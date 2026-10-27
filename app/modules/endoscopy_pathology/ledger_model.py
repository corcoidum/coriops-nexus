"""조직검체·CLO·Stool 장부 1행과 부속 기록. 저장소(메모리·PostgreSQL)가 함께 쓰는 값 객체다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from .result_notation import Finding


KST = ZoneInfo("Asia/Seoul")
KINDS = ("BIOPSY", "CLO", "STOOL")
PROCEDURE_LABELS = {"stomach": "위내시경", "colon": "대장내시경"}
STAGE_LABELS = {
    "HANDOFF_PENDING": "인계 대기",
    "RESULT_PENDING": "결과 대기",
    "DOCTOR_PENDING": "원장 지시 대기",
    "FOLLOWUP": "재검 예정",
    "CLOSED": "종결",
}
STAGE_ACTIONS = {
    "HANDOFF_PENDING": "오늘 인계 기록",
    "RESULT_PENDING": "결과 입력",
    "DOCTOR_PENDING": "원장 지시 기록",
    "FOLLOWUP": "재검 완료 기록",
    "CLOSED": "기록 보기",
}
REVIEW_LABELS = {
    "UNREGISTERED_CODE": "미등록 코드",
    "RESULT_UNPARSED": "결과 표기 확인",
    "SYDNEY_UNPARSED": "특이소견 표기 확인",
}


@dataclass(frozen=True)
class LedgerEntry:
    """장부 1행. 판독문 원문·비고는 담지 않는다(A11)."""

    id: UUID
    kind: str
    chart_no: str
    patient_name: str
    exam_date: date
    created_at: datetime
    updated_at: datetime
    version: int = 0
    source: str = "MANUAL"
    sex: str | None = None
    age: int | None = None
    procedure_type: str | None = None
    specimen_count: int | None = None
    site: str = ""
    report_ref: str = ""
    registered_by: str = ""
    handed_by: str = ""
    received_by: str = ""
    handoff_id: UUID | None = None
    entrusted_on: date | None = None
    reported_on: date | None = None
    findings: tuple[Finding, ...] = ()
    sydney: tuple[tuple[str, str], ...] = ()
    result_code: str = ""
    review_codes: tuple[str, ...] = ()
    decided_at: datetime | None = None
    decided_by: str | None = None  # 원장 지시를 기록한 계정. None = Stage A 이전 자료
    followup_due: date | None = None
    no_followup_reason: str = ""
    followup_done_on: date | None = None
    followup_done_by: str | None = None
    import_batch_id: UUID | None = None

    def needs_handoff(self, handoff_kinds: frozenset[str]) -> bool:
        return self.kind in handoff_kinds and self.entrusted_on is None

    def stage_for(self, handoff_kinds: frozenset[str], review_kinds: frozenset[str] | None = None) -> str:
        """화면용 분류이며 정식 PathologyRequest 상태를 대신하지 않는다.
        review_kinds에 없는 종류(CLO)는 결과를 기록하면 종결한다(A27)."""
        if self.needs_handoff(handoff_kinds):
            return "HANDOFF_PENDING"
        if self.reported_on is None:
            return "RESULT_PENDING"
        if self.decided_at is None:
            if review_kinds is not None and self.kind not in review_kinds:
                return "CLOSED"
            return "DOCTOR_PENDING"
        if self.followup_due is not None and self.followup_done_on is None:
            return "FOLLOWUP"
        return "CLOSED"

    @property
    def waiting_since(self) -> date:
        """결과 대기 경과일 기준: 위탁일, 인계가 없는 종류는 검사일."""
        return self.entrusted_on or self.exam_date

    @property
    def closed_on(self) -> date | None:
        if self.followup_done_on:
            return self.followup_done_on
        if self.decided_at and self.followup_due is None:
            return self.decided_at.astimezone(KST).date()
        return None

    @property
    def display_name(self) -> str:
        """화면 기본 표시는 가운데 글자를 가린다(2글자는 끝 글자, 1글자는 전체)."""
        name = self.patient_name
        if len(name) <= 1:
            return "*"
        if len(name) == 2:
            return name[0] + "*"
        return name[0] + "*" * (len(name) - 2) + name[-1]

    @property
    def procedure_label(self) -> str:
        return PROCEDURE_LABELS.get(self.procedure_type or "", "")

    @property
    def result_notation(self) -> str:
        if self.findings:
            return ", ".join(finding.display() for finding in self.findings)
        return self.result_code

    @property
    def all_review_codes(self) -> tuple[str, ...]:
        codes = list(self.review_codes)
        if any(not finding.registered for finding in self.findings) and "UNREGISTERED_CODE" not in codes:
            codes.append("UNREGISTERED_CODE")
        return tuple(codes)

    @property
    def needs_review(self) -> bool:
        return bool(self.all_review_codes)

    @property
    def review_labels(self) -> list[str]:
        return [REVIEW_LABELS.get(code, code) for code in self.all_review_codes]


@dataclass(frozen=True)
class Handoff:
    """하루 한 번 이상 가능한 검체 인계 기록. 접수인·인계인·수령인 3자를 남긴다."""

    id: UUID
    handed_at: datetime
    registered_by: str
    handed_by: str
    receiver_name: str
    specimen_count: int
    case_count: int

    @property
    def handed_time(self) -> str:
        return self.handed_at.astimezone(KST).strftime("%H:%M")


@dataclass(frozen=True)
class ImportBatch:
    """가져오기 1회. 파일명·원본·무시 열 값은 저장하지 않는다."""

    id: UUID
    committed_at: datetime
    digest: str
    accepted: int
    skipped: int
    sheet_counts: dict


@dataclass(frozen=True)
class ExportRecord:
    """엑셀 출력 1회. 언제 몇 건을 어떤 파일 이름으로 지정 폴더에 저장했는지 남긴다."""

    id: UUID
    exported_at: datetime
    file_name: str
    row_count: int

    @property
    def exported_time(self) -> str:
        return self.exported_at.astimezone(KST).strftime("%Y.%m.%d %H:%M")
