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


def test_home_shows_both_ledgers_and_links_work(client):
    page = client.get("/").text
    assert "조직검체 장부 열기" in page and "혈액검체 장부 열기" in page
    for href in re.findall(r'class="today-(?:row[^"]*|go)" href="([^"]+)"', page):
        assert client.get(href.replace("&amp;", "&")).status_code == 200, href
    assert 'href="/lab?stage=CRITICAL_PENDING"' in page


def test_sidebar_groups_ledgers_separately(client):
    page = client.get("/dashboard").text
    tissue = page.index('class="nav-group tissue"')
    blood = page.index('class="nav-group blood"')
    assert tissue < page.index('href="/ledger/excel"') < blood < page.index('href="/lab"')


def test_critical_alert_shows_on_every_ledger_page_until_reported(client, app):
    for path in ("/", "/dashboard", "/ledger/excel", "/lab"):
        assert "⚠ 위급치<span class=\"alert-long\"> 원장 보고 대기</span> 2건" in client.get(path).text, path
    for case in lab(app).snapshot(stage="CRITICAL_PENDING")["cases"]:
        post(client, app, f"/lab/cases/{case.id}/report-critical", reported_by="테스트사무장")
    assert lab(app).critical_pending_count() == 0
    assert "critical-alert" not in client.get("/dashboard").text


def test_ledger_chips_mark_each_page(client):
    assert 'ledger-chip tissue' in client.get("/dashboard").text
    lab_page = client.get("/lab").text
    assert 'ledger-chip blood' in lab_page and '<span class="ledger-chip tissue">조직검체</span> 장부' not in lab_page


def test_service_repr_hides_patient_values(app):
    case = first_in(app, "CHECK_PENDING")
    assert case.record.patient_name not in repr(case)


def test_lab_routes_do_not_touch_pathology_module():
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "app/modules/screening_lab"
    for path in source.glob("*.py"):
        assert "endoscopy_pathology" not in path.read_text(encoding="utf-8")


# ---------- 결과 직접 입력(B14·B16)·관리자 위급치 표기(B15)

def result_form(**changes):
    data = {"report_ref": "2026.11.04-0000001", "report_date": "2026-11-05", "entered_by": "테스트직원",
            "item_name": ["AST", "GGT"], "item_value": ["52", "70"], "item_flag": ["H", "H"],
            "qual_name": ["HBsAg", "Anti-HBs"], "qual_value": ["Neg", "Pos"]}
    data.update(changes)
    return data


def test_pending_case_shows_entry_form_with_hepatitis_choices(client, app):
    case = first_in(app, "RESULT_PENDING")
    page = client.get(f"/lab?selected_id={case.id}").text
    assert f'action="/lab/cases/{case.id}/result"' in page
    assert 'value="HBsAg"' in page and 'value="Anti-HBs"' in page and 'value="Anti-HCV"' not in page


def test_entered_result_lists_flagged_and_hepatitis_then_waits_for_check(client, app):
    case = first_in(app, "RESULT_PENDING")
    response = client.post(f"/lab/cases/{case.id}/result",
                           data={"csrf_token": app.state.csrf_token, **result_form()}, follow_redirects=False)
    assert response.status_code == 303
    entered = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert entered.stage == "CHECK_PENDING" and entered.result_entered_by == "테스트직원"
    assert lab(app).result_text(entered) == "AST 52 H, GGT 70 H, HBsAg Neg, Anti-HBs Pos"
    assert entered.record.report_ref == "2026.11.04-0000001"


def test_no_flagged_items_is_recorded_as_normal(client, app):
    case = first_in(app, "RESULT_PENDING")
    data = result_form(item_name=[""], item_value=[""], item_flag=[""], no_flagged="1")
    assert post(client, app, f"/lab/cases/{case.id}/result", **data).status_code == 303
    entered = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert lab(app).result_text(entered) == "정상, HBsAg Neg, Anti-HBs Pos"


@pytest.mark.parametrize("changes", [
    {"item_name": [""], "item_value": [""], "item_flag": [""]},          # H/L도 '없음' 확인도 없음
    {"no_flagged": "1"},                                                   # 항목과 '없음'을 함께 보냄
    {"item_name": ["SGOT"], "item_value": ["52"], "item_flag": ["H"]},    # 목록 밖 항목
    {"item_name": ["AST"], "item_value": ["52"], "item_flag": [""]},      # 판정 누락
    {"item_name": ["AST", "AST"], "item_value": ["52", "60"], "item_flag": ["H", "H"]},
    {"qual_value": ["Neg", ""]},                                           # 간염 선택 누락
    {"report_date": "2099-01-01"},
    {"report_ref": " "},
])
def test_invalid_result_entry_changes_nothing(client, app, changes):
    case = first_in(app, "RESULT_PENDING")
    assert post(client, app, f"/lab/cases/{case.id}/result", **result_form(**changes)).status_code == 422
    assert first_in(app, "RESULT_PENDING").id == case.id


def test_manager_marks_critical_then_report_is_required(client, app):
    case = next(c for c in lab(app).snapshot(stage="CHECK_PENDING")["cases"] if any(i.flag for i in c.record.items))
    flagged = next(i.name for i in case.record.items if i.flag)
    page = client.get(f"/lab?selected_id={case.id}").text
    assert "위급치 표기 (관리자 확인 후)" in page
    response = post(client, app, f"/lab/cases/{case.id}/mark-critical", critical_items=[flagged],
                    marked_by="테스트관리자")
    assert response.status_code == 303
    marked = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert marked.stage == "CRITICAL_PENDING" and marked.critical_marked_by == "테스트관리자"
    assert lab(app).critical_pending_count() == 3
    assert "관리자 위급치 표기" in client.get(f"/lab?selected_id={case.id}").text


def test_critical_can_only_be_chosen_from_flagged_items(client, app):
    case = next(c for c in lab(app).snapshot(stage="CHECK_PENDING")["cases"] if any(i.flag for i in c.record.items))
    unflagged = next((i.name for i in case.record.items if not i.flag), "Hb")
    for items in ([], [unflagged]):
        assert post(client, app, f"/lab/cases/{case.id}/mark-critical", critical_items=items,
                    marked_by="테스트관리자").status_code == 422
    assert lab(app).critical_pending_count() == 2
