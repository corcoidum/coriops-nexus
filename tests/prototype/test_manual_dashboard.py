"""실환자·외부 연결 없이 수동 업무 dashboard의 흐름과 경계를 확인한다."""

from __future__ import annotations

from datetime import date
import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


STAGES = ("RESULT_PENDING", "DOCTOR_PENDING", "NOTIFY_PENDING", "DONE")


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def snapshot(app, *, stage: str = "ALL", selected_id: UUID | None = None):
    return app.state.dashboard_service.snapshot(stage=stage, selected_id=selected_id)


def case_in_stage(app, stage: str):
    return next(case for case in snapshot(app)["cases"] if case.stage == stage)


def current_case(app, case_id: UUID):
    return next(case for case in snapshot(app)["cases"] if case.id == case_id)


def post_case(client, app, case_id: UUID, action: str, **data: str):
    return client.post(
        f"/demo/cases/{case_id}/{action}",
        data={"csrf_token": app.state.csrf_token, **data},
        follow_redirects=False,
    )


def case_state(app, case_id: UUID) -> tuple[object, ...]:
    """거절된 요청이 직원 입력을 바꾸지 않는지 확인할 값만 고정한다."""
    case = current_case(app, case_id)
    return (
        case.stage,
        case.result_summary,
        case.site_summary,
        case.followup_due,
        case.no_followup_reason,
        case.notified,
        case.contact_attempts,
    )


def test_seed_has_eight_independent_cases_and_all_four_stage_counts(app):
    first = snapshot(app)
    second_app = create_app()
    second = snapshot(second_app)

    assert len(first["cases"]) == 8
    assert len({case.id for case in first["cases"]}) == 8
    assert all(isinstance(case.id, UUID) for case in first["cases"])
    assert set(first["counts"]) == set(STAGES)
    assert sum(first["counts"].values()) == 8
    assert all(first["counts"][stage] >= 1 for stage in STAGES)
    assert first["counts"] == {
        "RESULT_PENDING": 3, "DOCTOR_PENDING": 2, "NOTIFY_PENDING": 2, "DONE": 1,
    }
    assert first["counts"] == second["counts"]
    assert isinstance(first["today"], date)
    assert app.state.dashboard_service is not second_app.state.dashboard_service


@pytest.mark.parametrize("stage", STAGES)
def test_stage_filter_preserves_global_counts_and_returns_matching_rows(app, stage):
    all_cases = snapshot(app)
    filtered = snapshot(app, stage=stage)

    assert filtered["cases"]
    assert all(case.stage == stage for case in filtered["cases"])
    assert len(filtered["cases"]) == all_cases["counts"][stage]
    assert filtered["counts"] == all_cases["counts"]


def test_snapshot_can_select_a_known_case(app):
    chosen = case_in_stage(app, "DOCTOR_PENDING")

    selected = snapshot(app, selected_id=chosen.id)["selected"]

    assert selected.id == chosen.id


