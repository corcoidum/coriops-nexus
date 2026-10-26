"""Stage B 규칙(L01~L05)과 할 일 실행기. 규칙마다 생김·안 생김·저절로 닫힘, 중복 방지, 재현성을 본다(A17)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.kernel.calendar import ClinicCalendar
from app.kernel.tasks import Candidate, MemoryTaskStore, RuleBook, TaskClosed, TaskEngine
from app.modules.endoscopy_pathology.ledger_db import MemoryStore, replace_entry
from app.modules.endoscopy_pathology.ledger_model import KST
from app.modules.endoscopy_pathology.manual_dashboard import DashboardPolicy, ManualDashboardService
from app.modules.endoscopy_pathology.rules import handoff_due


def kst(year, month, day, hour=10, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


class MovingClock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def now(self) -> datetime:
        return self.moment.astimezone(timezone.utc)


# 2026-11-05(목) 10:00 KST. 목요일 씨젠 수령 15:00.
THU = kst(2026, 11, 5)


@pytest.fixture
def clock():
    return MovingClock(THU)


@pytest.fixture
def service(clock, tmp_path):
    return ManualDashboardService(clock=clock, store=MemoryStore(), export_dir=tmp_path)


def open_tasks(service, rule_id=None):
    return [t for t in service.tasks.store.tasks()
            if t.status == "OPEN" and (rule_id is None or t.rule_id == rule_id)]


def biopsy(service, chart="T-0701", day=date(2026, 11, 5), kind="BIOPSY"):
    if kind == "BIOPSY":
        return service.register("BIOPSY", chart, "테스트규칙", day, procedure_type="stomach", specimen_count="1")
    return service.register(kind, chart, "테스트규칙", day, specimen_count="1" if kind == "STOOL" else "")


def at(service, clock, moment):
    clock.moment = moment
    return service.tasks.run()


# ---------- L01 인계 누락 (조직검사·Stool 당일 인수·당일 인계, A16)


@pytest.mark.parametrize("kind", ["BIOPSY", "STOOL"])
def test_l01_opens_after_pickup_time_and_closes_on_handoff(service, clock, kind):
    entry_id = biopsy(service, kind=kind)
    at(service, clock, kst(2026, 11, 5, 14, 59))
    assert open_tasks(service, "PATH.L01") == []
    at(service, clock, kst(2026, 11, 5, 15, 1))
    [task] = open_tasks(service, "PATH.L01")
    assert (task.subject_id, task.assignee_role, task.priority, task.title) == (entry_id, "NURSE", "HIGH", "검체 인계 확인")
    assert task.due_at == kst(2026, 11, 5, 15, 0) and task.overdue(clock.now())

    service.handoff("테스트 접수", "테스트 인계", "테스트 수령", 1)
    assert open_tasks(service, "PATH.L01") == []
    assert [t.status for t in service.tasks.store.tasks()] == ["AUTO_RESOLVED"]


def test_l01_never_for_rut_and_wednesday_pickup_is_11(service, clock):
    biopsy(service, chart="T-0702", kind="CLO")
    at(service, clock, kst(2026, 11, 5, 23, 0))
    assert open_tasks(service, "PATH.L01") == []

    clock.moment = kst(2026, 11, 4, 9, 0)  # 수요일
    biopsy(service, chart="T-0703", day=date(2026, 11, 4))
    at(service, clock, kst(2026, 11, 4, 10, 59))
    assert open_tasks(service, "PATH.L01") == []
    at(service, clock, kst(2026, 11, 4, 11, 1))
    assert len(open_tasks(service, "PATH.L01")) == 1


def test_handoff_due_moves_to_next_pickup_on_closed_days():
    calendar = ClinicCalendar.load()
    sunday = type("E", (), {"exam_date": date(2026, 11, 8)})()
    assert handoff_due(sunday, calendar) == kst(2026, 11, 9, 15, 0)
    closure = type("E", (), {"exam_date": date(2026, 11, 25)})()  # 합성 임시 휴진(수)
    assert handoff_due(closure, calendar) == kst(2026, 11, 26, 15, 0)


# ---------- L02 결과 지연 — 화면의 '지연' 표시와 같은 순간에 생긴다


@pytest.mark.parametrize("kind", ["BIOPSY", "CLO"])
def test_l02_matches_the_dashboard_delay_on_every_day(service, clock, kind):
    entry_id = biopsy(service, kind=kind)
    if kind == "BIOPSY":
        service.handoff("테스트 접수", "테스트 인계", "테스트 수령", 1)
    for days in range(0, 8):
        for hour in (0, 12, 23):
            moment = THU.replace(hour=hour) + timedelta(days=days)
            at(service, clock, moment)
            alert = service.snapshot()["alerts"][entry_id]
            has_task = bool(open_tasks(service, "PATH.L02"))
            assert has_task == (alert.level == "danger"), (moment, alert.text)
    assert open_tasks(service, "PATH.L02")[0].assignee_role == "ADMIN"


def test_l02_rut_is_due_after_one_clinic_day(service, clock):
    biopsy(service, kind="CLO")  # 목요일
    at(service, clock, kst(2026, 11, 6, 23, 59))  # 금: 1진료일
    assert open_tasks(service, "PATH.L02") == []
    at(service, clock, kst(2026, 11, 7, 0, 1))  # 토: 2진료일 → 지연
    assert len(open_tasks(service, "PATH.L02")) == 1


def test_l02_closes_when_result_arrives(service, clock):
    entry_id = biopsy(service, kind="CLO")
    at(service, clock, kst(2026, 11, 9))
    assert len(open_tasks(service, "PATH.L02")) == 1
    service.receive(entry_id, "", "+", "")
    assert open_tasks(service, "PATH.L02") == []


# ---------- L03 원장 지시 대기


def test_l03_opens_on_result_and_closes_on_decision(service, clock):
    entry_id = biopsy(service, kind="CLO")
    service.receive(entry_id, "", "-", "")
    [task] = open_tasks(service, "PATH.L03")
    assert (task.assignee_role, task.title) == ("DOCTOR", "원장 지시 확인")
    assert task.due_at.astimezone(KST).date() == date(2026, 11, 6)  # 회신 다음 진료일 마감
    assert not task.overdue(clock.now())
    at(service, clock, kst(2026, 11, 7, 0, 1))
    assert open_tasks(service, "PATH.L03")[0].overdue(clock.now())
    service.decide(entry_id, "not_required", reason="합성 사유", actor="테스트원장")
    assert open_tasks(service, "PATH.L03") == []


def test_l03_skips_rows_imported_from_old_excel(service, clock):
    entry_id = biopsy(service, kind="CLO")
    entry = next(e for e in service._store.entries() if e.id == entry_id)
    service._store.write(updated=[replace_entry(entry, clock.now(), source="IMPORT", reported_on=date(2026, 1, 5),
                                                result_code="+")])
    at(service, clock, THU)
    assert open_tasks(service, "PATH.L03") == []
    assert service.snapshot()["flags"]["imported_pending"] == 1  # 화면 배지로만 둔다


# ---------- L04·L05 재검


def followup(service, clock, due: date, chart="T-0710"):
    entry_id = biopsy(service, chart=chart, kind="CLO")
    service.receive(entry_id, "", "+", "")
    service.decide(entry_id, "required", due)
    return entry_id


def test_l04_window_then_l05_on_the_day_then_done(service, clock):
    entry_id = followup(service, clock, date(2026, 12, 20))  # 45일 뒤
    assert open_tasks(service, "PATH.L04") == []
    at(service, clock, kst(2026, 11, 20))  # 30일 전
    [soon] = open_tasks(service, "PATH.L04")
    assert (soon.assignee_role, soon.priority, soon.overdue(clock.now())) == ("ADMIN", "NORMAL", False)

    at(service, clock, kst(2026, 12, 20, 9))  # 재검일 당일
    assert open_tasks(service, "PATH.L04") == []
    [due] = open_tasks(service, "PATH.L05")
    assert (due.priority, due.overdue(clock.now())) == ("HIGH", False)
    at(service, clock, kst(2026, 12, 21, 0, 1))
    assert open_tasks(service, "PATH.L05")[0].overdue(clock.now())

    service.complete_followup(entry_id, date(2026, 12, 21))
    assert open_tasks(service) == []


def test_new_followup_date_opens_a_new_task_and_closes_the_old(service, clock):
    entry_id = followup(service, clock, date(2026, 11, 20))
    [old] = open_tasks(service, "PATH.L04")
    entry = next(e for e in service._store.entries() if e.id == entry_id)
    service._store.write(updated=[replace_entry(entry, clock.now(), followup_due=date(2026, 11, 27))])
    service.tasks.run({entry_id})
    [new] = open_tasks(service, "PATH.L04")
    assert new.id != old.id and new.dedupe_key.endswith("2026-11-27")
    assert next(t for t in service.tasks.store.tasks() if t.id == old.id).status == "AUTO_RESOLVED"


# ---------- 중복 방지·사람이 닫기·재현성


def test_repeated_runs_do_not_add_tasks(service, clock):
    for chart in ("T-0720", "T-0721", "T-0722"):
        biopsy(service, chart=chart)
    followup(service, clock, date(2026, 11, 10), chart="T-0723")
    clock.moment = kst(2026, 11, 12, 16)
    first = service.tasks.run()
    count = len(service.tasks.store.tasks())
    for _ in range(10):
        run = service.tasks.run()
        assert (run.created_count, run.resolved_count, run.status) == (0, 0, "SUCCEEDED")
    assert len(service.tasks.store.tasks()) == count and first.created_count > 0
    assert {r.status for r in service.tasks.store.runs()} == {"SUCCEEDED"}


def test_closed_tasks_are_not_reopened_and_dismiss_needs_a_reason(service, clock):
    followup(service, clock, date(2026, 11, 20))
    [task] = open_tasks(service, "PATH.L04")
    with pytest.raises(ValueError):
        service.tasks.close(task.id, "DISMISSED", "테스트원무", "")
    service.tasks.close(task.id, "DONE", "테스트원무")
    with pytest.raises(TaskClosed):
        service.tasks.close(task.id, "DISMISSED", "테스트원무", "두 번")
    service.tasks.run()
    assert open_tasks(service, "PATH.L04") == []
    done = next(t for t in service.tasks.store.tasks() if t.id == task.id)
    assert (done.status, done.resolved_by) == ("DONE", "테스트원무")


def test_same_clock_gives_the_same_tasks(tmp_path):
    def build():
        clock = MovingClock(THU)
        service = ManualDashboardService(clock=clock)  # 고정 합성 14건
        clock.moment = kst(2026, 11, 12, 16)
        service.tasks.run()
        return sorted((t.rule_id, t.subject_id, t.dedupe_key, t.due_at, t.status) for t in service.tasks.store.tasks())

    first, second = build(), build()
    assert first == second and len(first) > 3


def test_tasks_and_runs_hold_no_names_or_chart_numbers(service, clock):
    biopsy(service, chart="T-0730")
    at(service, clock, kst(2026, 11, 9))
    text = repr(service.tasks.store.tasks()) + repr(service.tasks.store.runs())
    assert "T-0730" not in text and "테스트규칙" not in text


def test_rule_failure_is_recorded_without_breaking_the_write(clock):
    def broken(now):
        raise RuntimeError("합성 실패")

    engine = TaskEngine(MemoryTaskStore(), RuleBook.load(), broken, clock)
    run = engine.run()
    assert (run.status, run.error_code) == ("FAILED", "RuntimeError")
    assert engine.store.runs()[-1].status == "FAILED"


def test_unknown_rule_candidates_are_ignored(clock):
    subject = uuid4()
    engine = TaskEngine(MemoryTaskStore(), RuleBook.load(),
                        lambda now: [Candidate("PATH.X99", "exam", subject, "2026-11-05", now)], clock)
    assert engine.run().created_count == 0


def test_full_run_is_throttled(service, clock):
    service.snapshot()
    runs = len(service.tasks.store.runs())
    clock.moment = THU + timedelta(minutes=4)
    service.snapshot()
    assert len(service.tasks.store.runs()) == runs
    clock.moment = THU + timedelta(minutes=6)
    service.snapshot()
    assert len(service.tasks.store.runs()) == runs + 1


def test_rule_numbers_match_the_dashboard_config():
    book, policy = RuleBook.load(), DashboardPolicy.load()
    assert book.specs["PATH.L02"].params["business_days"] == policy.result_delay_business_days
    assert book.specs["PATH.L02"].params["rut_business_days"] == policy.rut_result_delay_business_days
    assert book.specs["PATH.L04"].params["window_days"] == policy.followup_window_days
