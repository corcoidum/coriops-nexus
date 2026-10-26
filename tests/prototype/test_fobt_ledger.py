"""분변잠혈 대장(A22): 조직검체 장부에서 Stool을 빼고 따로 보여준다. 합성 자료만 쓴다."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from app.main import create_app
from app.modules.endoscopy_pathology.ledger_db import MemoryStore
from app.modules.endoscopy_pathology.manual_dashboard import DashboardError, ManualDashboardService
from ledger_helpers import FixedClock

DAY = date(2026, 11, 4)
CLOCK = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)  # 2026-11-05(목) 10:00 KST


@pytest.fixture
def service(tmp_path):
    return ManualDashboardService(clock=FixedClock(CLOCK), store=MemoryStore(), export_dir=tmp_path)


@pytest.fixture
def client(tmp_path):
    app = create_app(ManualDashboardService(clock=FixedClock(CLOCK), store=MemoryStore(), export_dir=tmp_path))
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        yield test_client


def post(client, path, **data):
    return client.post(path, data={"csrf_token": client.app_state.csrf_token, **data}, follow_redirects=False)


def stool(service, number: int, day: date = DAY):
    return service.register("STOOL", f"T-{number:04}", f"테스트변{number}", day, "M", "70")


def test_ledgers_split_tissue_and_fobt(service):
    biopsy = service.register("BIOPSY", "T-0001", "테스트조직", DAY, procedure_type="stomach", specimen_count="1")
    fobt = stool(service, 2)
    tissue = service.snapshot()
    fobt_view = service.snapshot(ledger="fobt")
    assert [c.id for c in tissue["cases"]] == [biopsy] and list(tissue["kind_labels"]) == ["BIOPSY", "CLO"]
    assert [c.id for c in fobt_view["cases"]] == [fobt] and fobt_view["kind_labels"] == {"STOOL": "분변잠혈"}
    # 같은 씨젠 수령 때 함께 나가므로 인계 대기는 두 장부가 같은 수를 본다.
    assert tissue["pickup"]["pending_cases"] == fobt_view["pickup"]["pending_cases"] == 2
    with pytest.raises(DashboardError):
        service.snapshot(kind="STOOL")
    with pytest.raises(DashboardError):
        service.snapshot(selected_id=fobt)
    with pytest.raises(DashboardError):
        service.snapshot(ledger="unknown")


def test_fobt_page_and_actions_return_to_fobt(client):
    page = client.get("/dashboard").text
    assert 'href="/fobt"' in page and "분변잠혈 대장" in page
    response = post(client, "/ledger/register", kind="STOOL", exam_date="2026-11-04", chart_no="T-0301",
                    patient_name="테스트변", sex_age="M/70")
    location = response.headers["location"]
    assert response.status_code == 303 and location.startswith("/fobt?")
    fobt_page = client.get(location).text
    assert "분변잠혈 대장" in fobt_page and 'action="/fobt"' in fobt_page
    assert 'class="kind-tabs"' not in fobt_page  # 종류가 하나라 종류 탭이 없다
    assert "T-0301" not in client.get("/dashboard").text
    entry_id = location.split("selected_id=")[1].split("&")[0]
    assert client.get(f"/dashboard?selected_id={entry_id}").status_code == 404

    handoff = post(client, "/ledger/handoff", registered_by="테스트접수", handed_by="테스트인계",
                   receiver_name="테스트수령", confirmed_count="1", ledger="fobt")
    assert handoff.headers["location"].startswith("/fobt?")
    receive = post(client, f"/ledger/cases/{entry_id}/receive", result_notation="Negative 6.0")
    assert receive.headers["location"] == f"/fobt?selected_id={entry_id}"
    for href in re.findall(r'href="(/fobt\?[^"]+)"', client.get(receive.headers["location"]).text):
        assert client.get(href.replace("&amp;", "&")).status_code == 200, href


def test_unknown_ledger_in_forms_falls_back_to_tissue(client):
    post(client, "/ledger/register", kind="STOOL", exam_date="2026-11-04", chart_no="T-0302",
         patient_name="테스트변", sex_age="M/70")
    handoff = post(client, "/ledger/handoff", registered_by="테스트접수", handed_by="테스트인계",
                   receiver_name="테스트수령", confirmed_count="1", ledger="//evil.example")
    assert handoff.headers["location"].startswith("/dashboard?")


def test_tissue_copy_export_has_no_stool_sheet(service, tmp_path):
    service.register("BIOPSY", "T-0001", "테스트조직", DAY, procedure_type="stomach", specimen_count="1")
    stool(service, 2)
    record = service.export()
    assert load_workbook(tmp_path / record.file_name).sheetnames == ["Biopsy", "CLO"]


def test_paper_form_three_lists_only_stool(service):
    service.register("BIOPSY", "T-0001", "테스트조직", DAY, procedure_type="stomach", specimen_count="1")
    entry = stool(service, 2)
    bottles = service.snapshot()["pickup"]["pending_specimens"]
    service.handoff("테스트접수", "테스트인계", "테스트수령", bottles)  # 조직검체와 함께 인계
    service.receive(entry, "", "Negative 6.0", "")
    data = service.paper_rows("fobt", DAY, DAY)
    assert [row["chart_no"] for row in data["rows"]] == ["T-0002"]
    assert data["rows"][0]["result"] == "Negative 6.0" and data["title"] == "분변잠혈검사 결과기록대장"


def test_paper_form_three_exports_two_blocks_per_page(service, tmp_path):
    for number in range(1, 46):  # 쪽당 40줄(왼쪽 20 + 오른쪽 20) → 2쪽
        stool(service, number)
    record, subjects = service.export_paper("fobt", DAY, DAY)
    sheet = load_workbook(tmp_path / record.file_name).active
    headers = [sheet.cell(3, column).value for column in range(1, 15)]
    assert headers[:7] == headers[7:] and headers[0] == "접수\n일자" and headers[6].startswith("결과\n(참고치")
    assert "[검진] Stool occult blood 정량" in sheet["A2"].value
    assert sheet.cell(4, 2).value == "T-0001" and sheet.cell(23, 2).value == "T-0020"   # 왼쪽 1~20
    assert sheet.cell(4, 9).value == "T-0021" and sheet.cell(23, 9).value == "T-0040"   # 오른쪽 21~40
    assert sheet.cell(24, 2).value == "T-0041" and sheet.cell(28, 2).value == "T-0045"  # 2쪽 왼쪽
    assert sheet.cell(24, 9).value in (None, "")                                      # 남은 칸은 빈 줄
    assert [brk.id for brk in sheet.row_breaks.brk] == [23]
    assert sheet.print_title_rows == "$3:$3" and sheet.page_setup.orientation == "landscape"
    assert len(subjects) == 45


def test_paper_page_offers_form_three(client):
    page = client.get("/ledger/paper?form=fobt&date_from=2026-11-04&date_to=2026-11-04")
    assert page.status_code == 200 and "③ 분변잠혈 대장" in page.text and "접수일자" in page.text


def test_followup_export_is_scoped_by_ledger(service):
    stool(service, 3)
    with pytest.raises(DashboardError) as tissue_only:
        service.export_followups(kind="STOOL", due="due")
    assert tissue_only.value.status_code == 422
