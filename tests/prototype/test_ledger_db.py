"""PostgreSQL 16 저장소와 Alembic 스키마. 메모리 시연과 같은 업무 규칙이 DB에서도 지켜지는지 확인한다."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.kernel.patients import metadata as patient_metadata
from app.modules.endoscopy_pathology.ledger_db import (
    ConcurrentUpdate, PostgresStore, database_url, metadata, replace_entry,
)
from app.modules.endoscopy_pathology.ledger_model import LedgerEntry
from app.modules.endoscopy_pathology.manual_dashboard import DashboardError, ManualDashboardService
from app.modules.endoscopy_pathology.result_notation import ResultCodeBook
from ledger_helpers import FixedClock, standard_workbook

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("followups", "doctor_reviews", "exam_results", "specimens", "exams", "patients", "ledger_exports",
          "ledger_import_batches", "ledger_handoffs")


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


@pytest.fixture(scope="module")
def engine():
    engine = create_engine(database_url())
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def store(engine):
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE " + ", ".join(TABLES) + " CASCADE"))
    return PostgresStore(engine)


def entry(**changes) -> LedgerEntry:
    now = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)
    values = dict(id=uuid4(), kind="BIOPSY", chart_no="T-9001", patient_name="테스트환자", exam_date=date(2026, 11, 5),
                  created_at=now, updated_at=now, procedure_type="stomach", specimen_count=1)
    values.update(changes)
    return LedgerEntry(**values)


def test_migration_runs_up_down_up_and_matches_the_code_schema(engine):
    command.downgrade(alembic_config(), "base")
    assert not set(TABLES) & set(inspect(engine).get_table_names())
    command.upgrade(alembic_config(), "head")
    inspector = inspect(engine)
    for table in [*patient_metadata.sorted_tables, *metadata.sorted_tables]:
        columns = {c["name"]: c for c in inspector.get_columns(table.name)}
        assert set(columns) == set(table.columns.keys()), table.name
        assert all(columns[c.name]["nullable"] == c.nullable for c in table.columns), table.name
        assert "created_at" in columns and "updated_at" in columns
        assert str(columns["id"]["type"]) == "UUID"


def test_entry_round_trips_with_structured_results(store):
    book = ResultCodeBook.load()
    original = entry(findings=book.parse_findings("TA#2(L), ZZ#1"), sydney=tuple(book.parse_sydney("HP-/IM+").items()),
                     review_codes=("SYDNEY_UNPARSED",), report_ref="T9700001", site="합성 위치")

    store.write(inserted=[original])

    assert store.entries() == [original]


def test_stale_version_rolls_back_the_whole_change(store):
    first, second = entry(), entry(chart_no="T-9002")
    store.write(inserted=[first, second])
    now = datetime(2026, 11, 5, 2, 0, tzinfo=timezone.utc)
    good = replace_entry(first, now, site="바뀐 위치")
    stale = replace_entry(replace_entry(second, now), now, site="오래된 화면")

    with pytest.raises(ConcurrentUpdate):
        store.write(updated=[good, stale])

    assert {e.site for e in store.entries()} == {""}
    assert {e.version for e in store.entries()} == {0}


def test_duplicate_report_reference_is_rejected(store):
    store.write(inserted=[entry(report_ref="T9700001")])

    with pytest.raises(ConcurrentUpdate):
        store.write(inserted=[entry(chart_no="T-9003", report_ref="T9700001")])
    assert len(store.entries()) == 1


@pytest.mark.parametrize("sql", [
    "UPDATE exams SET kind = 'LAB'",
    "UPDATE exams SET procedure_type = 'knee'",
    "UPDATE exams SET sex = 'X'",
    "UPDATE specimens SET specimen_count = 0",
    "INSERT INTO patients (id, chart_no, name, created_at, updated_at) "
    "SELECT gen_random_uuid(), chart_no, '다른이름', now(), now() FROM patients",
    # 원장 지시 없는 재검 계획은 FK가 막는다.
    "INSERT INTO followups (id, review_id, due_on, created_at, updated_at) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), '2030-01-01', now(), now())",
])
def test_database_checks_reject_invalid_values(store, engine, sql):
    store.write(inserted=[entry()])
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(sql))


def test_service_flow_persists_across_service_instances(store, tmp_path):
    clock = FixedClock()
    service = ManualDashboardService(clock=clock, store=store, export_dir=tmp_path)
    entry_id = service.register("BIOPSY", "T-9100", "테스트환자", date(2026, 11, 5), procedure_type="colon",
                                specimen_count="2")
    service.handoff("테스트 접수자", "테스트 인계자", "테스트 수령인", 2)
    service.receive(entry_id, "T9700100", "TA#2(L)", "합성 위치")
    service.decide(entry_id, "required", date(2029, 11, 5))
    service.export()

    reopened = ManualDashboardService(clock=clock, store=PostgresStore(store._engine), export_dir=tmp_path)
    snapshot = reopened.snapshot()
    assert snapshot["stages"][entry_id] == "FOLLOWUP"
    assert snapshot["pickup"]["handed_today"][0].receiver_name == "테스트 수령인"
    assert len(snapshot["exports"]) == 1
    assert reopened.persistent is True


def test_import_into_postgres_and_reset_is_refused(store):
    service = ManualDashboardService(clock=FixedClock(), store=store)
    assert service.commit_import(service.preview_import(standard_workbook())) == 7
    assert len(store.imports()) == 1

    with pytest.raises(DashboardError) as error:
        service.reset()
    assert error.value.status_code == 403
    assert len(store.entries()) == 7
