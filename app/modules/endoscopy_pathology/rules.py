"""장부 규칙 L01~L05(A17). 상태·기한·누락만 계산하고 결과 코드의 의미로 판단하지 않는다(Q19).

규칙은 조회만 한다. 할 일 저장·중복 방지·자동 해소는 커널 실행기(app.kernel.tasks)가 맡는다.
기한(due_at)은 KST 날짜의 마지막 시각, 인계는 수령 시각이다. 화면의 날짜 기준 지연·도래 표시와 같은 날 바뀐다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.kernel.calendar import ClinicCalendar
from app.kernel.tasks import Candidate, RuleSpec

from .ledger_model import KST, LedgerEntry

SUBJECT_TYPE = "exam"


def end_of_day(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(0), KST) - timedelta(microseconds=1)


def handoff_due(entry: LedgerEntry, calendar: ClinicCalendar) -> datetime:
    """당일 인수·당일 인계(A16): 시행날짜의 수령 시각. 그날 수령이 없으면 다음 수령일의 수령 시각."""
    pickup_day = calendar.next_pickup(entry.exam_date)
    if pickup_day is None:
        return end_of_day(entry.exam_date)
    return datetime.combine(pickup_day, calendar.pickup_time(pickup_day), KST)


def ledger_candidates(entries: list[LedgerEntry], stages: dict, now: datetime, specs: dict[str, RuleSpec],
                      calendar: ClinicCalendar, handoff_kinds: frozenset[str]) -> list[Candidate]:
    """지금 열려 있어야 하는 할 일 후보. stages는 화면과 같은 단계 계산 결과다."""
    today = now.astimezone(KST).date()
    found: list[Candidate] = []

    def add(rule_id: str, entry: LedgerEntry, anchor: date, due_at: datetime) -> None:
        if rule_id in specs:
            found.append(Candidate(rule_id, SUBJECT_TYPE, entry.id, anchor.isoformat(), due_at))

    for entry in entries:
        stage = stages[entry.id]
        if stage == "HANDOFF_PENDING" and entry.kind in handoff_kinds:
            due = handoff_due(entry, calendar)
            if now > due:
                add("PATH.L01", entry, entry.exam_date, due)
        elif stage == "RESULT_PENDING" and "PATH.L02" in specs:
            params = specs["PATH.L02"].params
            limit = params["rut_business_days"] if entry.kind == "CLO" else params["business_days"]
            # 화면과 같은 기준: 기준일 다음날부터 센 진료일이 limit을 넘는 첫 진료일 0시부터 지연이다.
            due = end_of_day(calendar.add_business_days(entry.waiting_since, limit + 1) - timedelta(days=1))
            if now > due:
                add("PATH.L02", entry, entry.waiting_since, due)
        elif stage == "DOCTOR_PENDING" and "PATH.L03" in specs:
            params = specs["PATH.L03"].params
            if entry.source not in params.get("skip_sources", ()):
                reported = entry.reported_on or today
                add("PATH.L03", entry, reported, end_of_day(calendar.add_business_days(reported, params["business_days"])))
        elif stage == "FOLLOWUP" and entry.followup_due is not None:
            left = (entry.followup_due - today).days
            if left <= 0:
                add("PATH.L05", entry, entry.followup_due, end_of_day(entry.followup_due))
            elif "PATH.L04" in specs and left <= specs["PATH.L04"].params["window_days"]:
                add("PATH.L04", entry, entry.followup_due, end_of_day(entry.followup_due))
    return found
