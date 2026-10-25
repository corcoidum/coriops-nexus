"""혈액검체 결과 확인 흐름을 합성 자료로 확인하는 메모리 서비스. 영구 저장하지 않는다.

결과 해석·위급치 판정은 하지 않는다. 씨젠이 표시한 H/L·위급치를 보여주고,
직원의 원장 보고·확인 기록만 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from uuid import UUID
from zoneinfo import ZoneInfo

from app.kernel.clock import Clock, SystemClock
from app.kernel.web import UserError

from .ledger import LabLedgerPolicy, LabRecord, format_result, load_policy
from .ledger_demo import synthetic_records


STAGE_LABELS = {
    "RESULT_PENDING": "결과 미수신",
    "CRITICAL_PENDING": "원장 보고 대기",
    "CHECK_PENDING": "확인 대기",
    "DONE": "확인 완료",
}
STAGE_ACTIONS = {
    "RESULT_PENDING": "결과 기다림",
    "CRITICAL_PENDING": "원장 보고 기록",
    "CHECK_PENDING": "확인 기록",
    "DONE": "기록 보기",
}
KST = ZoneInfo("Asia/Seoul")
NAME_MAX = 20


@dataclass(frozen=True, repr=False)
class LabCase:
    id: UUID
    record: LabRecord
    critical_reported_at: datetime | None = None
    critical_reported_by: str = ""
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
        if not self.record.items:
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
        return format_result(case.record.items, self._policy.normal_label) or ""

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
            }

    @staticmethod
    def _name(value: str, label: str) -> str:
        clean = value.strip()
        if not clean or len(clean) > NAME_MAX:
            raise UserError(f"{label}을(를) 1~{NAME_MAX}자로 입력해 주세요.", 422)
        return clean

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
            self._cases = {
                UUID(int=number): LabCase(UUID(int=number), record)
                for number, record in enumerate(synthetic_records(), 1)
            }