def test_home_redirects_to_the_synthetic_dashboard(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_dashboard_is_local_html_and_prevents_browser_caching(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "조직검체" in response.text
    assert "합성" in response.text
    assert "no-store" in response.headers.get("cache-control", "")
    # 첫 UI는 local 자원만 사용하며 외부 CDN에 조회를 발생시키지 않는다.
    assert not re.search(r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//", response.text, re.I)


def test_manual_workflow_keeps_the_entered_date_and_counts_contact_attempts(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    before_counts = snapshot(app)["counts"].copy()
    untouched_app = create_app()
    untouched_counts = snapshot(untouched_app)["counts"].copy()

    received = post_case(
        client, app, case_id, "receive",
        result_summary="합성 결과 약어", site_summary="합성 검사위치",
    )
    assert received.status_code == 303
    case = current_case(app, case_id)
    assert case.stage == "DOCTOR_PENDING"
    assert case.result_summary == "합성 결과 약어"
    assert case.site_summary == "합성 검사위치"

    decided = post_case(
        client, app, case_id, "decide", mode="required", due_date="2030-01-15",
    )
    assert decided.status_code == 303
    assert current_case(app, case_id).stage == "NOTIFY_PENDING"
    assert current_case(app, case_id).followup_due == date(2030, 1, 15)
    before_attempts = current_case(app, case_id).contact_attempts

    not_reached = post_case(client, app, case_id, "notify", outcome="no_answer")
    assert not_reached.status_code == 303
    assert current_case(app, case_id).stage == "NOTIFY_PENDING"
    assert current_case(app, case_id).notified is False
    assert current_case(app, case_id).contact_attempts == before_attempts + 1

    reached = post_case(client, app, case_id, "notify", outcome="reached")
    assert reached.status_code == 303
    assert current_case(app, case_id).stage == "DONE"
    assert current_case(app, case_id).notified is True
    assert current_case(app, case_id).contact_attempts == before_attempts + 2
    after_counts = snapshot(app)["counts"]
    assert after_counts["RESULT_PENDING"] == before_counts["RESULT_PENDING"] - 1
    assert after_counts["DONE"] == before_counts["DONE"] + 1
    assert sum(after_counts.values()) == 8
    assert snapshot(untouched_app)["counts"] == untouched_counts


def test_explicit_no_followup_reason_allows_notification_without_a_date(client, app):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id

    decision = post_case(
        client, app, case_id, "decide", mode="not_required", reason="합성 원장 지시 기록",
    )

    assert decision.status_code == 303
    case = current_case(app, case_id)
    assert case.stage == "NOTIFY_PENDING"
    assert case.followup_due is None
    assert case.no_followup_reason == "합성 원장 지시 기록"
    assert post_case(client, app, case_id, "notify", outcome="reached").status_code == 303
    assert current_case(app, case_id).stage == "DONE"


@pytest.mark.parametrize(
    ("stage", "action", "data"),
    [
        ("RESULT_PENDING", "decide", {"mode": "required", "due_date": "2030-01-15"}),
        ("RESULT_PENDING", "notify", {"outcome": "reached"}),
        ("DOCTOR_PENDING", "notify", {"outcome": "reached"}),
    ],
)
def test_out_of_order_actions_are_rejected_without_changing_the_case(client, app, stage, action, data):
    case_id = case_in_stage(app, stage).id
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, action, **data)

    assert response.status_code == 400
    assert case_state(app, case_id) == before


@pytest.mark.parametrize(
    "data",
    [
        {"mode": "required"},
        {"mode": "required", "due_date": "not-a-date"},
        {"mode": "required", "due_date": "2030-02-30"},
        {"mode": "required", "due_date": "20300115"},
        {"mode": "required", "due_date": "2030-W03-2"},
        {"mode": "required", "due_date": "2000-01-15"},
        {"mode": "not_required"},
        {"mode": "not_required", "reason": "  "},
        {"mode": "automatic", "due_date": "2030-01-15"},
    ],
)
def test_invalid_decisions_are_rejected_without_changing_the_case(client, app, data):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, "decide", **data)

    assert response.status_code == 422
    assert case_state(app, case_id) == before


def test_due_date_of_today_is_accepted(client, app):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id
    today = snapshot(app)["today"]

    response = post_case(client, app, case_id, "decide", mode="required", due_date=today.isoformat())

    assert response.status_code == 303
    assert current_case(app, case_id).followup_due == today


@pytest.mark.parametrize(
    ("stage", "action", "data"),
    [
        ("RESULT_PENDING", "receive", {"result_summary": "합성", "site_summary": "합성"}),
        ("DOCTOR_PENDING", "decide", {"mode": "required", "due_date": "2030-01-15"}),
        ("NOTIFY_PENDING", "notify", {"outcome": "reached"}),
    ],
)
def test_case_that_left_the_filter_is_not_selected_on_return(client, app, stage, action, data):
    case_id = case_in_stage(app, stage).id

    response = post_case(client, app, case_id, action, stage=stage, **data)

    assert response.status_code == 303
    assert response.headers["location"] == f"/dashboard?stage={stage}"
    page = snapshot(app, stage=stage)
    assert all(case.stage == stage for case in page["cases"])
    assert page["selected"] is None or page["selected"].stage == stage
    assert client.get(response.headers["location"]).status_code == 200


def test_case_still_in_the_filter_stays_selected_on_return(client, app):
    case_id = case_in_stage(app, "NOTIFY_PENDING").id

    response = post_case(client, app, case_id, "notify", stage="NOTIFY_PENDING", outcome="no_answer")

    assert response.status_code == 303
    assert response.headers["location"] == f"/dashboard?stage=NOTIFY_PENDING&selected_id={case_id}"
    assert client.get(response.headers["location"]).status_code == 200


@pytest.mark.parametrize("stage", ["ALL", "UNKNOWN", ""])
def test_unknown_or_all_stage_returns_to_the_full_list(client, app, stage):
    case_id = case_in_stage(app, "RESULT_PENDING").id

    response = post_case(
        client, app, case_id, "receive", stage=stage, result_summary="합성", site_summary="합성",
    )

    assert response.headers["location"] == f"/dashboard?selected_id={case_id}"


def test_dashboard_forms_carry_the_current_stage(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id

    page = client.get(f"/dashboard?stage=RESULT_PENDING&selected_id={case_id}")

    assert '<input type="hidden" name="stage" value="RESULT_PENDING">' in page.text


def test_invalid_notification_outcome_is_rejected(client, app):
    case_id = case_in_stage(app, "NOTIFY_PENDING").id
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, "notify", outcome="automatic")

    assert response.status_code == 422
    assert case_state(app, case_id) == before


@pytest.mark.parametrize(
    "data",
    [
        {"result_summary": "", "site_summary": "합성"},
        {"result_summary": "합성", "site_summary": "  "},
        {"result_summary": "A" * 121, "site_summary": "합성"},
        {"result_summary": "합성", "site_summary": "A" * 81},
    ],
)
def test_empty_or_too_long_result_fields_are_rejected(client, app, data):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, "receive", **data)

    assert response.status_code == 422
    assert case_state(app, case_id) == before


@pytest.mark.parametrize("token", ["INVALID", "잘못된 토큰", ""])
def test_wrong_csrf_token_cannot_change_a_case(client, app, token):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    before = case_state(app, case_id)

    response = client.post(
        f"/demo/cases/{case_id}/receive",
        data={"csrf_token": token, "result_summary": "합성", "site_summary": "합성"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert case_state(app, case_id) == before


def test_known_seed_only_unknown_case_is_rejected(client, app):
    before = snapshot(app)["counts"].copy()

    response = post_case(
        client, app, uuid4(), "receive", result_summary="합성", site_summary="합성",
    )

    assert response.status_code == 404
    assert snapshot(app)["counts"] == before
    assert len(snapshot(app)["cases"]) == 8


def test_staff_text_is_autoescaped_when_rendered(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    unsafe = '<script>alert("synthetic")</script>'
    response = post_case(
        client, app, case_id, "receive", result_summary=unsafe, site_summary="합성 위치",
    )
    assert response.status_code == 303

    page = client.get(f"/dashboard?selected_id={case_id}")

    assert page.status_code == 200
    assert unsafe not in page.text
    assert "&lt;script&gt;" in page.text


def test_reset_requires_csrf_and_restores_the_eight_seed_cases(client, app):
    original_counts = snapshot(app)["counts"].copy()
    case_id = case_in_stage(app, "RESULT_PENDING").id
    assert post_case(
        client, app, case_id, "receive", result_summary="합성 변경", site_summary="합성 위치",
    ).status_code == 303
    changed_counts = snapshot(app)["counts"].copy()

    denied = client.post("/demo/reset", data={"csrf_token": "INVALID"}, follow_redirects=False)
    assert denied.status_code == 403
    assert snapshot(app)["counts"] == changed_counts
    restored = client.post(
        "/demo/reset", data={"csrf_token": app.state.csrf_token}, follow_redirects=False,
    )
    assert restored.status_code == 303
    assert snapshot(app)["counts"] == original_counts
    assert len(snapshot(app)["cases"]) == 8
