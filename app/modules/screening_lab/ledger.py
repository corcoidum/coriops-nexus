"""합성 혈액검체 결과를 원내 서식(제목 줄 + 12열) 장부로 옮기는 기능. 실제 수집·임상 판정은 포함하지 않는다."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Iterable, Mapping

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import yaml


type RecordKey = tuple[str, str]
EXCEL_CELL_TEXT_LIMIT = 32767
COLUMN_KINDS = {"date", "text", "manual", "sex_age", "exam_kinds", "lab_result"}
COLUMN_COUNT = 13
NOTE_MAX = 40  # 비고란 메모 길이. 문장형 판독을 막으려고 짧게 둔다
HEADER_ROW = 2  # 1행은 대장 제목
THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
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
    # 직원이 결과를 입력했으나 H/L 항목이 하나도 없을 때(모두 정상) True. 항목이 있으면 자동으로 수신 상태다.
    result_received: bool = False
    followup_note: str | None = None  # 비고란(B22·B24): 추후 관리 메모만

    @property
    def received(self) -> bool:
        return bool(self.items) or self.result_received


@dataclass(frozen=True)
class Column:
    header: str
    kind: str
    width: int
    field: str | None = None


@dataclass(frozen=True)
class LabLedgerPolicy:
    sheet_name: str
    title: str
    freeze_panes: str
    exam_kinds: tuple[str, ...]
    result_flags: tuple[str, ...]
    normal_label: str
    item_names: tuple[str, ...]
    columns: tuple[Column, ...]
    qualitative_items: dict[str, tuple[str, ...]] = field(default_factory=dict)
    qualitative_values: tuple[str, ...] = ()

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(column.header for column in self.columns)

    @property
    def qualitative_names(self) -> frozenset[str]:
        return frozenset(name for names in self.qualitative_items.values() for name in names)

    def qualitative_for(self, exam_kinds: Iterable[str]) -> tuple[str, ...]:
        """분류에 따라 Neg/Pos를 반드시 골라야 하는 정성 검사 항목."""
        return tuple(name for kind in exam_kinds for name in self.qualitative_items.get(kind, ()))

    def result_text(self, record: LabRecord) -> str | None:
        return format_result(record.items, self.normal_label, self.qualitative_names, record.received)


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
    """혈액 장부 12열 정책(원내 서식)을 읽는다. 조직검체 설정은 읽지 않는다."""
    source = path or Path(__file__).resolve().parents[3] / "config/lab_ledger_mapping.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    columns = tuple(Column(**column) for column in data["columns"])
    allowed_fields = set(LabRecord.__dataclass_fields__)
    if (
        len(columns) != COLUMN_COUNT
        or len({column.header for column in columns}) != COLUMN_COUNT
        or any(column.kind not in COLUMN_KINDS for column in columns)
        or any(column.field not in allowed_fields for column in columns if column.field)
        or any(column.field for column in columns if column.kind == "manual")
        or any(not column.field for column in columns if column.kind != "manual")
    ):
        raise ValueError("INVALID_LEDGER_POLICY")
    return LabLedgerPolicy(
        data["sheet_name"],
        data["title"],
        data["freeze_panes"],
        tuple(data["exam_kinds"]),
        tuple(data["result_flags"]),
        data["normal_label"],
        tuple(data["item_names"]),
        columns,
        {kind: tuple(names) for kind, names in (data.get("qualitative_items") or {}).items()},
        tuple(data.get("qualitative_values") or ()),
    )


def new_workbook(policy: LabLedgerPolicy) -> Workbook:
    """원내 서식과 같은 제목 줄 + 12열 workbook을 만든다."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = policy.sheet_name
    sheet.freeze_panes = policy.freeze_panes
    last = get_column_letter(len(policy.columns))
    sheet["A1"] = policy.title
    sheet.merge_cells(f"A1:{last}1")
    sheet["A1"].font = Font(name="맑은 고딕", size=16, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 40
    sheet.row_dimensions[HEADER_ROW].height = 32
    # 서명 칸이 있어 종이로 출력한다. 가로 용지 한 쪽 폭에 맞추고 쪽마다 제목·열 이름을 반복한다.
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"1:{HEADER_ROW}"
    for index, column in enumerate(policy.columns, 1):
        sheet.column_dimensions[get_column_letter(index)].width = column.width
        cell = sheet.cell(HEADER_ROW, index, column.header)
        cell.fill = PatternFill("solid", fgColor="EEECE1")
        cell.font = Font(name="맑은 고딕", size=10, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    return workbook


def format_result(items: Iterable[LabItem], normal_label: str, qualitative_names: frozenset[str] = frozenset(),
                  received: bool = False) -> str | None:
    """정상범위 항목은 빼고 '항목 값 H/L'을 쉼표로 잇고, 정성 검사는 'HBsAg Neg'처럼 늘 덧붙인다.

    결과를 받지 않았으면 빈칸(미수신), H/L 항목이 없으면 normal_label을 앞에 적는다.
    """
    items = tuple(items)
    if not items and not received:
        return None
    flagged = [
        " ".join(part for part in (item.name, item.value, item.flag) if part)
        for item in items
        if (item.flag or item.critical) and item.name not in qualitative_names
    ]
    qualitative = [f"{item.name} {item.value}" for item in items if item.name in qualitative_names]
    return ", ".join((flagged or [normal_label]) + qualitative)


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
    if record.followup_note is not None and (
        not isinstance(record.followup_note, str) or len(record.followup_note) > NOTE_MAX
    ):
        raise ValueError("INVALID_FOLLOWUP_NOTE")
    for value in (record.sex, record.age):
        if value is not None and not isinstance(value, str):
            raise ValueError("INVALID_TEXT_TYPE")
    if not isinstance(record.exam_kinds, tuple) or not isinstance(record.items, tuple):
        raise ValueError("INVALID_COLLECTION_TYPE")
    if type(record.result_received) is not bool:
        raise ValueError("INVALID_RECEIVED_FLAG")
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
        # 정성 검사는 판정 칸이 없으므로 H/L을 받지 않고 Neg/Pos만 받는다(B16).
        if item.name in policy.qualitative_names and (item.flag or item.value not in policy.qualitative_values):
            raise ValueError("INVALID_QUALITATIVE_RESULT")
        if type(item.critical) is not bool:
            raise ValueError("INVALID_CRITICAL_FLAG")
    texts = [record.report_ref, record.chart_no, record.patient_name, record.sex, record.age, record.followup_note]
    texts += [", ".join(record.exam_kinds), policy.result_text(record)]
    for value in texts:
        if value is not None:
            _check_text(value)
    return record.report_ref, record.chart_no


def _cell_value(record: LabRecord, column: Column, policy: LabLedgerPolicy) -> object:
    if column.kind == "manual":
        return None
    if column.kind == "sex_age":
        if record.sex is None and record.age is None:
            return None
        return f"{record.sex or ''}/{record.age or ''}"
    if column.kind == "exam_kinds":
        return ", ".join(record.exam_kinds) or None
    if column.kind == "lab_result":
        return policy.result_text(record)
    return getattr(record, column.field)


def merge_records(
    workbook: Workbook,
    records: Iterable[LabRecord],
    policy: LabLedgerPolicy,
    fingerprints: Mapping[RecordKey, str] | None = None,
) -> MergeResult:
    """기존 행은 보존하고 신규 합성 행만 추가한다. 위급치·변경은 검토에 남긴다."""
    sheet = workbook[policy.sheet_name]
    if tuple(cell.value for cell in sheet[HEADER_ROW]) != policy.headers:
        raise ValueError("HEADER_MISMATCH")
    report_column = next(i for i, column in enumerate(policy.columns, 1) if column.field == "report_ref")
    chart_column = next(i for i, column in enumerate(policy.columns, 1) if column.field == "chart_no")
    existing: dict[RecordKey, int] = {}
    for row in range(HEADER_ROW + 1, sheet.max_row + 1):
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
            value = _cell_value(record, column, policy)
            cell = sheet.cell(row, index, value)
            cell.font = Font(name="맑은 고딕", size=10)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=column.kind in {"lab_result", "exam_kinds", "text"},
                                       horizontal="left" if column.kind == "lab_result" else "center")
            if isinstance(value, str):
                # 외부 문자열이 = 등으로 시작해도 수식으로 실행되지 않게 한다.
                cell.data_type = "s"
                cell.number_format = "@"
            elif column.kind == "date":
                cell.number_format = "yyyy-mm-dd"
            if column.kind == "lab_result" and critical:
                cell.fill = CRITICAL_FILL
        # 결과란에 실제로 적히는 항목 중 약칭 목록에 없는 이름만 검토한다.
        if any(
            item.name not in policy.item_names for item in record.items
            if (item.flag or item.critical) and item.name not in policy.qualitative_names
        ):
            issues.append(ReviewIssue(row, result_header, "ITEM_NAME_UNREGISTERED"))
        if critical:
            # 원장 보고 대상. 보고 완료 여부는 사람이 대시보드에서 기록한다(L3).
            issues.append(ReviewIssue(row, result_header, "CRITICAL_REPORT"))
        # 분류가 셋 이상이면 칸 안에서 두 줄로 접히므로 행을 높인다.
        sheet.row_dimensions[row].height = 26 if len(record.exam_kinds) <= 2 else 38
        existing[key] = row
        known[key] = digest
        appended += 1
    sheet.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(policy.columns))}{sheet.max_row}"
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
