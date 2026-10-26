"""Stage A-2 데이터 이전(0003): 기존 장부 한 줄을 여섯 테이블로 나눠도 값이 그대로다.

합성 장부를 0002 스키마(ledger_entries)에 넣고 upgrade → downgrade → upgrade를 거치며 비교한다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
import pytest
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text

from app.modules.endoscopy_pathology.ledger_db import ConcurrentUpdate, PostgresStore, database_url
from app.modules.endoscopy_pathology.ledger_model import LedgerEntry
from app.modules.endoscopy_pathology.manual_dashboard import ManualDashboardService
from app.modules.endoscopy_pathology.result_notation import Finding
from ledger_helpers import FixedClock

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "0002_auth_access_logs"
NOW = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


@pytest.fixture
def engine():
    engine = create_engine(database_url())
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), BEFORE)
    yield engine
    # 문제 행이 남아 있어도 다음 시험이 깨끗한 head에서 시작하게 한다.
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")
    engine.dispose()


def _revision(engine) -> str:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _legacy_table(engine) -> Table:
    return Table("ledger_entries", MetaData(), autoload_with=engine)


def _legacy_row(entry: LedgerEntry) -> dict:
    """0002까지의 저장 방식(ledger_db._to_row)과 같다."""
    return {
        "id": entry.id, "version": entry.version, "kind": entry.kind, "source": entry.source,
        "chart_no": entry.chart_no, "patient_name": entry.patient_name, "sex": entry.sex, "age": entry.age,
        "exam_date": entry.exam_date, "procedure_type": entry.procedure_type, "specimen_count": entry.specimen_count,
        "site": entry.site, "report_ref": entry.report_ref or None, "registered_by": entry.registered_by,
        "handed_by": entry.handed_by, "received_by": entry.received_by, "handoff_id": entry.handoff_id,
        "entrusted_on": entry.entrusted_on, "reported_on": entry.reported_on,
        "findings": [{"code": f.code, "lesion_count": f.lesion_count, "modifiers": list(f.modifiers),
                      "registered": f.registered} for f in entry.findings],
        "sydney": dict(entry.sydney), "result_code": entry.result_code, "review_codes": list(entry.review_codes),
        "decided_at": entry.decided_at, "followup_due": entry.followup_due,
        "no_followup_reason": entry.no_followup_reason, "followup_done_on": entry.followup_done_on,
        "import_batch_id": entry.import_batch_id, "created_at": entry.created_at, "updated_at": entry.updated_at,
    }


def synthetic_ledger() -> list[LedgerEntry]:
    """모든 단계·종류·결과 형태를 한 번씩 담은 합성 장부. 같은 환자의 여러 검사도 포함한다."""
    day = date(2026, 10, 1)

    def make(number: int, **changes) -> LedgerEntry:
        created = NOW - timedelta(days=40 - number)
        values = dict(id=uuid4(), kind="BIOPSY", chart_no=f"T-{number:04}", patient_name=f"테스트환자{number}",
                      exam_date=day + timedelta(days=number), created_at=created, updated_at=created + timedelta(hours=3),
                      version=number % 3, source="MANUAL", procedure_type="stomach", specimen_count=2,
                      site="합성 위치")
        values.update(changes)
        return LedgerEntry(**values)

    handed = dict(entrusted_on=day, registered_by="테스트 접수", handed_by="테스트 인계", received_by="테스트 인수")
    reported = dict(**handed, report_ref="T9800001", reported_on=day + timedelta(days=2),
                    findings=(Finding("TA", 2, ("L",), True), Finding("ZZ", None, (), False)),
                    sydney=(("h_pylori", "NEG"), ("atrophy", "POS1")), review_codes=("SYDNEY_UNPARSED",))
    decided = dict(decided_at=NOW - timedelta(days=5))
    return [
        make(1),  # 인계 대기
        make(2, **handed),  # 결과 대기
        make(3, **{**reported, "report_ref": "T9800003"}),  # 원장 지시 대기
        make(4, **{**reported, "report_ref": "T9800004"}, **decided, followup_due=date(2027, 10, 1)),  # 재검 예정
        make(5, **{**reported, "report_ref": "T9800005"}, **decided, followup_due=date(2026, 10, 20),
             followup_done_on=date(2026, 10, 21)),  # 재검 완료
        make(6, **{**reported, "report_ref": "T9800006"}, **decided, no_followup_reason="합성 사유"),  # 재검 불필요
        make(7, kind="CLO", procedure_type="stomach", specimen_count=None, site="", sex="F", age=61,
             reported_on=day, result_code="+"),  # CLO 결과
        make(8, kind="STOOL", procedure_type=None, specimen_count=1, sex="M", source="IMPORT",
             review_codes=("RESULT_UNPARSED",)),  # 결과 표기 확인만 있는 가져오기 행
        make(9, chart_no="T-0001", patient_name="테스트환자1", kind="CLO", sex=None),  # 같은 환자의 다른 검사
    ]


def _insert_legacy(engine, ledger: list[LedgerEntry]) -> None:
    table = _legacy_table(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [_legacy_row(e) for e in ledger])


def _legacy_rows(engine) -> list[dict]:
    table = _legacy_table(engine)
    with engine.connect() as connection:
        return sorted((dict(r._mapping) for r in connection.execute(select(table))), key=lambda r: r["id"])


def _by_id(entries) -> dict[UUID, LedgerEntry]:
    # JSONB는 객체 키 순서를 스스로 정한다(이전과 같음). Sydney는 화면에서 dict로만 쓰므로 순서 없이 비교한다.
    return {e.id: replace(e, sydney=tuple(sorted(e.sydney))) for e in entries}


def test_upgrade_downgrade_upgrade_keeps_every_value(engine):
    ledger = synthetic_ledger()
    _insert_legacy(engine, ledger)
    original_rows = _legacy_rows(engine)

    command.upgrade(alembic_config(), "head")
    assert _by_id(PostgresStore(engine).entries()) == _by_id(ledger)
    with engine.connect() as connection:
        patients = connection.execute(text("SELECT count(*) FROM patients")).scalar_one()
        stages = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                  for table in ("exams", "specimens", "exam_results", "doctor_reviews", "followups")}
    assert patients == 8  # T-0001은 검사 2건이지만 환자 1명
    assert stages == {"exams": 9, "specimens": 9, "exam_results": 6, "doctor_reviews": 3, "followups": 2}
    assert "ledger_entries_legacy" in inspect(engine).get_table_names()

    command.downgrade(alembic_config(), BEFORE)
    assert _legacy_rows(engine) == original_rows
    assert not {"patients", "exams", "ledger_entries_legacy"} & set(inspect(engine).get_table_names())

    command.upgrade(alembic_config(), "head")
    assert _by_id(PostgresStore(engine).entries()) == _by_id(ledger)


def test_downgrade_carries_changes_made_after_the_split(engine):
    """분리 뒤 새 테이블에 기록한 원장 지시도 되돌릴 때 장부 한 줄에 들어간다(기록자는 버린다)."""
    ledger = synthetic_ledger()
    _insert_legacy(engine, ledger)
    command.upgrade(alembic_config(), "head")
    service = ManualDashboardService(clock=FixedClock(), store=PostgresStore(engine))
    service.decide(ledger[2].id, "required", date(2028, 1, 2), actor="합성원장")
    assert _by_id(PostgresStore(engine).entries())[ledger[2].id].decided_by == "합성원장"

    command.downgrade(alembic_config(), BEFORE)
    row = next(r for r in _legacy_rows(engine) if r["id"] == ledger[2].id)
    assert row["followup_due"] == date(2028, 1, 2) and row["decided_at"] is not None


@pytest.mark.parametrize(("change", "message"), [
    ({"chart_no": "T-0002", "patient_name": "다른이름"}, "이름이 둘 이상인 차트번호 1건"),
    ({"no_followup_reason": "지시 없이 사유"}, "원장 지시 없이 재검 날짜·사유·완료일이 있는 행 1건"),
    ({"sex": "X"}, "성별이 M·F·빈칸이 아닌 행 1건"),
])
def test_problem_rows_stop_the_migration_without_changes(engine, change, message):
    ledger = synthetic_ledger()
    ledger[0] = LedgerEntry(**{**ledger[0].__dict__, **change})
    _insert_legacy(engine, ledger)
    before = _legacy_rows(engine)

    with pytest.raises(RuntimeError) as error:
        command.upgrade(alembic_config(), "head")
    assert message in str(error.value)
    # 오류에 차트번호·이름을 넣지 않는다.
    assert "T-0001" not in str(error.value) and "다른이름" not in str(error.value)
    assert _revision(engine) == BEFORE
    assert _legacy_rows(engine) == before
    assert "patients" not in inspect(engine).get_table_names()


def test_patient_is_stored_once_and_name_conflicts_are_refused(engine):
    command.upgrade(alembic_config(), "head")
    store = PostgresStore(engine)
    first = synthetic_ledger()[0]
    second = LedgerEntry(**{**first.__dict__, "id": uuid4(), "kind": "CLO", "specimen_count": None})
    store.write(inserted=[first, second])
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(text("patients"))).scalar_one() == 1

    renamed = LedgerEntry(**{**first.__dict__, "id": uuid4(), "patient_name": "다른이름"})
    with pytest.raises(ConcurrentUpdate):
        store.write(inserted=[renamed])
    assert {e.patient_name for e in store.entries()} == {first.patient_name}


def test_decision_and_followup_recorders_are_kept(engine):
    command.upgrade(alembic_config(), "head")
    store = PostgresStore(engine)
    service = ManualDashboardService(clock=FixedClock(), store=store)
    store.write(inserted=synthetic_ledger()[2:4])
    entries = store.entries()
    waiting = next(e for e in entries if e.decided_at is None)
    planned = next(e for e in entries if e.followup_due is not None)
    service.bulk_not_required([waiting.id], "합성 사유", actor="합성원장")
    service.complete_followup(planned.id, date(2026, 11, 1), actor="합성간호")

    saved = _by_id(PostgresStore(engine).entries())
    assert saved[waiting.id].decided_by == "합성원장"
    assert saved[planned.id].followup_done_by == "합성간호"
    assert saved[planned.id].decided_by is None  # 이전 자료처럼 기록자가 없던 지시는 비워 둔다
