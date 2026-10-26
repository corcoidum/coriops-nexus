"""실환자·외부 연결 없이 조직검체 장부 dashboard의 흐름과 경계를 확인한다."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService


STAGES = ("HANDOFF_PENDING", "RESULT_PENDING", "DOCTOR_PENDING", "FOLLOWUP", "CLOSED")
# 2026-11-05(목) 10:00 KST. 씨젠 수령 15:00 전.
THURSDAY_10 = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


def make_app(moment: datetime = THURSDAY_10):
    return create_app(ManualDashboardService(clock=FixedClock(moment)))


@pytest.fixture
def app():
    return make_app()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def snapshot(app, **kwargs):
    return app.state.dashboard_service.snapshot(**kwargs)


def stage_of(app, case_id: UUID) -> str:
    return snapshot(app)["stages"][case_id]


def case_in_stage(app, stage: str):
    snap = snapshot(app, stage=stage)
    return snap["cases"][0]


def current_case(app, case_id: UUID):
    return next(case for case in snapshot(app)["cases"] if case.id == case_id)


def post(client, app, path: str, **data: str):
    return client.post(path, data={"csrf_token": app.state.csrf_token, **data}, follow_redirects=False)


def post_case(client, app, case_id: UUID, action: str, **data: str):
    return post(client, app, f"/ledger/cases/{case_id}/{action}", **data)


def handoff_data(count: str, **overrides: str) -> dict[str, str]:
    data = {"registered_by": "테스트 접수자", "handed_by": "테스트 인계자",
            "receiver_name": "테스트 수령인", "confirmed_count": count}
    return {**data, **overrides}


def receive_data(**overrides: str) -> dict[str, str]:
    data = {"report_ref": "T9799999", "result_notation": "TA#2(L), H#1", "site_summary": "합성 위치"}
    return {**data, **overrides}


def case_state(app, case_id: UUID) -> tuple[object, ...]:
    """거절된 요청이 입력을 바꾸지 않는지 확인할 값만 고정한다."""
    case = current_case(app, case_id)
    return (stage_of(app, case_id), case.handoff_id, case.report_ref, case.findings, case.sydney,
            case.site, case.followup_due, case.no_followup_reason, case.followup_done_on)


def all_states(app):
    return {case.id: case_state(app, case.id) for case in snapshot(app)["cases"]}


# ---------- seed·조회

def test_seed_has_fourteen_independent_cases_in_every_stage(app):
    first = snapshot(app)
    second_app = make_app()

    assert first["total"] == 14
    assert len({case.id for case in first["cases"]}) == 14
    assert first["counts"] == {
        "HANDOFF_PENDING": 2, "RESULT_PENDING": 4, "DOCTOR_PENDING": 3, "FOLLOWUP": 3, "CLOSED": 2,
    }
    assert first["flags"] == {"result_delayed": 1, "code_review": 1, "imported_pending": 0,
                              "followup_due": 1, "followup_overdue": 1, "followup_soon": 1}
    assert {case.kind for case in first["cases"]} == {"BIOPSY", "CLO", "STOOL"}
    assert snapshot(second_app)["counts"] == first["counts"]
    assert app.state.dashboard_service is not second_app.state.dashboard_service


@pytest.mark.parametrize("stage", STAGES)
def test_stage_filter_preserves_global_counts_and_returns_matching_rows(app, stage):
    all_cases = snapshot(app)
    filtered = snapshot(app, stage=stage)

    assert filtered["cases"]
    assert all(filtered["stages"][case.id] == stage for case in filtered["cases"])
    assert len(filtered["cases"]) == all_cases["counts"][stage]
    assert filtered["counts"] == all_cases["counts"]


def test_unknown_stage_is_rejected(client):
    assert client.get("/dashboard?stage=NOTIFY_PENDING").status_code == 422


def test_home_redirects_to_the_synthetic_dashboard(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_dashboard_is_local_html_and_prevents_browser_caching(client):
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "조직검체" in response.text and "합성" in response.text
    assert "오늘 수탁기관 인계" in response.text
    assert "no-store" in response.headers.get("cache-control", "")
    assert not re.search(r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//", response.text, re.I)


@pytest.mark.parametrize("stage", ("ALL", *STAGES))
def test_every_stage_page_renders(client, stage):
    assert client.get(f"/dashboard?stage={stage}").status_code == 200


def test_followup_list_puts_overdue_first_then_nearest(app):
    rows = snapshot(app, stage="FOLLOWUP")
    texts = [rows["alerts"][case.id].text for case in rows["cases"]]

    assert texts == ["재검 기한 10일 경과", "재검 D-20", "재검 D-300"]
    assert [rows["alerts"][case.id].level for case in rows["cases"]] == ["danger", "warn", "normal"]


def test_result_waiting_is_flagged_only_after_the_business_day_threshold(app):
    rows = snapshot(app, stage="RESULT_PENDING")
    texts = sorted(rows["alerts"][case.id].text for case in rows["cases"])

    assert texts == ["검사 후 0진료일", "위탁 후 1진료일", "위탁 후 2진료일", "위탁 후 4진료일 · 지연"]


def test_doctor_page_hides_nothing_but_flags_unregistered_codes(app):
    rows = snapshot(app, stage="DOCTOR_PENDING")
    flagged = [case.result_notation for case in rows["cases"] if case.needs_review]

    assert flagged == ["TEST#1"]


# ---------- 오늘 인계

@pytest.mark.parametrize(("moment", "status", "level"), [
    (THURSDAY_10, "DUE", "warn"),
    (datetime(2026, 11, 5, 6, 30, tzinfo=timezone.utc), "OVERDUE", "danger"),   # 목 15:30
    (datetime(2026, 11, 4, 2, 30, tzinfo=timezone.utc), "OVERDUE", "danger"),   # 수 11:30
    (datetime(2026, 11, 4, 1, 30, tzinfo=timezone.utc), "DUE", "warn"),         # 수 10:30
    (datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc), "NO_PICKUP", "warn"),    # 일요일
    (datetime(2026, 12, 25, 1, 0, tzinfo=timezone.utc), "NO_PICKUP", "warn"),   # 공휴일
])
def test_pickup_status_follows_clinic_pickup_times(moment, status, level):
    pickup = snapshot(make_app(moment))["pickup"]

    assert (pickup["status"], pickup["level"]) == (status, level)
    assert pickup["pending_cases"] == 2
    assert pickup["pending_specimens"] == 4


def test_handoff_moves_all_pending_cases_and_records_three_parties(client, app):
    pending = [case.id for case in snapshot(app, stage="HANDOFF_PENDING")["cases"]]

    response = post(client, app, "/ledger/handoff", **handoff_data("4"))

    assert response.status_code == 303
    for case_id in pending:
        case = current_case(app, case_id)
        assert stage_of(app, case_id) == "RESULT_PENDING"
        assert case.entrusted_on == date(2026, 11, 5)
    pickup = snapshot(app)["pickup"]
    assert pickup["status"] == "DONE"
    record = pickup["handed_today"][0]
    assert (record.registered_by, record.handed_by, record.receiver_name) == (
        "테스트 접수자", "테스트 인계자", "테스트 수령인")
    assert (record.case_count, record.specimen_count) == (2, 4)
    page = client.get("/dashboard").text
    assert "테스트 수령인" in page
    assert "✓ 10:00 2건 4병" in page  # KST 표시


@pytest.mark.parametrize("data", [
    handoff_data("3"),
    handoff_data("5"),
    handoff_data("four"),
    handoff_data(""),
    handoff_data("4", registered_by="  "),
    handoff_data("4", handed_by=""),
    handoff_data("4", receiver_name="가" * 21),
])
def test_wrong_count_or_missing_names_block_the_handoff(client, app, data):
    before = all_states(app)

    response = post(client, app, "/ledger/handoff", **data)

    assert response.status_code == 422
    assert all_states(app) == before
    assert snapshot(app)["pickup"]["handed_today"] == []


def test_count_mismatch_message_shows_both_numbers(client, app):
    response = post(client, app, "/ledger/handoff", **handoff_data("3"))

    assert "장부 4병" in response.text and "확인 3병" in response.text


def test_second_handoff_without_pending_cases_is_rejected(client, app):
    assert post(client, app, "/ledger/handoff", **handoff_data("4")).status_code == 303

    assert post(client, app, "/ledger/handoff", **handoff_data("0")).status_code == 400


def test_handed_case_starts_counting_result_days_from_handoff(client):
    later = make_app(datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc))  # 월요일
    service = later.state.dashboard_service
    with TestClient(later) as test_client:
        post(test_client, later, "/ledger/handoff", **handoff_data("4"))
    service._clock.moment = datetime(2026, 11, 12, 1, 0, tzinfo=timezone.utc)  # 목요일: 3진료일
    alerts = {service.snapshot()["alerts"][UUID(int=n)].text for n in (1, 2)}

    assert alerts == {"위탁 후 3진료일 · 지연"}


# ---------- 결과 입력 (A11: 코드만)

def test_result_codes_are_parsed_and_normalized(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id

    response = post_case(client, app, case_id, "receive",
                         **receive_data(result_notation=" TA#2(L) ,H#1 ,inf.p#1"))

    assert response.status_code == 303
    case = current_case(app, case_id)
    assert stage_of(app, case_id) == "DOCTOR_PENDING"
    assert case.result_notation == "TA#2(L), H#1, INF_P#1"
    assert [f.lesion_count for f in case.findings] == [2, 1, 1]
    assert case.findings[0].modifiers == ("L",)
    assert case.needs_review is False


def test_unregistered_code_is_kept_and_flagged_for_dictionary_review(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id

    post_case(client, app, case_id, "receive", **receive_data(result_notation="NEWCODE#1(zz)"))

    case = current_case(app, case_id)
    assert case.result_notation == "NEWCODE#1(zz)"
    assert case.needs_review is True
    assert "· 검토" not in case.result_notation


def test_sydney_grades_are_structured_for_gastric_cases(client, app):
    case_id = next(c.id for c in snapshot(app, stage="RESULT_PENDING")["cases"] if c.procedure_type == "stomach" and c.kind == "BIOPSY")

    response = post_case(client, app, case_id, "receive",
                         **receive_data(result_notation="CAG#1(im)", sydney_notation="HP-/Neu++/Mon+++/Atr+/IM-"))

    assert response.status_code == 303
    assert dict(current_case(app, case_id).sydney) == {
        "h_pylori": "NEG", "neutrophil": "POS2", "mononuclear": "POS3", "atrophy": "POS1",
        "intestinal_metaplasia": "NEG"}
    page = client.get(f"/dashboard?selected_id={case_id}")
    assert "HP-/Neu++/Mon+++/Atr+/IM-" in page.text


@pytest.mark.parametrize("data", [
    receive_data(result_notation="tubular adenoma with low grade dysplasia"),
    receive_data(result_notation="TA#2(L),"),
    receive_data(result_notation=""),
    receive_data(result_notation=", ".join(["H#1"] * 11)),
    receive_data(report_ref=""),
    receive_data(report_ref="12"),
    receive_data(report_ref="T97 0001"),
    receive_data(site_summary="  "),
    receive_data(site_summary="A" * 81),
    receive_data(sydney_notation="HP positive"),
    receive_data(sydney_notation="HP-/HP+"),
])
def test_invalid_result_entries_are_rejected_without_changing_the_case(client, app, data):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, "receive", **data)

    assert response.status_code == 422
    assert case_state(app, case_id) == before


def test_sydney_is_rejected_for_colon_cases(client, app):
    case_id = next(c.id for c in snapshot(app, stage="RESULT_PENDING")["cases"] if c.procedure_type == "colon")
    before = case_state(app, case_id)

    response = post_case(client, app, case_id, "receive", **receive_data(sydney_notation="HP-"))

    assert response.status_code == 422
    assert case_state(app, case_id) == before


def test_duplicate_report_reference_is_rejected(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    taken = case_in_stage(app, "DOCTOR_PENDING").report_ref

    response = post_case(client, app, case_id, "receive", **receive_data(report_ref=taken))

    assert response.status_code == 422
    assert stage_of(app, case_id) == "RESULT_PENDING"


def test_error_page_does_not_echo_the_submitted_text(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id

    response = post_case(client, app, case_id, "receive",
                         **receive_data(result_notation="합성 판독문 원문 문장"))

    assert response.status_code == 422
    assert "합성 판독문 원문 문장" not in response.text


# ---------- 원장 지시·재검

def test_required_decision_moves_to_followup_and_completion_closes_it(client, app):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id

    assert post_case(client, app, case_id, "decide", mode="required", due_date="2030-01-15").status_code == 303
    assert stage_of(app, case_id) == "FOLLOWUP"
    assert current_case(app, case_id).followup_due == date(2030, 1, 15)

    assert post_case(client, app, case_id, "followup-done", done_on="2026-11-05").status_code == 303
    assert stage_of(app, case_id) == "CLOSED"
    assert current_case(app, case_id).followup_done_on == date(2026, 11, 5)


def test_no_followup_reason_closes_without_a_date(client, app):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id

    response = post_case(client, app, case_id, "decide", mode="not_required", reason="합성 원장 지시 기록")

    assert response.status_code == 303
    case = current_case(app, case_id)
    assert stage_of(app, case_id) == "CLOSED"
    assert case.followup_due is None
    assert case.no_followup_reason == "합성 원장 지시 기록"


@pytest.mark.parametrize("data", [
    {"mode": "required"},
    {"mode": "required", "due_date": "not-a-date"},
    {"mode": "required", "due_date": "2030-02-30"},
    {"mode": "not_required"},
    {"mode": "not_required", "reason": "  "},
    {"mode": "automatic", "due_date": "2030-01-15"},
    # fromisoformat이 받는 압축·주차 표기와 오늘(2026-11-05) 이전 날짜는 거부한다.
    {"mode": "required", "due_date": "20300115"},
    {"mode": "required", "due_date": "2030-W03-2"},
    {"mode": "required", "due_date": "2026-11-04"},
])
def test_invalid_decisions_are_rejected_without_changing_the_case(client, app, data):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id
    before = case_state(app, case_id)

    assert post_case(client, app, case_id, "decide", **data).status_code == 422
    assert case_state(app, case_id) == before


def test_due_date_of_today_is_accepted(client, app):
    case_id = case_in_stage(app, "DOCTOR_PENDING").id

    assert post_case(client, app, case_id, "decide", mode="required", due_date="2026-11-05").status_code == 303
    assert current_case(app, case_id).followup_due == date(2026, 11, 5)


@pytest.mark.parametrize(("stage", "action", "data"), [
    ("RESULT_PENDING", "receive", receive_data()),
    ("DOCTOR_PENDING", "decide", {"mode": "required", "due_date": "2030-01-15"}),
    ("FOLLOWUP", "followup-done", {"done_on": "2026-11-05"}),
])
def test_case_that_left_the_filter_is_not_selected_on_return(client, app, stage, action, data):
    case = case_in_stage(app, stage)

    response = post_case(client, app, case.id, action, stage=stage, kind=case.kind, **data)

    assert response.status_code == 303
    assert response.headers["location"] == f"/dashboard?stage={stage}&kind={case.kind}"
    assert stage_of(app, case.id) != stage
    assert client.get(response.headers["location"]).status_code == 200


@pytest.mark.parametrize("stage", ["", "ALL", "UNKNOWN"])
def test_without_a_stage_filter_the_case_stays_selected(client, app, stage):
    case = case_in_stage(app, "DOCTOR_PENDING")

    response = post_case(client, app, case.id, "decide", stage=stage, kind="ALL",
                         mode="required", due_date="2030-01-15")

    assert response.headers["location"] == f"/dashboard?selected_id={case.id}"


def test_case_forms_carry_the_current_view(client, app):
    case = case_in_stage(app, "DOCTOR_PENDING")

    page = client.get(f"/dashboard?stage=DOCTOR_PENDING&kind={case.kind}&selected_id={case.id}").text

    assert '<input type="hidden" name="stage" value="DOCTOR_PENDING">' in page
    assert f'<input type="hidden" name="kind" value="{case.kind}">' in page


@pytest.mark.parametrize("done_on", ["", "2026-11-06", "2026-13-01"])
def test_followup_completion_needs_a_past_or_today_date(client, app, done_on):
    case_id = case_in_stage(app, "FOLLOWUP").id
    before = case_state(app, case_id)

    assert post_case(client, app, case_id, "followup-done", done_on=done_on).status_code == 422
    assert case_state(app, case_id) == before


@pytest.mark.parametrize(("stage", "action", "data"), [
    ("HANDOFF_PENDING", "receive", receive_data()),
    ("RESULT_PENDING", "decide", {"mode": "required", "due_date": "2030-01-15"}),
    ("DOCTOR_PENDING", "followup-done", {"done_on": "2026-11-05"}),
    ("CLOSED", "followup-done", {"done_on": "2026-11-05"}),
    ("FOLLOWUP", "receive", receive_data()),
])
def test_out_of_order_actions_are_rejected_without_changing_the_case(client, app, stage, action, data):
    case_id = case_in_stage(app, stage).id
    before = case_state(app, case_id)

    assert post_case(client, app, case_id, action, **data).status_code == 400
    assert case_state(app, case_id) == before


def test_patient_notification_step_is_removed(client, app):
    """결과 설명·환자 안내는 EMR에서 관리한다(A12)."""
    case_id = case_in_stage(app, "FOLLOWUP").id

    response = post_case(client, app, case_id, "notify", outcome="reached")

    assert response.status_code in (404, 405)


# ---------- 검색

@pytest.mark.parametrize(("query", "expected"), [
    ("T-0009", {"T-0009"}),
    ("T9700006", {"T-0006"}),
    ("ta", {"T-0006", "T-0009"}),
    ("CAG", {"T-0007", "T-0010"}),
    ("없는값", set()),
])
def test_search_by_chart_report_or_result_code(app, query, expected):
    assert {case.chart_no for case in snapshot(app, query=query)["cases"]} == expected


def test_search_combines_with_stage_filter_and_escapes_the_query(client, app):
    assert {c.chart_no for c in snapshot(app, stage="FOLLOWUP", query="CAG")["cases"]} == {"T-0010"}

    page = client.get("/dashboard", params={"q": "<b>x</b>"})
    assert page.status_code == 200
    assert "<b>x</b>" not in page.text
    assert client.get("/dashboard", params={"q": "A" * 31}).status_code == 422


# ---------- 보안 경계

@pytest.mark.parametrize("token", ["INVALID", "잘못된 토큰", ""])
def test_wrong_csrf_token_cannot_change_anything(client, app, token):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    before = all_states(app)

    for path, data in [
        (f"/ledger/cases/{case_id}/receive", receive_data()),
        ("/ledger/handoff", handoff_data("4")),
    ]:
        response = client.post(path, data={"csrf_token": token, **data}, follow_redirects=False)
        assert response.status_code == 403
    assert all_states(app) == before


def test_known_seed_only_unknown_case_is_rejected(client, app):
    before = snapshot(app)["counts"].copy()

    response = post_case(client, app, uuid4(), "receive", **receive_data())

    assert response.status_code == 404
    assert snapshot(app)["counts"] == before


def test_staff_text_is_autoescaped_when_rendered(client, app):
    case_id = case_in_stage(app, "RESULT_PENDING").id
    unsafe = '<script>alert("synthetic")</script>'
    assert post_case(client, app, case_id, "receive", **receive_data(site_summary=unsafe)).status_code == 303

    page = client.get(f"/dashboard?selected_id={case_id}")

    assert unsafe not in page.text
    assert "&lt;script&gt;" in page.text


def test_reset_requires_csrf_and_restores_the_seed(client, app):
    original = snapshot(app)["counts"].copy()
    assert post(client, app, "/ledger/handoff", **handoff_data("4")).status_code == 303
    changed = snapshot(app)["counts"].copy()

    denied = client.post("/ledger/reset", data={"csrf_token": "INVALID"}, follow_redirects=False)
    assert denied.status_code == 403
    assert snapshot(app)["counts"] == changed
    assert post(client, app, "/ledger/reset").status_code == 303
    assert snapshot(app)["counts"] == original
    assert snapshot(app)["pickup"]["handed_today"] == []


# ---------- 새 검사 접수

def register_data(**overrides: str) -> dict[str, str]:
    data = {"kind": "BIOPSY", "chart_no": "N-0001", "patient_name": "새환자", "exam_date": "2026-11-05",
            "procedure_type": "colon", "specimen_count": "2", "sex": "M", "age": "55", "site": ""}
    return {**data, **overrides}


@pytest.mark.parametrize(("kind", "expected"), [
    ("BIOPSY", "HANDOFF_PENDING"), ("STOOL", "HANDOFF_PENDING"), ("CLO", "RESULT_PENDING"),
])
def test_register_puts_new_exam_in_the_right_first_stage(client, app, kind, expected):
    response = post(client, app, "/ledger/register", **register_data(kind=kind))

    assert response.status_code == 303
    entry_id = UUID(response.headers["location"].split("selected_id=")[1].split("&")[0])
    assert stage_of(app, entry_id) == expected
    entry = current_case(app, entry_id)
    assert (entry.chart_no, entry.patient_name, entry.source) == ("N-0001", "새환자", "MANUAL")
    if kind == "CLO":
        assert entry.procedure_type == "stomach"


def test_registered_biopsy_joins_todays_handoff_count(client, app):
    post(client, app, "/ledger/register", **register_data())

    pickup = snapshot(app)["pickup"]
    assert (pickup["pending_cases"], pickup["pending_specimens"]) == (3, 6)


@pytest.mark.parametrize("data", [
    register_data(kind="LAB"),
    register_data(chart_no=""),
    register_data(chart_no="12 34"),
    register_data(patient_name=" "),
    register_data(exam_date="2026-11-06"),
    register_data(exam_date=""),
    register_data(procedure_type=""),
    register_data(procedure_type="knee"),
    register_data(specimen_count=""),
    register_data(specimen_count="0"),
    register_data(age="abc"),
    register_data(sex="X"),
    register_data(chart_no="T-0001", patient_name="다른이름"),
])
def test_invalid_registration_adds_nothing(client, app, data):
    before = snapshot(app)["total"]

    assert post(client, app, "/ledger/register", **data).status_code == 422
    assert snapshot(app)["total"] == before


def test_registration_form_and_kind_filter_render(client):
    form = client.get("/dashboard?new=1")
    assert form.status_code == 200 and "새 검사 접수" in form.text and 'name="kind"' in form.text
    clo = client.get("/dashboard?kind=CLO")
    assert clo.status_code == 200 and "T-0013" in clo.text and "T-0001" not in clo.text
    assert client.get("/dashboard?kind=LAB").status_code == 422


def test_list_shows_masked_names_but_detail_shows_full_name_for_entry(client, app):
    page = client.get("/dashboard?stage=HANDOFF_PENDING").text

    assert "테****1" in page  # 목록: 가운데 가림
    detail = client.get(f"/dashboard?selected_id={UUID(int=5)}").text
    assert "테스트환자5" in detail  # 입력 대상 확인용 상세


def test_long_lists_are_paginated(app):
    service = app.state.dashboard_service
    for number in range(60):
        service.register("CLO", f"P-{number:04}", f"페이지{number}", date(2026, 11, 5))

    first = snapshot(app, stage="RESULT_PENDING")
    second = snapshot(app, stage="RESULT_PENDING", page=2)
    assert (first["pages"], len(first["cases"]), len(second["cases"])) == (2, 50, first["matched"] - 50)


def test_links_on_the_page_keep_the_current_view_and_open(client):
    """화면의 종류 탭·행 링크를 실제로 따라가 본다(빈 stage로 422가 나던 회귀 방지)."""
    import html
    import re

    page = client.get("/dashboard?stage=RESULT_PENDING&kind=BIOPSY").text
    links = {html.unescape(h) for h in re.findall(r'href="(/dashboard\?[^"]+)"', page)}
    assert "/dashboard?stage=RESULT_PENDING&kind=CLO" in links
    assert any("stage=RESULT_PENDING&kind=BIOPSY&selected_id=" in h for h in links)
    for href in links:
        assert client.get(href).status_code == 200, href
