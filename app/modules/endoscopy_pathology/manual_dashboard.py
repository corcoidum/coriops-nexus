"""합성 자료로 수동 입력 흐름을 확인하는 독립 서비스. 영구 저장하지 않는다."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from threading import RLock
from uuid import UUID
from zoneinfo import ZoneInfo

from app.kernel.clock import Clock, SystemClock


STAGE_LABELS = {
    "RESULT_PENDING": "결과 대기",
    "DOCTOR_PENDING": "재검 시점 기록 대기",
    "NOTIFY_PENDING": "환자 안내 대기",
    "DONE": "안내 완료",
}
STAGE_ACTIONS = {
    "RESULT_PENDING": "결과 입력",
    "DOCTOR_PENDING": "원장 지시 기록",
    "NOTIFY_PENDING": "안내 기록",
    "DONE": "기록 보기",
}
KST = ZoneInfo("Asia/Seoul")


class DashboardError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class DemoCase:
    id: UUID
    patient_name: str
    chart_no: str
    procedure_date: date
    procedure_type: str
    specimen_count: int
    created_at: datetime
    updated_at: datetime
    result_received_at: datetime | None = None
    result_summary: str = ""
    site_summary: str = ""
    doctor_decided_at: datetime | None = None
    followup_due: date | None = None
    no_followup_reason: str = ""
    notified: bool = False
    notified_at: datetime | None = None
    contact_attempts: int = 0

    @property
    def stage(self) -> str:
        """화면용 분류이며 정식 PathologyRequest 상태를 대신하지 않는다."""
        if self.notified:
            return "DONE"
        if self.doctor_decided_at is not None:
            return "NOTIFY_PENDING"
        if self.result_received_at is not None:
            return "DOCTOR_PENDING"
        return "RESULT_PENDING"

    @property
    def display_name(self) -> str:
        return f"테스트 · {self.chart_no[-2:]}"

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]

    @property
    def action_label(self) -> str:
        return STAGE_ACTIONS[self.stage]


class ManualDashboardService:
    def __init__(self, clock: Clock | None = None):
        self._clock = clock or SystemClock()
        self._lock = RLock()
        self._cases: dict[UUID, DemoCase] = {}
        self.reset()

    def _get(self, case_id: UUID) -> DemoCase:
        try:
            return self._cases[case_id]
        except KeyError:
            raise DashboardError("시연 항목을 찾을 수 없습니다.", 404) from None

    def snapshot(self, stage: str = "ALL", selected_id: UUID | None = None) -> dict:
        with self._lock:
            if stage != "ALL" and stage not in STAGE_LABELS:
                raise DashboardError("알 수 없는 업무 분류입니다.", 422)
            all_cases = list(self._cases.values())
            counts = {key: sum(case.stage == key for case in all_cases) for key in STAGE_LABELS}
            cases = [case for case in all_cases if stage == "ALL" or case.stage == stage]
            selected = self._get(selected_id) if selected_id else (cases[0] if cases else None)
            return {
                "cases": cases,
                "counts": counts,
                "selected": selected,
                "today": self._clock.now().astimezone(KST).date(),
                "stage": stage,
                "stage_labels": STAGE_LABELS,
                "total": len(all_cases),
            }

    @staticmethod
    def _text(value: str, label: str, maximum: int) -> str:
        clean = value.strip()
        if not clean or len(clean) > maximum:
            raise DashboardError(f"{label}을(를) 1~{maximum}자로 입력해 주세요.", 422)
        return clean

    def receive(self, case_id: UUID, result_summary: str, site_summary: str) -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "RESULT_PENDING":
                raise DashboardError("결과 대기 항목에서 입력해 주세요.")
            result = self._text(result_summary, "결과 요약", 120)
            site = self._text(site_summary, "검사위치", 80)
            now = self._clock.now()
            self._cases[case_id] = replace(
                case, result_received_at=now, result_summary=result,
                site_summary=site, updated_at=now,
            )

    def decide(self, case_id: UUID, mode: str, due_date: date | None = None, reason: str = "") -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "DOCTOR_PENDING":
                raise DashboardError("결과 입력 후 원장 지시를 기록해 주세요.")
            if mode == "required":
                if due_date is None:
                    raise DashboardError("원장이 정한 재검 날짜를 입력해 주세요.", 422)
                # 연도 오타 등으로 이미 지난 날짜가 지시로 남지 않게 한다. 날짜를 대신 정하지는 않는다.
                if due_date < self._clock.now().astimezone(KST).date():
                    raise DashboardError("재검 날짜가 오늘보다 이전입니다. 원장이 정한 날짜를 다시 확인해 주세요.", 422)
                clean_reason = ""
            elif mode == "not_required":
                clean_reason = self._text(reason, "재검 불필요 사유", 120)
                due_date = None
            else:
                raise DashboardError("재검 여부를 선택해 주세요.", 422)
            now = self._clock.now()
            # 재검 간격을 추천하거나 계산하지 않고 입력 날짜만 보관한다.
            self._cases[case_id] = replace(
                case, doctor_decided_at=now, followup_due=due_date,
                no_followup_reason=clean_reason, updated_at=now,
            )

    def notify(self, case_id: UUID, outcome: str) -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "NOTIFY_PENDING":
                raise DashboardError("원장 지시 기록 후 안내를 기록해 주세요.")
            if outcome not in {"reached", "no_answer"}:
                raise DashboardError("안내 결과를 선택해 주세요.", 422)
            now = self._clock.now()
            self._cases[case_id] = replace(
                case, contact_attempts=case.contact_attempts + 1,
                notified=outcome == "reached",
                notified_at=now if outcome == "reached" else None, updated_at=now,
            )

    def reset(self) -> None:
        """새 환자를 받지 않고 고정된 합성 8건만 다시 만든다."""
        with self._lock:
            now = self._clock.now()
            today = now.astimezone(KST).date()
            cases = []
            for number in range(1, 9):
                created = now - timedelta(days=9 - number)
                case = DemoCase(
                    id=UUID(int=number), patient_name=f"테스트환자{number}",
                    chart_no=f"T-{number:04}", procedure_date=today - timedelta(days=9 - number),
                    procedure_type="위내시경" if number % 2 else "대장내시경",
                    specimen_count=1 if number % 2 else 2,
                    created_at=created, updated_at=created,
                )
                if number >= 4:
                    case = replace(
                        case, result_received_at=now - timedelta(hours=3),
                        result_summary=f"합성 결과 예시 {number}", site_summary="합성 위치",
                    )
                if number >= 6:
                    # 합성 지시 예시일 뿐 환자별 주기를 산출하지 않는다.
                    case = replace(
                        case, doctor_decided_at=now - timedelta(hours=2),
                        followup_due=date(2027, 4, 22) if number == 6 else date(2027, 10, 22),
                    )
                if number == 7:
                    case = replace(case, contact_attempts=1)
                if number == 8:
                    case = replace(case, notified=True, notified_at=now, contact_attempts=1)
                cases.append(replace(case, updated_at=now))
            self._cases = {case.id: case for case in cases}
