"""합성 데이터 전용 혈액검체 장부 계약: 실데이터·외부 조회를 사용하지 않는다."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.modules.screening_lab.ledger import (
    LabItem,
    LabRecord,
    format_result,
    load_policy,
    merge_records,
    new_workbook,
    save_new_workbook,
)
from app.modules.screening_lab.ledger_demo import synthetic_records


SHEET_NAME = "혈액검체장부"
HEADERS = (
    "접수일",
    "접수번호",
    "차트번호",
    "수진자명",
    "성별",
    "나이",
    "검사종류",
    "접수인",
    "인계인",
    "위탁일",
    "수령인",
    "결과보고일",
    "결과란",
)
MANUAL_HEADERS = ("접수인", "인계인", "수령인")


def synthetic_record(**changes: object) -> LabRecord:
    """아래 번호·이름·수치는 테스트를 위한 가짜 값이다."""
    fields = {
        "report_ref": "00004321",
        "chart_no": "00008765",
        "patient_name": "테스트수진자A",
        "received_date": date(2026, 10, 19),
        "sex": "F",
        "age": "52",
        "exam_kinds": ("일반검진9종", "간검진(AFP)"),
        "entrusted_date": date(2026, 10, 19),
        "report_date": date(2026, 10, 21),
        "items": (
            LabItem("합성항목A", "52", "H"),
            LabItem("합성항목B", "38", None),
            LabItem("합성항목C", "<0.5", "L"),
        ),
    }
    fields.update(changes)
    return LabRecord(**fields)


@pytest.fixture
def policy():
    return load_policy()


@pytest.fixture
def workbook(policy):
    return new_workbook(policy)


def row_values(workbook, row: int = 2) -> dict[str, object]:
    sheet = workbook[SHEET_NAME]
    return {header: sheet.cell(row=row, column=column).value for column, header in enumerate(HEADERS, start=1)}


def test_headers_follow_user_order(workbook, policy):
    assert policy.headers == HEADERS
    assert tuple(cell.value for cell in workbook[SHEET_NAME][1]) == HEADERS


def test_one_row_holds_whole_patient_result(workbook, policy):
    result = merge_records(workbook, [synthetic_record()], policy)
    values = row_values(workbook)
    assert result.appended == 1
    assert workbook[SHEET_NAME].max_row == 2
    assert values["검사종류"] == "일반검진9종, 간검진(AFP)"
    assert values["접수번호"] == "00004321"
    assert values["접수일"] == date(2026, 10, 19)


def test_result_lists_only_flagged_items(workbook, policy):
    merge_records(workbook, [synthetic_record()], policy)
    assert row_values(workbook)["결과란"] == "합성항목A 52 H, 합성항목C <0.5 L"


def test_all_normal_leaves_result_blank():
    assert format_result([LabItem("합성항목B", "38", None)]) is None


def test_manual_columns_stay_blank(workbook, policy):
    merge_records(workbook, [synthetic_record()], policy)
    values = row_values(workbook)
    assert all(values[header] is None for header in MANUAL_HEADERS)


def test_staff_edits_are_preserved_on_rerun(workbook, policy):
    first = merge_records(workbook, [synthetic_record()], policy)
    workbook[SHEET_NAME].cell(2, HEADERS.index("수령인") + 1, "직원A")
    again = merge_records(workbook, [synthetic_record()], policy, fingerprints=first.fingerprints)
    assert again.appended == 0 and again.unchanged == 1
    assert row_values(workbook)["수령인"] == "직원A"


def test_critical_value_creates_report_issue_and_highlight(workbook, policy):
    record = synthetic_record(items=(LabItem("합성항목E", "999", "H", critical=True),))
    result = merge_records(workbook, [record], policy)
    column = HEADERS.index("결과란") + 1
    assert [issue.code for issue in result.issues] == ["CRITICAL_REPORT"]
    assert result.issues[0].row == 2
    assert workbook[SHEET_NAME].cell(2, column).fill.fgColor.rgb.endswith("F8D7DA")


def test_non_critical_row_has_no_issue(workbook, policy):
    result = merge_records(workbook, [synthetic_record()], policy)
    assert result.issues == ()


def test_changed_source_is_reviewed_not_overwritten(workbook, policy):
    first = merge_records(workbook, [synthetic_record()], policy)
    changed = synthetic_record(items=(LabItem("합성항목A", "70", "H"),))
    again = merge_records(workbook, [changed], policy, fingerprints=first.fingerprints)
    assert [issue.code for issue in again.issues] == ["SOURCE_CHANGED"]
    assert row_values(workbook)["결과란"] == "합성항목A 52 H, 합성항목C <0.5 L"


def test_existing_row_without_fingerprint_is_reviewed(workbook, policy):
    merge_records(workbook, [synthetic_record()], policy)
    again = merge_records(workbook, [synthetic_record()], policy)
    assert [issue.code for issue in again.issues] == ["EXISTING_ROW_REVIEW"]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"exam_kinds": ("종합검진",)}, "UNKNOWN_EXAM_KIND"),
        ({"exam_kinds": ("일반검진6종", "일반검진6종")}, "DUPLICATE_EXAM_KIND"),
        ({"items": (LabItem("합성항목A", "52", "HH"),)}, "UNKNOWN_RESULT_FLAG"),
        ({"items": (LabItem("", "52", "H"),)}, "INVALID_ITEM_TEXT"),
        ({"chart_no": " "}, "MISSING_RECORD_KEY_OR_NAME"),
        ({"report_date": "2026-10-21"}, "INVALID_DATE_TYPE"),
        ({"exam_kinds": ["일반검진6종"]}, "INVALID_COLLECTION_TYPE"),
    ],
)
def test_invalid_input_rejects_whole_batch(workbook, policy, changes, code):
    with pytest.raises(ValueError, match=code):
        merge_records(workbook, [synthetic_record(report_ref="OK-1"), synthetic_record(**changes)], policy)
    assert workbook[SHEET_NAME].max_row == 1


def test_duplicate_key_in_batch_rejected(workbook, policy):
    with pytest.raises(ValueError, match="DUPLICATE_BATCH_KEY"):
        merge_records(workbook, [synthetic_record(), synthetic_record()], policy)


def test_formula_like_text_is_stored_as_text(workbook, policy):
    merge_records(workbook, [synthetic_record(patient_name="=테스트()")], policy)
    content = BytesIO()
    workbook.save(content)
    reopened = load_workbook(BytesIO(content.getvalue()))
    cell = reopened[SHEET_NAME].cell(2, HEADERS.index("수진자명") + 1)
    assert cell.data_type == "s" and cell.value == "=테스트()"


def test_header_mismatch_rejected(workbook, policy):
    workbook[SHEET_NAME].cell(1, 1, "검사일")
    with pytest.raises(ValueError, match="HEADER_MISMATCH"):
        merge_records(workbook, [synthetic_record()], policy)


def test_save_never_overwrites(tmp_path, workbook):
    target = tmp_path / "lab.xlsx"
    save_new_workbook(workbook, target)
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        save_new_workbook(workbook, target)
    assert target.read_bytes() == before


def test_record_repr_hides_patient_values():
    assert "테스트수진자A" not in repr(synthetic_record())
    assert "52" not in repr(LabItem("합성항목A", "52", "H"))


def test_demo_records_are_synthetic_and_idempotent(workbook, policy):
    records = synthetic_records()
    assert all(record.patient_name.startswith("테스트") for record in records)
    first = merge_records(workbook, records, policy)
    again = merge_records(workbook, records, policy, fingerprints=first.fingerprints)
    assert first.appended == 10 and again.appended == 0
    assert sum(issue.code == "CRITICAL_REPORT" for issue in first.issues) == 2


def test_lab_module_does_not_import_pathology_module():
    source = Path(__file__).resolve().parents[2] / "app/modules/screening_lab"
    for path in source.glob("*.py"):
        assert "endoscopy_pathology" not in path.read_text(encoding="utf-8")


def test_policy_rejects_wrong_column_count(tmp_path, policy):
    broken = tmp_path / "broken.yaml"
    broken.write_text(
        "sheet_name: x\nfreeze_panes: A2\nexam_kinds: []\nresult_flags: [H]\n"
        "columns:\n  - {header: 접수일, field: received_date, kind: date, width: 10}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="INVALID_LEDGER_POLICY"):
        load_policy(broken)
