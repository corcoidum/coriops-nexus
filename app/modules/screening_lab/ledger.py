"""합성 혈액검체 결과를 13열 장부로 옮기는 기능. 실제 수집·임상 판정은 포함하지 않는다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Iterable, Mapping

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import yaml


type RecordKey = tuple[str, str]
EXCEL_CELL_TEXT_LIMIT = 32767
COLUMN_KINDS = {"date", "text", "manual", "exam_kinds", "lab_result"}
CRITICAL_FILL = PatternFill("solid", fgColor="F8D7DA")


@dataclass(frozen=True, repr=False)
class LabItem:
    """씨젠 결과 1항목. 값은 '<0.5' 같은 표기를 보존하려고 문자열로 받는다."""

    name: str
    value: str
    flag: str | None = None  # 씨젠의 H/L 표시. None이면 정상범위
    critical: bool = False  # 씨젠이 위급치로 표시한 항목만 True. 시스템이 계산하지 않는다


@dataclass(frozen=True, repr=False)
class LabRecord:
    """수진자 1명(접수 1건)의 결과. 한 행으로 기록한다."""

    report_ref: str
    chart_no: str
    patient_name: str
    received_date: date | None = None
    sex: str | None = None
    age: str | None = None
    exam_kinds: tuple[str, ...] = ()
    entrusted_date: date | None = None
    report_date: date | None = None
    items: tuple[LabItem, ...] = ()


@dataclass(frozen=True)
class Column:
    header: str
    kind: str
    width: int
    field: str | None = None


@dataclass(frozen=True)
class LabLedgerPolicy:
    sheet_name: str
    freeze_panes: str
    exam_kinds: tuple[str, ...]
    result_flags: tuple[str, ...]
    columns: tuple[Column, ...]

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(column.header for column in self.columns)


@dataclass(frozen=True)
class ReviewIssue:
    """개인값·결과값을 담지 않는 검토 위치·사유."""

    row: int
    column: str
    code: str


@dataclass(frozen=True, repr=False)
class MergeResult:
    appended: int
    unchanged: int
    issues: tuple[ReviewIssue, ...]
    fingerprints: dict[RecordKey, str]


def load_policy(path: Path | None = None) -> LabLedgerPolicy:
    """혈액 장부 13열 정책을 읽는다. 조직검체 설정은 읽지 않는다."""
    source = path or Path(__file__).resolve().parents[3] / "config/lab_ledger_mapping.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    columns = tuple(Column(**column) for column in data["columns"])
    allowed_fields = set(LabRecord.__dataclass_fields__)
    if (
        len(columns) != 13
        or len({column.header for column in columns}) != 13
        or any(column.kind not in COLUMN_KINDS for column in columns)
        or any(column.field not in allowed_fields for column in columns if column.field)
        or any(column.field for column in columns if column.kind == "manual")
        or any(not column.field for column in columns if column.kind != "manual")
    ):
        raise ValueError("INVALID_LEDGER_POLICY")
    return LabLedgerPolicy(
        data["sheet_name"],
        data["freeze_panes"],
        tuple(data["exam_kinds"]),
        tuple(data["result_flags"]),
        columns,
    )


def new_workbook(policy: LabLedgerPolicy) -> Workbook:
    """요청된 13열만 있는 시연용 workbook을 만든다."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = policy.sheet_name
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = policy.freeze_panes
    sheet.append(policy.headers)
    sheet.row_dimensions[1].height = 32
    for index, column in enumerate(policy.columns, 1):
        sheet.column_dimensions[get_column_letter(index)].width = column.width
        cell = sheet.cell(1, index)
        cell.fill = PatternFill("solid", fgColor="243746")
        cell.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return workbook


def format_result(items: Iterable[LabItem]) -> str | None:
    """정상범위 항목은 빼고 '항목 값 H/L'을 쉼표로 잇는다. 모두 정상이면 빈칸."""
    parts = [
        " ".join(part for part in (item.name, item.value, item.flag) if part)
        for item in items
        if item.flag or item.critical
    ]
    return ", ".join(parts) or None


def _check_text(value: str) -> None:
    # Excel의 자동 잘림·XML 직렬화 오류가 발생하기 전에 배치 전체를 거부한다.
    if len(value) > EXCEL_CELL_TEXT_LIMIT:
        raise ValueError("EXCEL_TEXT_TOO_LONG")
    if ILLEGAL_CHARACTERS_RE.search(value) or "￾" in value or "￿" in value:
        raise ValueError("INVALID_EXCEL_TEXT")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("INVALID_EXCEL_TEXT") from None


