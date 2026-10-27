"""PostgreSQL 16의 규칙·할 일 저장소(0004). 메모리 저장소와 같은 결과, 제약, 규칙 동기화를 본다."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.kernel.tasks import PostgresTaskStore, RuleBook, TaskClosed
from app.modules.endoscopy_pathology.ledger_db import PostgresStore, database_url
from app.modules.endoscopy_pathology.ledger_model import KST
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("tasks", "rule_runs", "rules", "followups", "doctor_reviews", "exam_results", "specimens", "exams",
          "patients", "ledger_exports", "ledger_import_batches", "ledger_handoffs")


class MovingClock:
    def __init__(self, moment: datetime):
        self.moment = moment

    def now(self) -> datetime:
        return self.moment.astimezone(timezone.utc)


@pytest.fixture(scope="module")
def engine():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")
    engine = create_engine(database_url())
    yield engine
    engine.dispose()


@pytest.fixture
def clock():
    return MovingClock(datetime(2026, 11, 5, 10, tzinfo=KST))


@pytest.fixture
def service(engine, clock):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE"))
    return ManualDashboardService(clock=clock, store=PostgresStore(engine), task_store=PostgresTaskStore(engine))


def resulted(service, chart):
    """조직검사 1건을 원장 지시 대기까지. CLO는 결과를 기록하면 종결해 쓰지 않는다(A27)."""
    entry_id = service.register("BIOPSY", chart, "테스트디비", date(2026, 11, 5), procedure_type="stomach",
                                specimen_count="1")
    service.handoff("테스트 접수", "테스트 인계", "테스트 수령", 1)
    service.receive(entry_id, f"R{chart[2:]}", "TA#1(L)", "합성 위치")
    return entry_id


def test_tasks_open_close_and_stay_unique_in_postgres(service, clock, engine):
    entry_id = service.register("BIOPSY", "T-0801", "테스트디비", date(2026, 11, 5), procedure_type="colon",
                                specimen_count="2")
    clock.moment = datetime(2026, 11, 5, 15, 1, tzinfo=KST)
    service.tasks.run()
    for _ in range(3):
        assert service.tasks.run().created_count == 0
    [task] = [t for t in service.tasks.store.tasks() if t.status == "OPEN"]
    assert (task.rule_id, task.subject_id, task.title) == ("PATH.L01", entry_id, "검체 인계 확인")

    service.handoff("테스트 접수", "테스트 인계", "테스트 수령", 2)
    assert [t.status for t in service.tasks.store.tasks()] == ["AUTO_RESOLVED"]
    with engine.connect() as connection:
        rules = dict(connection.execute(text("SELECT rule_id, enabled FROM rules")).all())
        scopes = [row[0] for row in connection.execute(text("SELECT scope FROM rule_runs ORDER BY evaluated_at"))]
    assert set(rules) == set(RuleBook.load().specs) and all(rules.values())
    assert "ALL" in scopes and "SUBJECTS" in scopes
    # 실패는 업무 화면을 막지 않고 기록만 하므로, 실패가 하나도 없는지 따로 본다.
    assert {r.status for r in service.tasks.store.runs()} == {"SUCCEEDED"}


def test_people_close_tasks_once_in_postgres(service, clock):
    resulted(service, "T-0802")
    [task] = [t for t in service.tasks.store.tasks() if t.rule_id == "PATH.L03"]
    closed = service.tasks.close(task.id, "DISMISSED", "테스트원장", "합성 사유")
    assert (closed.status, closed.resolved_by, closed.resolution_note) == ("DISMISSED", "테스트원장", "합성 사유")
    with pytest.raises(TaskClosed):
        service.tasks.close(task.id, "DONE", "테스트원장")
    service.tasks.run()
    assert [t.status for t in service.tasks.store.tasks() if t.rule_id == "PATH.L03"] == ["DISMISSED"]


def test_removed_rules_are_disabled_not_deleted(service, engine, clock, tmp_path):
    service.tasks.run()
    config = (ROOT / "config" / "rules.yaml").read_text(encoding="utf-8")
    trimmed = config.split("  PATH.L05:")[0]
    (tmp_path / "rules.yaml").write_text(trimmed, encoding="utf-8")
    other = ManualDashboardService(clock=clock, store=PostgresStore(engine), task_store=PostgresTaskStore(engine),
                                   rulebook=RuleBook.load(tmp_path / "rules.yaml"))
    other.tasks.run()
    with engine.connect() as connection:
        enabled = dict(connection.execute(text("SELECT rule_id, enabled FROM rules")).all())
    assert enabled["PATH.L05"] is False and enabled["PATH.L01"] is True


@pytest.mark.parametrize("sql", [
    "UPDATE tasks SET status = 'LATER'",
    "UPDATE tasks SET priority = 'LOW'",
    "UPDATE tasks SET assignee_role = 'SEEGENE'",
    "UPDATE tasks SET resolved_at = now()",  # OPEN인데 처리 시각이 있으면 거부
])
def test_task_constraints(service, engine, sql):
    resulted(service, "T-0803")
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(sql))
