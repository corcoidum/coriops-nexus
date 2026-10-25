"""기존 엑셀(Biopsy·CLO·Stool) 가져오기·대조. 미리보기는 저장하지 않고, 신규만 저장한다."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.formparsers import MultiPartParser

from app.main import create_app
from app.modules.endoscopy_pathology.ledger_db import MemoryStore
from app.modules.endoscopy_pathology.manual_dashboard import DashboardError, ManualDashboardService
from ledger_helpers import SENTINEL, FixedClock, biopsy_row, short_row, standard_workbook, workbook_bytes


@pytest.fixture
def clock():
    return FixedClock()


@pytest.fixture
def service(clock):
    # 빈 저장소에서 시작한다(DB 모드와 같은 조건).
    return ManualDashboardService(clock=clock, store=MemoryStore())


def by_chart(service, chart):
    return next(e for e in service._store.entries() if e.chart_no == chart)


def stage(service, chart):
    entry = by_chart(service, chart)
    return service.snapshot()["stages"][entry.id]


def test_preview_reads_three_sheets_and_saves_nothing(service):
    token = service.preview_import(standard_workbook())
    summary = service.preview(token)

    assert [s["sheet"] for s in summary["sheets"]] == ["Biopsy", "CLO", "Stool"]
    assert {s["sheet"]: s["counts"]["new"] for s in summary["sheets"]} == {"Biopsy": 5, "CLO": 1, "Stool": 1}
    assert summary["other_sheets"] == ["분석 대시보드"]
    assert summary["sheets"][0]["ignored_headers"] == ["비고란"]
    assert service._store.entries() == []


def test_commit_stores_new_rows_with_structured_results(service):
    assert service.commit_import(service.preview_import(standard_workbook())) == 7

    colon = by_chart(service, "H-0001")
    assert colon.source == "IMPORT" and colon.import_batch_id is not None
    assert colon.result_notation == "TA#2(L), H#1"
    assert colon.procedure_type == "colon" and colon.specimen_count == 2
    gastric = by_chart(service, "H-0002")
    assert dict(gastric.sydney)["neutrophil"] == "POS2"
    clo = next(e for e in service._store.entries() if e.kind == "CLO")
    assert clo.result_code == "+" and clo.procedure_type == "stomach"


def test_free_text_result_is_not_stored_and_flagged(service):
    service.commit_import(service.preview_import(standard_workbook()))

    entry = by_chart(service, "H-0003")
    assert entry.findings == () and entry.result_code == ""
    assert "RESULT_UNPARSED" in entry.review_codes
    assert stage(service, "H-0003") == "DOCTOR_PENDING"
    assert all("tubular" not in repr(e) for e in service._store.entries())


def test_ignored_note_column_never_reaches_storage_or_screen(service):
    app = create_app(service)
    token = service.preview_import(standard_workbook())
    with TestClient(app) as client:
        preview_page = client.get(f"/ledger/excel?token={token}").text
        service.commit_import(token)
        dashboard = client.get("/dashboard").text

    assert SENTINEL not in preview_page and SENTINEL not in dashboard
    assert all(SENTINEL not in repr(e) for e in service._store.entries())


def test_past_rows_skip_handoff_but_today_waits_for_handoff(service):
    service.commit_import(service.preview_import(standard_workbook()))

    assert stage(service, "H-0004") == "RESULT_PENDING"   # 10/12, 결과 없음 → 위탁된 것으로 간주
    assert stage(service, "H-0005") == "HANDOFF_PENDING"  # 오늘, 위탁일 없음
    assert service.snapshot()["flags"]["imported_pending"] == 5  # 조직 3 + CLO 1 + Stool 1


def test_same_file_again_is_all_same_and_cannot_commit(service):
    service.commit_import(service.preview_import(standard_workbook()))

    token = service.preview_import(standard_workbook())
    summary = service.preview(token)

    assert summary["new_total"] == 0
    assert sum(s["counts"]["same"] for s in summary["sheets"]) == 7
    with pytest.raises(DashboardError) as error:
        service.commit_import(token)
    assert error.value.status_code == 422
    with pytest.raises(DashboardError) as reused:
        service.commit_import(token)
    assert reused.value.status_code == 410  # 미리보기는 1회용


def test_reconcile_reports_differences_and_db_only_rows(service):
    service.commit_import(service.preview_import(standard_workbook()))
    changed = workbook_bytes(biopsy=[
        biopsy_row(date(2026, 10, 2), "T9800001", "H-0001", "가져온환자일", result="TA#3(L), H#1",
                   reported=date(2026, 10, 5), kind="colon", count=2),
        biopsy_row(date(2026, 10, 12), "", "H-0004", "가져온환자사", result="", entrusted=False),
    ])

    summary = service.preview(service.preview_import(changed))

    biopsy = summary["sheets"][0]["counts"]
    assert (biopsy["different"], biopsy["same"], biopsy["missing"]) == (1, 1, 2)
    assert summary["differences"][0]["fields"] == ["결과"]
    assert {item["entry"].chart_no for item in summary["missing"]} == {"H-0002", "H-0003"}
    assert by_chart(service, "H-0001").result_notation == "TA#2(L), H#1"  # 덮어쓰지 않음


def test_manual_entry_without_report_ref_matches_excel_row_by_chart_and_date(service):
    entry_id = service.register("BIOPSY", "H-0101", "수기환자", date(2026, 10, 30), procedure_type="colon",
                                specimen_count="1")
    assert entry_id
    workbook = workbook_bytes(biopsy=[biopsy_row(date(2026, 10, 30), "T9800101", "H-0101", "수기환자",
                                                 kind="colon", result="", entrusted=False)])

    summary = service.preview(service.preview_import(workbook))

    assert summary["new_total"] == 0
    assert summary["differences"][0]["fields"] == ["접수번호", "검사위치", "위탁일"]


def test_invalid_rows_are_excluded_with_row_numbers_only(service):
    workbook = workbook_bytes(biopsy=[
        biopsy_row(date(2026, 10, 2), "T9800001", "", "이름만", result="H#1"),
        biopsy_row("날짜아님", "T9800002", "H-0002", "가져온환자이"),
        biopsy_row(date(2026, 10, 3), "T9800003", "H-0003", "가져온환자삼"),
        biopsy_row(date(2026, 10, 3), "T9800003", "H-0003", "가져온환자삼"),
    ])

    summary = service.preview(service.preview_import(workbook))

    codes = [(i.row, i.code, i.column) for i in summary["issues"]]
    assert (2, "REQUIRED_MISSING", "차트번호") in codes
    assert (3, "INVALID_REQUIRED", "검사일") in codes
    assert (5, "DUPLICATE_IN_FILE", "") in codes
    assert summary["new_total"] == 1
    assert "이름만" not in repr(summary["issues"])


def test_name_mismatch_with_existing_chart_is_not_imported(service):
    service.commit_import(service.preview_import(standard_workbook()))
    workbook = workbook_bytes(biopsy=[biopsy_row(date(2026, 10, 25), "T9800009", "H-0001", "다른이름")])

    summary = service.preview(service.preview_import(workbook))

    assert summary["new_total"] == 0
    assert summary["issues"][0].code == "NAME_MISMATCH"


def test_missing_required_header_skips_the_sheet(service):
    headers = ["검사일", "접수번호", "수진자명"]
    summary = service.preview(service.preview_import(workbook_bytes(biopsy_headers=headers)))

    assert summary["sheets"][0]["skipped"] is True
    assert summary["issues"][0].code == "MISSING_HEADER"


@pytest.mark.parametrize("data", [b"", b"not an excel file", b"PK\x03\x04broken"])
def test_unreadable_files_are_rejected(service, data):
    with pytest.raises(DashboardError) as error:
        service.preview_import(data)
    assert error.value.status_code == 422


def test_preview_expires_and_is_single_use(service, clock):
    token = service.preview_import(standard_workbook())
    clock.moment += timedelta(minutes=16)

    with pytest.raises(DashboardError) as error:
        service.commit_import(token)
    assert error.value.status_code == 410
    assert service._store.entries() == []


def test_bulk_not_required_closes_selected_imported_rows_together(service):
    service.commit_import(service.preview_import(standard_workbook()))
    ids = [by_chart(service, c).id for c in ("H-0001", "H-0003")]

    assert service.bulk_not_required(ids, "합성 원장 일괄 지시") == 2
    assert {stage(service, "H-0001"), stage(service, "H-0003")} == {"CLOSED"}

    pending = by_chart(service, "H-0004").id  # 결과 대기 → 원장 지시 대상 아님
    before = [e.version for e in service._store.entries()]
    with pytest.raises(DashboardError):
        service.bulk_not_required([by_chart(service, "H-0002").id, pending], "합성")
    assert [e.version for e in service._store.entries()] == before  # 하나라도 실패하면 전부 취소
    with pytest.raises(DashboardError):
        service.bulk_not_required([by_chart(service, "H-0002").id], " ")


# ---------- HTTP 경계

def test_upload_route_previews_and_commit_route_saves(service):
    app = create_app(service)
    with TestClient(app) as client:
        response = client.post("/ledger/import/preview", data={"csrf_token": app.state.csrf_token},
                               files={"ledger_file": ("합성.xlsx", standard_workbook())}, follow_redirects=False)
        assert response.status_code == 303
        token = response.headers["location"].split("token=")[1]
        page = client.get(f"/ledger/excel?token={token}")
        assert "신규 7건 DB에 저장" in page.text
        committed = client.post("/ledger/import/commit", data={"csrf_token": app.state.csrf_token, "token": token},
                                follow_redirects=False)
        assert committed.status_code == 303
    assert len(service._store.entries()) == 7


def test_upload_requires_csrf_and_size_limit(service):
    app = create_app(service)
    with TestClient(app) as client:
        denied = client.post("/ledger/import/preview", data={"csrf_token": "INVALID"},
                             files={"ledger_file": ("합성.xlsx", standard_workbook())})
        too_big = client.post("/ledger/import/preview", data={"csrf_token": app.state.csrf_token},
                              files={"ledger_file": ("합성.xlsx", b"0" * (service.max_upload_bytes + 70 * 1024))})
    assert denied.status_code == 403
    assert too_big.status_code == 413
    assert service._store.entries() == []


def test_uploads_within_limit_stay_in_memory(service):
    create_app(service)
    assert MultiPartParser.spool_max_size >= service.max_upload_bytes


def test_bulk_route_needs_a_reason(service):
    service.commit_import(service.preview_import(standard_workbook()))
    app = create_app(service)
    entry_id = str(by_chart(service, "H-0001").id)
    with TestClient(app) as client:
        missing = client.post("/ledger/bulk-decide", data={"csrf_token": app.state.csrf_token,
                                                           "entry_ids": [entry_id], "reason": ""})
        done = client.post("/ledger/bulk-decide", data={"csrf_token": app.state.csrf_token,
                                                        "entry_ids": [entry_id], "reason": "합성 지시"},
                           follow_redirects=False)
    assert missing.status_code == 422
    assert done.status_code == 303
    assert stage(service, "H-0001") == "CLOSED"


def test_short_result_rows_for_clo_and_stool(service):
    workbook = workbook_bytes(
        clo=[short_row(date(2026, 10, 20), "", "H-0201", "합성씨엘오", result="양성", reported=date(2026, 10, 21))],
        stool=[short_row(date(2026, 10, 21), "", "H-0202", "합성대변", result="긴 문장으로 쓴 결과 설명은 저장하지 않음",
                         reported=date(2026, 10, 23))],
    )
    service.commit_import(service.preview_import(workbook))

    assert by_chart(service, "H-0201").result_code == "양성"
    stool = by_chart(service, "H-0202")
    assert stool.result_code == "" and "RESULT_UNPARSED" in stool.review_codes
