"""혈액검체 결과 확인 흐름을 합성 자료로 확인하는 메모리 서비스. 영구 저장하지 않는다.

결과 해석·위급치 판정은 하지 않는다. 직원은 씨젠 결과지(PDF)에서 H/L로 표시된 항목과
정성 검사 Neg/Pos만 옮겨 적고(B14·B16), 위급치는 관리자가 확인한 뒤 표기한다(B15).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from threading import RLock
from uuid import UUID
from zoneinfo import ZoneInfo

from app.kernel.clock import Clock, SystemClock
from app.kernel.web import UserError

from .ledger import LabItem, LabLedgerPolicy, LabRecord, load_policy
from .ledger_demo import synthetic_records


STAGE_LABELS = {
    "RESULT_PENDING": "결과 미수신",
    "CRITICAL_PENDING": "원장 보고 대기",
    "CHECK_PENDING": "확인 대기",
    "DONE": "확인 완료",
}
STAGE_ACTIONS = {
    "RESULT_PENDING": "결과 입력",
    "CRITICAL_PENDING": "원장 보고 기록",
    "CHECK_PENDING": "확인 기록",
    "DONE": "기록 보기",
}
KST = ZoneInfo("Asia/Seoul")
NAME_MAX = 20
REF_MAX = 30
VALUE_MAX = 20


@dataclass(frozen=True, repr=False)
class LabCase:
    id: UUID
    record: LabRecord
    critical_marked_at: datetime | None = None
    critical_marked_by: str = ""
    critical_reported_at: datetime | None = None
    critical_reported_by: str = ""
    result_entered_at: datetime | None = None
    result_entered_by: str = ""
    checked_at: datetime | None = None
    checked_by: str = ""

    @property
    def critical(self) -> bool:
        return any(item.critical for item in self.record.items)

    @property
    def abnormal(self) -> bool:
        return any(item.flag for item in self.record.items)

    @property
    def stage(self) -> str:
        """화면용 분류. 위급치는 원장 보고를 기록해야 확인 단계로 넘어간다."""
        if not self.record.received:
            return "RESULT_PENDING"
        if self.critical and self.critical_reported_at is None:
            return "CRITICAL_PENDING"
        if self.checked_at is None:
            return "CHECK_PENDING"
        return "DONE"

    @property
    def display_name(self) -> str:
        # 목록에는 이름 대신 차트번호 끝자리만 보인다(조직검체 장부와 같은 가림).
        return f"테스트 · {self.record.chart_no[-2:]}"


class LabDashboardService:
    persistent = False

    def __init__(self, clock: Clock | None = None, policy: LabLedgerPolicy | None = None):
        self._clock = clock or SystemClock()
        self._policy = policy or load_policy()
        self._lock = RLock()
        self._cases: dict[UUID, LabCase] = {}
        self.reset()

    def _get(self, case_id: UUID) -> LabCase:
        try:
            return self._cases[case_id]
        except KeyError:
            raise UserError("시연 항목을 찾을 수 없습니다.", 404) from None

    def result_text(self, case: LabCase) -> str:
        return self._policy.result_text(case.record) or ""

    def snapshot(self, stage: str = "ALL", selected_id: UUID | None = None) -> dict:
        with self._lock:
            if stage != "ALL" and stage not in STAGE_LABELS:
                raise UserError("알 수 없는 업무 분류입니다.", 422)
            all_cases = list(self._cases.values())
            counts = {key: sum(case.stage == key for case in all_cases) for key in STAGE_LABELS}
            cases = [case for case in all_cases if stage == "ALL" or case.stage == stage]
            selected = self._get(selected_id) if selected_id else (cases[0] if cases else None)
            return {
                "cases": cases,
                "counts": counts,
                "selected": selected,
                "results": {case.id: self.result_text(case) for case in all_cases},
                "today": self._clock.now().astimezone(KST).date(),
                "stage": stage,
                "stage_labels": STAGE_LABELS,
                "stage_actions": STAGE_ACTIONS,
                "total": len(all_cases),
                "kst": KST,
                "item_names": self._policy.item_names,
                "result_flags": self._policy.result_flags,
                "qualitative_values": self._policy.qualitative_values,
                "qualitative_for": self._policy.qualitative_for,
                "entry_rows": 5,
            }

    @staticmethod
    def _name(value: str, label: str) -> str:
        clean = value.strip()
        if not clean or len(clean) > NAME_MAX:
            raise UserError(f"{label}을(를) 1~{NAME_MAX}자로 입력해 주세요.", 422)
        return clean

    def enter_result(self, case_id: UUID, *, report_ref: str, report_date: date | None,
                     rows: list[tuple[str, str, str]], qualitative: dict[str, str], no_flagged: bool,
                     entered_by: str) -> None:
        """결과지에서 H/L 항목과 정성 검사만 옮겨 적는다. 값을 판정하거나 계산하지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "RESULT_PENDING":
                raise UserError("결과 입력 대기 항목에서 입력해 주세요.")
            name = self._name(entered_by, "입력한 직원")
            ref = report_ref.strip()
            if not ref or len(ref) > REF_MAX:
                raise UserError(f"씨젠 접수번호를 1~{REF_MAX}자로 입력해 주세요.", 422)
            today = self._clock.now().astimezone(KST).date()
            if report_date is None or report_date > today:
                raise UserError("결과지의 결과보고일(회신날짜)을 오늘 이전 날짜로 입력해 주세요.", 422)
            items: list[LabItem] = []
            for item_name, value, flag in rows:
                item_name, value, flag = item_name.strip(), value.strip(), flag.strip()
                if not (item_name or value or flag):
                    continue
                if item_name not in self._policy.item_names:
                    raise UserError("항목을 목록에서 골라 주세요.", 422)
                if not value or len(value) > VALUE_MAX:
                    raise UserError(f"{item_name} 결과값을 1~{VALUE_MAX}자로 입력해 주세요.", 422)
                if flag not in self._policy.result_flags:
                    raise UserError(f"{item_name}의 판정(H/L)을 골라 주세요.", 422)
                if any(existing.name == item_name for existing in items):
                    raise UserError(f"{item_name}을(를) 두 번 입력했습니다.", 422)
                items.append(LabItem(item_name, value, flag))
            # H/L 항목을 하나도 적지 않은 채 저장되는 실수를 막으려고 '없음'을 직접 확인받는다.
            if items and no_flagged:
                raise UserError("H/L 항목을 입력했다면 'H/L 표시 없음'을 해제해 주세요.", 422)
            if not items and not no_flagged:
                raise UserError("H/L 항목을 입력하거나 'H/L 표시 없음'을 체크해 주세요.", 422)
            for qualitative_name in self._policy.qualitative_for(case.record.exam_kinds):
                value = qualitative.get(qualitative_name, "")
                if value not in self._policy.qualitative_values:
                    raise UserError(f"{qualitative_name}의 Neg/Pos를 골라 주세요.", 422)
                items.append(LabItem(qualitative_name, value))
            now = self._clock.now()
            record = replace(case.record, report_ref=ref, report_date=report_date, items=tuple(items),
                             result_received=True)
            self._cases[case_id] = replace(case, record=record, result_entered_at=now, result_entered_by=name)

    def mark_critical(self, case_id: UUID, item_names: list[str], marked_by: str) -> None:
        """관리자가 확인한 위급치를 표기한다(B15). 시스템은 수치로 위급치를 고르지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CHECK_PENDING" or case.critical:
                raise UserError("결과 입력 후 확인 대기 상태에서 표기해 주세요.")
            name = self._name(marked_by, "확인한 관리자")
            flagged = {item.name for item in case.record.items if item.flag}
            chosen = set(item_names)
            if not chosen or not chosen <= flagged:
                raise UserError("H/L로 입력된 항목 중에서 위급치를 골라 주세요.", 422)
            items = tuple(replace(item, critical=item.name in chosen) for item in case.record.items)
            self._cases[case_id] = replace(case, record=replace(case.record, items=items),
                                           critical_marked_at=self._clock.now(), critical_marked_by=name)

    def report_critical(self, case_id: UUID, reported_by: str) -> None:
        """직원이 위급치를 원장에게 보고했음을 기록한다. 원장 지시 내용은 받지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CRITICAL_PENDING":
                raise UserError("원장 보고 대기 항목에서 기록해 주세요.")
            name = self._name(reported_by, "보고한 직원")
            self._cases[case_id] = replace(
                case, critical_reported_at=self._clock.now(), critical_reported_by=name)

    def check(self, case_id: UUID, checked_by: str) -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CHECK_PENDING":
                raise UserError("확인 대기 항목에서 기록해 주세요.")
            name = self._name(checked_by, "확인한 직원")
            self._cases[case_id] = replace(case, checked_at=self._clock.now(), checked_by=name)

    def critical_pending_count(self) -> int:
        """모든 화면 상단 알림용. 건수만 돌려주고 환자 정보는 담지 않는다."""
        with self._lock:
            return sum(case.stage == "CRITICAL_PENDING" for case in self._cases.values())

    def subject_of(self, case_id: UUID) -> str:
        with self._lock:
            return self._get(case_id).record.chart_no

    def reset(self) -> None:
        """고정된 합성 10건만 다시 만든다. 새 수진자를 받지 않는다."""
        with self._lock:
            now = self._clock.now()
            cases = {}
            for number, record in enumerate(synthetic_records(), 1):
                case = LabCase(UUID(int=number), record)
                if any(item.critical for item in record.items):
                    # 시연 자료의 위급치는 관리자가 이미 표기한 상태로 둔다.
                    case = replace(case, critical_marked_at=now, critical_marked_by="테스트관리자")
                cases[case.id] = case
            self._cases = cases
