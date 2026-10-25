"""혈액검체 탭: 합성 메모리 시연의 흐름·경계를 실제 링크를 따라가며 확인한다."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from app.modules.screening_lab.dashboard import LabDashboardService


THURSDAY_10 = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


@pytest.fixture
def app():
    clock = FixedClock(THURSDAY_10)
    return create_app(ManualDashboardService(clock=clock), lab_service=LabDashboardService(clock=clock))


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def lab(app):
    return app.state.lab_service


def first_in(app, stage: str):
    return lab(app).snapshot(stage=stage)["cases"][0]


def post(client, app, path: str, **data: str):
    return client.post(path, data={"csrf_token": app.state.csrf_token, **data}, follow_redirects=False)


def test_seed_covers_every_stage(app):
    snap = lab(app).snapshot()
    assert snap["total"] == 10
    assert snap["counts"] == {"RESULT_PENDING": 1, "CRITICAL_PENDING": 2, "CHECK_PENDING": 7, "DONE": 0}


def test_sidebar_links_to_lab_and_page_lists_results(client):
    page = client.get("/dashboard").text
    assert 'href="/lab"' in page
    response = client.get("/lab")
    assert response.status_code == 200
    assert "검진 혈액검체 장부" in response.text
    assert "AST 48 H, GGT 61 H" in response.text and "정상" in response.text
    assert not re.search(r"(?:src|href)\s*=\s*['\"]\s*(?:https?:)?//", response.text, re.I)


def test_list_masks_names_and_detail_shows_selected_name(client, app):
    cases = lab(app).snapshot(stage="CHECK_PENDING")["cases"]
    selected, others = cases[1], cases[:1] + cases[2:]
    page = client.get(f"/lab?stage=CHECK_PENDING&selected_id={selected.id}").text
    # 목록은 이름을 가리고, 선택한 건만 상세 패널에 이름이 보인다.
    assert selected.record.patient_name in page
    assert all(case.record.patient_name not in page for case in others)


def test_stat_cards_link_to_each_stage(client, app):
    page = client.get("/lab").text
    for stage in ("RESULT_PENDING", "CRITICAL_PENDING", "CHECK_PENDING", "DONE"):
        href = f"/lab?stage={stage}"
        assert f'href="{href}"' in page
        filtered = client.get(href)
        assert filtered.status_code == 200


def test_unknown_stage_rejected(client):
    assert client.get("/lab?stage=NOPE").status_code == 422


def test_critical_must_be_reported_before_check(client, app):
    case = first_in(app, "CRITICAL_PENDING")
    assert "원장 보고 완료 기록" in client.get(f"/lab?selected_id={case.id}").text
    # 보고 전 확인 기록은 거부되고 상태가 바뀌지 않는다.
    assert post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원").status_code == 400
    assert lab(app).snapshot()["counts"]["CRITICAL_PENDING"] == 2

    response = post(client, app, f"/lab/cases/{case.id}/report-critical", reported_by="테스트사무장")
    assert response.status_code == 303 and response.headers["location"] == f"/lab?selected_id={case.id}"
    reported = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert reported.stage == "CHECK_PENDING"
    assert reported.critical_reported_by == "테스트사무장" and reported.critical_reported_at == THURSDAY_10

    page = client.get(response.headers["location"]).text
    assert "테스트사무장" in page and "2026.11.05 10:00 보고" in page

    assert post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원").status_code == 303
    done = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert done.stage == "DONE" and done.checked_by == "테스트직원"
    assert "확인된 기록입니다" in client.get(f"/lab?selected_id={case.id}").text


def test_normal_result_can_be_checked_directly(client, app):
    case = first_in(app, "CHECK_PENDING")
    assert post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원").status_code == 303
    assert lab(app).snapshot()["counts"]["DONE"] == 1


def test_pending_result_cannot_be_checked_or_reported(client, app):
    case = first_in(app, "RESULT_PENDING")
    assert post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원").status_code == 400
    assert post(client, app, f"/lab/cases/{case.id}/report-critical", reported_by="테스트직원").status_code == 400
    assert first_in(app, "RESULT_PENDING").id == case.id


@pytest.mark.parametrize("name", ["", "   ", "가" * 21])
def test_staff_name_is_required_and_bounded(client, app, name):
    case = first_in(app, "CRITICAL_PENDING")
    assert post(client, app, f"/lab/cases/{case.id}/report-critical", reported_by=name).status_code == 422
    assert lab(app).snapshot()["counts"]["CRITICAL_PENDING"] == 2


def test_csrf_is_required(client, app):
    case = first_in(app, "CHECK_PENDING")
    response = client.post(f"/lab/cases/{case.id}/check", data={"checked_by": "테스트직원"})
    assert response.status_code == 403
    assert lab(app).snapshot()["counts"]["DONE"] == 0


def test_unknown_case_is_404(client, app):
    assert post(client, app, f"/lab/cases/{UUID(int=999)}/check", checked_by="테스트직원").status_code == 404


def test_reset_restores_seed(client, app):
    case = first_in(app, "CHECK_PENDING")
    post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원")
    assert post(client, app, "/lab/reset").headers["location"] == "/lab"
    assert lab(app).snapshot()["counts"]["DONE"] == 0


def test_service_repr_hides_patient_values(app):
    case = first_in(app, "CHECK_PENDING")
    assert case.record.patient_name not in repr(case)


def test_lab_routes_do_not_touch_pathology_module():
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "app/modules/screening_lab"
    for path in source.glob("*.py"):
        assert "endoscopy_pathology" not in path.read_text(encoding="utf-8")
