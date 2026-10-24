"""합성 자료로 조직검체 장부 업무를 확인하는 독립 서비스. 영구 저장하지 않는다.

흐름: 인계 대기 → 결과 대기 → 원장 지시 대기 → 재검 예정 → 종결.
결과 설명·환자 안내는 EMR에서 관리하므로 이 화면에서 기록하지 않는다(A12).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from threading import RLock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import yaml

from app.kernel.calendar import ClinicCalendar
from app.kernel.clock import Clock, SystemClock

from .result_notation import Finding, NotationError, ResultCodeBook


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
STAGE_ORDER = {key: index for index, key in enumerate(STAGE_LABELS)}
KST = ZoneInfo("Asia/Seoul")
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "manual_dashboard.yaml"
REPORT_REF = re.compile(r"^[0-9A-Za-z-]{4,20}$")
SEARCH_MAX = 30


class DashboardError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class DashboardPolicy:
    result_delay_business_days: int
    followup_window_days: int
    handoff_defaults: dict[str, str]
    staff_name_max_length: int

    @classmethod
    def load(cls, path: Path | None = None) -> DashboardPolicy:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        return cls(
            result_delay_business_days=int(raw["result_delay_business_days"]),
            followup_window_days=int(raw["followup_window_days"]),
            handoff_defaults=dict(raw["handoff_defaults"]),
            staff_name_max_length=int(raw["staff_name_max_length"]),
        )


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
class Alert:
    text: str
    level: str  # normal / warn / danger


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
    handoff_id: UUID | None = None
    entrusted_on: date | None = None
    report_ref: str = ""
    result_received_at: datetime | None = None
    findings: tuple[Finding, ...] = ()
    sydney: tuple[tuple[str, str], ...] = ()
    site_summary: str = ""
    doctor_decided_at: datetime | None = None
    followup_due: date | None = None
    no_followup_reason: str = ""
    followup_done_on: date | None = None

    @property
    def stage(self) -> str:
        """화면용 분류이며 정식 PathologyRequest 상태를 대신하지 않는다."""
        if self.handoff_id is None:
            return "HANDOFF_PENDING"
        if self.result_received_at is None:
            return "RESULT_PENDING"
        if self.doctor_decided_at is None:
            return "DOCTOR_PENDING"
        if self.followup_due is not None and self.followup_done_on is None:
            return "FOLLOWUP"
        return "CLOSED"

    @property
    def display_name(self) -> str:
        return f"테스트 · {self.chart_no[-2:]}"

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]

    @property
    def action_label(self) -> str:
        return STAGE_ACTIONS[self.stage]

    @property
    def result_notation(self) -> str:
        return ", ".join(finding.display() for finding in self.findings)

    @property
    def needs_code_review(self) -> bool:
        return any(not finding.registered for finding in self.findings)


@dataclass
class _State:
    cases: dict[UUID, DemoCase] = field(default_factory=dict)
    handoffs: list[Handoff] = field(default_factory=list)


class ManualDashboardService:
    def __init__(self, clock: Clock | None = None, calendar: ClinicCalendar | None = None,
                 policy: DashboardPolicy | None = None, codebook: ResultCodeBook | None = None):
        self._clock = clock or SystemClock()
        self._calendar = calendar or ClinicCalendar.load()
        self._policy = policy or DashboardPolicy.load()
        self._codebook = codebook or ResultCodeBook.load()
        self._lock = RLock()
        self._state = _State()
        self.reset()

    # ---------- 조회

    def _today(self) -> date:
        return self._clock.now().astimezone(KST).date()

    def _get(self, case_id: UUID) -> DemoCase:
        try:
            return self._state.cases[case_id]
        except KeyError:
            raise DashboardError("시연 항목을 찾을 수 없습니다.", 404) from None

    def _alert(self, case: DemoCase, today: date, pickup: dict) -> Alert:
        stage = case.stage
        if stage == "HANDOFF_PENDING":
            if case.procedure_date < today:
                return Alert("이전 검사일 · 인계 누락", "danger")
            return Alert(pickup["text"], pickup["level"])
        if stage == "RESULT_PENDING":
            days = self._calendar.business_days_between(case.entrusted_on, today)
            delayed = days > self._policy.result_delay_business_days
            return Alert(f"위탁 후 {days}진료일" + (" · 지연" if delayed else ""), "danger" if delayed else "normal")
        if stage == "DOCTOR_PENDING":
            return Alert("미등록 코드 검토", "warn") if case.needs_code_review else Alert("결과 입력됨", "normal")
        if stage == "FOLLOWUP":
            left = (case.followup_due - today).days
            if left < 0:
                return Alert(f"재검 기한 {-left}일 경과", "danger")
            level = "warn" if left <= self._policy.followup_window_days else "normal"
            return Alert(f"재검 D-{left}", level)
        return Alert("재검 완료" if case.followup_done_on else "재검 불필요", "normal")

    def _pickup(self, today: date, now: datetime, pending: list[DemoCase]) -> dict:
        """오늘 씨젠 수령 시각과 인계 상태. 시각은 config/clinic.yaml이 원천이다."""
        pickup = self._calendar.pickup_time(today)
        handed_today = [h for h in self._state.handoffs if h.handed_at.astimezone(KST).date() == today]
        info = {
            "time": pickup, "pending_cases": len(pending),
            "pending_specimens": sum(case.specimen_count for case in pending),
            "handed_today": handed_today,
        }
        if not pending:
            info.update(status="DONE" if handed_today else "NONE", level="normal",
                        text="오늘 인계 완료" if handed_today else "인계할 검체 없음")
        elif pickup is None:
            info.update(status="NO_PICKUP", level="warn", text="오늘 씨젠 수령 없음 · 보관 확인")
        else:
            deadline = datetime.combine(today, pickup, KST)
            minutes = int((deadline - now.astimezone(KST)).total_seconds() // 60)
            if minutes < 0:
                info.update(status="OVERDUE", level="danger", text=f"수령 {pickup:%H:%M} 지남 · 인계 확인")
            else:
                info.update(status="DUE", level="warn",
                            text=f"수령 {pickup:%H:%M}까지 {minutes // 60}시간 {minutes % 60}분")
        return info

    def _matches(self, case: DemoCase, query: str) -> bool:
        if not query:
            return True
        upper = query.upper()
        return (
            query in case.chart_no
            or (case.report_ref and query in case.report_ref)
            or any(finding.code.upper() == upper for finding in case.findings)
        )

    def _sort_key(self, case: DemoCase, today: date):
        if case.stage == "RESULT_PENDING":
            within = -self._calendar.business_days_between(case.entrusted_on, today)
        elif case.stage == "FOLLOWUP":
            within = (case.followup_due - today).days
        else:
            within = 0
        return (STAGE_ORDER[case.stage], within, case.procedure_date)

    def snapshot(self, stage: str = "ALL", selected_id: UUID | None = None, query: str = "") -> dict:
        with self._lock:
            if stage != "ALL" and stage not in STAGE_LABELS:
                raise DashboardError("알 수 없는 업무 분류입니다.", 422)
            query = query.strip()
            if len(query) > SEARCH_MAX:
                raise DashboardError(f"검색어는 {SEARCH_MAX}자까지 입력할 수 있습니다.", 422)
            now = self._clock.now()
            today = now.astimezone(KST).date()
            all_cases = sorted(self._state.cases.values(), key=lambda case: self._sort_key(case, today))
            pending = [case for case in all_cases if case.stage == "HANDOFF_PENDING"]
            pickup = self._pickup(today, now, pending)
            alerts = {case.id: self._alert(case, today, pickup) for case in all_cases}
            counts = {key: sum(case.stage == key for case in all_cases) for key in STAGE_LABELS}
            flags = {
                "result_delayed": sum(c.stage == "RESULT_PENDING" and alerts[c.id].level == "danger" for c in all_cases),
                "code_review": sum(c.stage == "DOCTOR_PENDING" and c.needs_code_review for c in all_cases),
                "followup_overdue": sum(c.stage == "FOLLOWUP" and alerts[c.id].level == "danger" for c in all_cases),
                "followup_soon": sum(c.stage == "FOLLOWUP" and alerts[c.id].level == "warn" for c in all_cases),
            }
            cases = [c for c in all_cases if (stage == "ALL" or c.stage == stage) and self._matches(c, query)]
            selected = self._get(selected_id) if selected_id else (cases[0] if cases else None)
            return {
                "cases": cases, "counts": counts, "flags": flags, "alerts": alerts,
                "selected": selected, "today": today, "stage": stage, "query": query,
                "stage_labels": STAGE_LABELS, "total": len(all_cases), "pickup": pickup,
                "handoff_defaults": self._policy.handoff_defaults,
                "sydney_text": self._codebook.format_sydney(dict(selected.sydney)) if selected else "",
                "delay_days": self._policy.result_delay_business_days,
                "window_days": self._policy.followup_window_days,
            }

    # ---------- 변경

    @staticmethod
    def _text(value: str, label: str, maximum: int) -> str:
        clean = value.strip()
        if not clean or len(clean) > maximum:
            raise DashboardError(f"{label}을(를) 1~{maximum}자로 입력해 주세요.", 422)
        return clean

    def handoff(self, registered_by: str, handed_by: str, receiver_name: str, confirmed_count: int) -> None:
        """인계 대기 검체 전체를 한 번에 넘긴다. 확인 병 수가 장부와 다르면 기록하지 않는다."""
        with self._lock:
            pending = [c for c in self._state.cases.values() if c.stage == "HANDOFF_PENDING"]
            if not pending:
                raise DashboardError("인계할 검체가 없습니다.")
            limit = self._policy.staff_name_max_length
            names = (
                self._text(registered_by, "접수인", limit),
                self._text(handed_by, "인계인", limit),
                self._text(receiver_name, "인수인(씨젠)", limit),
            )
            expected = sum(case.specimen_count for case in pending)
            if confirmed_count != expected:
                raise DashboardError(
                    f"병 수가 맞지 않습니다. 장부 {expected}병 / 확인 {confirmed_count}병. 다시 세어 주세요.", 422)
            now = self._clock.now()
            record = Handoff(uuid4(), now, *names, specimen_count=expected, case_count=len(pending))
            self._state.handoffs.append(record)
            today = now.astimezone(KST).date()
            for case in pending:
                self._state.cases[case.id] = replace(
                    case, handoff_id=record.id, entrusted_on=today, updated_at=now)

    def receive(self, case_id: UUID, report_ref: str, result_notation: str,
                site_summary: str, sydney_notation: str = "") -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "RESULT_PENDING":
                raise DashboardError("결과 대기 항목에서 입력해 주세요.")
            ref = report_ref.strip()
            if not REPORT_REF.match(ref):
                raise DashboardError("접수번호는 영문·숫자 4~20자로 입력해 주세요.", 422)
            if any(other.report_ref == ref for other in self._state.cases.values() if other.id != case_id):
                raise DashboardError("다른 검체에 이미 입력된 접수번호입니다.", 422)
            try:
                findings = self._codebook.parse_findings(result_notation)
                sydney = self._codebook.parse_sydney(sydney_notation) if sydney_notation.strip() else {}
            except NotationError as error:
                raise DashboardError(str(error), 422) from None
            if sydney and case.procedure_type != "위내시경":
                raise DashboardError("Sydney 등급은 위 검체에만 입력합니다.", 422)
            site = self._text(site_summary, "검사위치", 80)
            now = self._clock.now()
            self._state.cases[case_id] = replace(
                case, report_ref=ref, result_received_at=now, findings=findings,
                sydney=tuple(sydney.items()), site_summary=site, updated_at=now,
            )

    def decide(self, case_id: UUID, mode: str, due_date: date | None = None, reason: str = "") -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "DOCTOR_PENDING":
                raise DashboardError("결과 입력 후 원장 지시를 기록해 주세요.")
            if mode == "required":
                if due_date is None:
                    raise DashboardError("원장이 정한 재검 날짜를 입력해 주세요.", 422)
                clean_reason = ""
            elif mode == "not_required":
                clean_reason = self._text(reason, "재검 불필요 사유", 120)
                due_date = None
            else:
                raise DashboardError("재검 여부를 선택해 주세요.", 422)
            now = self._clock.now()
            # 재검 간격을 추천하거나 계산하지 않고 입력 날짜만 보관한다.
            self._state.cases[case_id] = replace(
                case, doctor_decided_at=now, followup_due=due_date,
                no_followup_reason=clean_reason, updated_at=now,
            )

    def complete_followup(self, case_id: UUID, done_on: date | None) -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "FOLLOWUP":
                raise DashboardError("재검 예정 항목에서 기록해 주세요.")
            if done_on is None or done_on > self._today():
                raise DashboardError("재검을 시행한 날짜(오늘 이전)를 입력해 주세요.", 422)
            self._state.cases[case_id] = replace(case, followup_done_on=done_on, updated_at=self._clock.now())

    def reset(self) -> None:
        """새 환자를 받지 않고 고정된 합성 12건만 다시 만든다."""
        with self._lock:
            now = self._clock.now()
            today = now.astimezone(KST).date()
            back = self._calendar.subtract_business_days
            book = self._codebook
            handoff_id = UUID(int=1000)
            plans = [
                # (내시경, 병 수, 검사일, 단계별 추가 값)
                ("위내시경", 1, today, {}),
                ("대장내시경", 3, today, {}),
                ("위내시경", 1, back(today, 1), {"handed": True}),
                ("대장내시경", 2, back(today, 2), {"handed": True}),
                ("위내시경", 2, back(today, 4), {"handed": True}),
                ("대장내시경", 2, back(today, 2), {"result": "TA#2(L), H#1"}),
                ("위내시경", 1, back(today, 3), {"result": "CAG#1(im)", "sydney": "HP-/Neu+/Mon++/Atr+/IM+"}),
                ("위내시경", 1, back(today, 3), {"result": "TEST#1"}),
                ("대장내시경", 3, today - timedelta(days=200), {"result": "TA#3(L)", "due": today + timedelta(days=20)}),
                ("위내시경", 1, today - timedelta(days=380), {"result": "CAG#1(im)", "due": today - timedelta(days=10)}),
                ("대장내시경", 1, today - timedelta(days=30), {"result": "SS#1", "due": today + timedelta(days=300)}),
                ("위내시경", 1, today - timedelta(days=14), {"result": "CG#1", "reason": "합성 원장 지시"}),
            ]
            cases = {}
            for number, (kind, count, day, extra) in enumerate(plans, start=1):
                created = datetime.combine(day, datetime.min.time(), KST)
                case = DemoCase(
                    id=UUID(int=number), patient_name=f"테스트환자{number}", chart_no=f"T-{number:04}",
                    procedure_date=day, procedure_type=kind, specimen_count=count,
                    created_at=created, updated_at=created,
                )
                if extra:
                    case = replace(case, handoff_id=handoff_id, entrusted_on=day)
                if "result" in extra:
                    sydney = book.parse_sydney(extra["sydney"]) if "sydney" in extra else {}
                    case = replace(
                        case, report_ref=f"T97{number:05}", result_received_at=created + timedelta(days=1),
                        findings=book.parse_findings(extra["result"]), sydney=tuple(sydney.items()),
                        site_summary="합성 위치",
                    )
                if "due" in extra or "reason" in extra:
                    # 합성 지시 예시일 뿐 환자별 주기를 산출하지 않는다.
                    case = replace(case, doctor_decided_at=created + timedelta(days=2),
                                   followup_due=extra.get("due"), no_followup_reason=extra.get("reason", ""))
                cases[case.id] = case
            self._state = _State(cases=cases)