def _validate_record(record: LabRecord, policy: LabLedgerPolicy) -> RecordKey:
    for value in (record.report_ref, record.chart_no, record.patient_name):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("MISSING_RECORD_KEY_OR_NAME")
    for value in (record.received_date, record.entrusted_date, record.report_date):
        if value is not None and type(value) is not date:
            raise ValueError("INVALID_DATE_TYPE")
    for value in (record.sex, record.age):
        if value is not None and not isinstance(value, str):
            raise ValueError("INVALID_TEXT_TYPE")
    if not isinstance(record.exam_kinds, tuple) or not isinstance(record.items, tuple):
        raise ValueError("INVALID_COLLECTION_TYPE")
    # 목록에 없는 검사종류는 오타·새 검사일 수 있어 추측하지 않고 거부한다.
    if any(kind not in policy.exam_kinds for kind in record.exam_kinds):
        raise ValueError("UNKNOWN_EXAM_KIND")
    if len(set(record.exam_kinds)) != len(record.exam_kinds):
        raise ValueError("DUPLICATE_EXAM_KIND")
    for item in record.items:
        if not isinstance(item, LabItem):
            raise ValueError("INVALID_ITEM_TYPE")
        if not isinstance(item.name, str) or not item.name.strip() or not isinstance(item.value, str):
            raise ValueError("INVALID_ITEM_TEXT")
        if item.flag is not None and item.flag not in policy.result_flags:
            raise ValueError("UNKNOWN_RESULT_FLAG")
        if type(item.critical) is not bool:
            raise ValueError("INVALID_CRITICAL_FLAG")
    texts = [record.report_ref, record.chart_no, record.patient_name, record.sex, record.age]
    texts += [", ".join(record.exam_kinds), format_result(record.items)]
    for value in texts:
        if value is not None:
            _check_text(value)
    return record.report_ref, record.chart_no


def _cell_value(record: LabRecord, column: Column) -> object:
    if column.kind == "manual":
        return None
    if column.kind == "exam_kinds":
        return ", ".join(record.exam_kinds) or None
    if column.kind == "lab_result":
        return format_result(record.items)
    return getattr(record, column.field)


def merge_records(
    workbook: Workbook,
    records: Iterable[LabRecord],
    policy: LabLedgerPolicy,
    fingerprints: Mapping[RecordKey, str] | None = None,
) -> MergeResult:
    """기존 행은 보존하고 신규 합성 행만 추가한다. 위급치·변경은 검토에 남긴다."""
    sheet = workbook[policy.sheet_name]
    if tuple(cell.value for cell in sheet[1]) != policy.headers:
        raise ValueError("HEADER_MISMATCH")
    report_column = next(i for i, column in enumerate(policy.columns, 1) if column.field == "report_ref")
    chart_column = next(i for i, column in enumerate(policy.columns, 1) if column.field == "chart_no")
    existing: dict[RecordKey, int] = {}
    for row in range(2, sheet.max_row + 1):
        values = tuple(sheet.cell(row, column).value for column in range(1, len(policy.columns) + 1))
        if all(value is None for value in values):
            continue
        key = (sheet.cell(row, report_column).value, sheet.cell(row, chart_column).value)
        if any(not isinstance(value, str) or not value.strip() for value in key):
            raise ValueError("EXISTING_ROW_KEY_MISSING")
        if key in existing:
            raise ValueError("DUPLICATE_EXISTING_KEY")
        existing[key] = row

    # 배치 입력 전체를 검증한 뒤 수정하여 뒤쪽 오류로 일부만 추가되지 않게 한다.
    batch = tuple(records)
    keys = tuple(_validate_record(record, policy) for record in batch)
    if len(set(keys)) != len(keys):
        raise ValueError("DUPLICATE_BATCH_KEY")
    known = {key: value for key, value in (fingerprints or {}).items() if key in existing}
    issues: list[ReviewIssue] = []
    appended = unchanged = 0
    result_header = next(column.header for column in policy.columns if column.kind == "lab_result")
    for record, key in zip(batch, keys, strict=True):
        payload = json.dumps(asdict(record), ensure_ascii=True, sort_keys=True, default=str)
        digest = sha256(payload.encode("utf-8")).hexdigest()
        if key in existing:
            if key not in known:
                issues.append(ReviewIssue(existing[key], "", "EXISTING_ROW_REVIEW"))
            elif known[key] != digest:
                issues.append(ReviewIssue(existing[key], "", "SOURCE_CHANGED"))
            else:
                unchanged += 1
            continue

        row = sheet.max_row + 1
        critical = any(item.critical for item in record.items)
        for index, column in enumerate(policy.columns, 1):
            value = _cell_value(record, column)
            cell = sheet.cell(row, index, value)
            cell.font = Font(name="Arial", size=11, color="243746")
            cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=column.kind == "lab_result")
            if isinstance(value, str):
                # 외부 문자열이 = 등으로 시작해도 수식으로 실행되지 않게 한다.
                cell.data_type = "s"
                cell.number_format = "@"
            elif column.kind == "date":
                cell.number_format = "yyyy-mm-dd"
            if column.kind == "lab_result" and critical:
                cell.fill = CRITICAL_FILL
        if critical:
            # 원장 보고 대상. 보고 완료 여부는 사람이 대시보드에서 기록한다(L3).
            issues.append(ReviewIssue(row, result_header, "CRITICAL_REPORT"))
        sheet.row_dimensions[row].height = 26
        existing[key] = row
        known[key] = digest
        appended += 1
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(policy.columns))}{sheet.max_row}"
    return MergeResult(appended, unchanged, tuple(issues), known)


def save_new_workbook(workbook: Workbook, path: Path) -> Path:
    """새 파일에만 저장한다. 기존 파일·심볼릭 링크가 있으면 덮어쓰지 않는다."""
    path = Path(path)
    content = BytesIO()
    workbook.save(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(content.getvalue())
    return path
