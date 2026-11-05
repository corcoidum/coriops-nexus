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
        href = "/critical" if stage == "CRITICAL_PENDING" else f"/lab?stage={stage}"
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
    assert 'href="/critical"' in page


def test_sidebar_groups_ledgers_separately(client):
    page = client.get("/dashboard").text
    tissue = page.index('class="nav-group tissue"')
    blood = page.index('class="nav-group blood"')
    microbiology = page.index('class="nav-group microbiology"')
    assert page.index('href="/critical"') < tissue < page.index('href="/ledger/excel"') < blood
    assert blood < page.index('href="/lab"') < page.index('href="/lab/paper"') < microbiology
    assert microbiology < page.index('href="/fobt"')
    groups = re.findall(r'<nav class="nav-group ([^"]+)" aria-label="([^"]+)">(.*?)</nav>', page, re.S)
    assert [(kind, label) for kind, label, _ in groups] == [
        ("tissue", "병리"), ("blood", "혈액"), ("microbiology", "미생물")]
    assert [len(re.findall(r'<a ', body)) for _, _, body in groups] == [5, 2, 1]


@pytest.mark.parametrize("path,href", [
    ("/dashboard", "/dashboard"), ("/dashboard?stage=FOLLOWUP", "/dashboard?stage=FOLLOWUP&amp;due=due"),
    ("/clo", "/clo"), ("/ledger/paper", "/ledger/paper"), ("/ledger/excel", "/ledger/excel"),
    ("/lab", "/lab"), ("/lab/paper", "/lab/paper"), ("/fobt", "/fobt"), ("/critical", "/critical"),
])
def test_only_current_sidebar_item_is_active(client, path, href):
    page = client.get(path).text.split("</aside>", 1)[0]
    active = re.findall(r'<a class="nav-item [^"]*\bactive\b[^"]*" href="([^"]+)"', page)
    assert active == [href]


def test_critical_report_screen_advances_and_keeps_empty_navigation(client, app):
    old = client.get("/lab?stage=CRITICAL_PENDING", follow_redirects=False)
    assert old.status_code == 303 and old.headers["location"] == "/critical"
    for remaining in (2, 1):
        page = client.get("/critical").text
        assert '<h1>위급치 보고</h1>' in page
        assert '<script ' not in page
        assert f"원장 보고 대기 {remaining}건" in page
        assert 'name="back" value="critical"' in page
        case = first_in(app, "CRITICAL_PENDING")
        response = post(client, app, f"/lab/cases/{case.id}/report-critical",
                        reported_by="테스트직원", back="critical")
        assert response.headers["location"] == "/critical?notice=reported"
        assert "원장 보고 완료를 기록했습니다." in client.get(response.headers["location"]).text
        assert client.get(f"/critical?selected_id={case.id}").status_code == 422
    page = client.get("/critical").text
    assert "원장 보고 대기 중인 위급치가 없습니다." in page
    assert 'aria-label="보고 대기 0건"' in page
    assert 'href="/critical"' in page and "critical-alert" not in page


def test_blood_paper_matches_config_masks_names_and_leaves_signatures_blank(client, app):
    response = client.get("/lab/paper?start=2026-10-01&end=2026-11-05")
    assert response.status_code == 200
    page = response.text
    assert "혈액 종이대장 대조" in page and "원내 서식 13열" in page
    assert page.count('<th scope="col">') == 13
    rows = lab(app).paper_snapshot(start=datetime(2026, 10, 1).date(), end=THURSDAY_10.date())["rows"]
    assert len(rows) == 10
    for row in rows:
        assert row["values"][6] is None and row["values"][8:10] == (None, None)
        assert f'/lab?selected_id={row["id"]}' in page
    for case in lab(app).snapshot()["cases"]:
        assert case.record.patient_name not in page
        assert case.display_name in page


@pytest.mark.parametrize("query", ["start=bad", "end=2026-02-30", "start=2026-11-06&end=2026-11-05"])
def test_blood_paper_rejects_invalid_date_filters(client, query):
    assert client.get(f"/lab/paper?{query}").status_code == 422


def test_blood_paper_does_not_invent_result_and_reflects_new_input(client, app):
    case = first_in(app, "RESULT_PENDING")
    start = datetime(2026, 10, 1).date()
    def values():
        return next(row["values"] for row in lab(app).paper_snapshot(start=start)["rows"] if row["id"] == case.id)
    assert values()[11] is None
    assert post(client, app, f"/lab/cases/{case.id}/result", **result_form()).status_code == 303
    assert "AST 52 H" in values()[11]
    assert "AST 52 H" in client.get("/lab/paper?start=2026-10-01&end=2026-11-05").text
    empty = client.get("/lab/paper?start=2026-01-01&end=2026-01-31").text
    assert "이 기간에 접수된 혈액검체가 없습니다." in empty


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
    assert 'value="HBsAg"' in page and 'value="Anti-HBs"' in page and 'value="Anti-HCV"' in page
    assert page.count('name="item_name"') == 1
    assert 'data-add-row' in page and 'data-remove-row' in page
    assert 'script-src \'self\'' in client.get(f"/lab?selected_id={case.id}").headers["content-security-policy"]
    assert "script-src" not in client.get("/dashboard").headers["content-security-policy"]
    assert client.get("/static/lab-result-form.js").status_code == 200


@pytest.mark.parametrize("hcv", ["Neg", "Pos", ""])
def test_additional_anti_hcv_is_saved_only_when_selected(client, app, hcv):
    case = first_in(app, "RESULT_PENDING")
    data = result_form(qual_name=["HBsAg", "Anti-HBs", "Anti-HCV"], qual_value=["Neg", "Pos", hcv])
    assert post(client, app, f"/lab/cases/{case.id}/result", **data).status_code == 303
    entered = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    hcv_items = [item.value for item in entered.record.items if item.name == "Anti-HCV"]
    assert hcv_items == ([hcv] if hcv else [])


def test_more_than_five_flagged_items_can_be_saved(client, app):
    case = first_in(app, "RESULT_PENDING")
    names = ["Hb", "Glu", "CHOL", "TG", "AST", "GGT"]
    data = result_form(item_name=names, item_value=["1"] * 6, item_flag=["H"] * 6)
    assert post(client, app, f"/lab/cases/{case.id}/result", **data).status_code == 303
    entered = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert [item.name for item in entered.record.items if item.flag] == names


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
    {"qual_name": ["HBsAg", "Anti-HBs", "Anti-HCV"], "qual_value": ["Neg", "Pos", "Unknown"]},
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


def test_check_can_record_followup_note(client, app):
    case = first_in(app, "CHECK_PENDING")
    assert post(client, app, f"/lab/cases/{case.id}/check", checked_by="테스트직원",
                followup_note="11/20 재검 안내함").status_code == 303
    done = next(c for c in lab(app).snapshot()["cases"] if c.id == case.id)
    assert done.record.followup_note == "11/20 재검 안내함"
    assert "비고란: 11/20 재검 안내함" in client.get(f"/lab?selected_id={case.id}").text
    other = first_in(app, "CHECK_PENDING")
    assert post(client, app, f"/lab/cases/{other.id}/check", checked_by="테스트직원",
                followup_note="가" * 41).status_code == 422
