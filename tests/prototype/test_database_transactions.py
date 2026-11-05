"""공유 연결·savepoint·요청별 격리와 commit 실패를 실제 시험 DB에서 확인한다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError

from app.kernel.database import connection, on_rollback, transaction
from app.modules.endoscopy_pathology.ledger_db import database_url


@pytest.fixture
def engine():
    engine = create_engine(database_url())
    yield engine
    engine.dispose()


def test_nested_database_error_rolls_back_only_its_savepoint(engine):
    with transaction(engine) as outer:
        with connection(engine) as reader:
            assert reader is outer
        with pytest.raises(DBAPIError):
            with transaction(engine) as nested:
                assert nested is outer
                nested.execute(text("SELECT 1 / 0"))
        assert outer.execute(text("SELECT 1")).scalar_one() == 1


def test_concurrent_work_uses_separate_connections(engine):
    barrier = Barrier(2)

    def worker():
        with transaction(engine) as outer:
            barrier.wait(timeout=10)
            with connection(engine) as reader:
                assert reader is outer
                return reader.execute(text("SELECT pg_backend_pid()")).scalar_one()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        assert len({future.result(timeout=15) for future in futures}) == 2


def test_different_engine_cannot_escape_the_current_transaction(engine):
    other = create_engine(database_url())
    try:
        with transaction(engine):
            with pytest.raises(RuntimeError, match="TRANSACTION_ENGINE_MISMATCH"):
                with transaction(other):
                    pytest.fail("다른 엔진을 열면 안 됩니다")
    finally:
        other.dispose()


def test_rollback_actions_follow_their_savepoint_and_outer_transaction(engine):
    undone = []
    with pytest.raises(ValueError):
        with transaction(engine):
            on_rollback(lambda: undone.append("outer"))
            with pytest.raises(ValueError):
                with transaction(engine):
                    on_rollback(lambda: undone.append("inner"))
                    raise ValueError("SYNTHETIC_INNER_FAILURE")
            assert undone == ["inner"]
            raise ValueError("SYNTHETIC_OUTER_FAILURE")
    assert undone == ["inner", "outer"]


def test_commit_failure_runs_cleanup_and_releases_the_context(engine):
    undone = []

    def fail_commit(connection):
        raise RuntimeError("SYNTHETIC_COMMIT_FAILURE")

    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="SYNTHETIC_COMMIT_FAILURE"):
            with transaction(engine):
                on_rollback(lambda: undone.append("cleanup"))
    finally:
        event.remove(engine, "commit", fail_commit)
    assert undone == ["cleanup"]
    with connection(engine) as reader:
        assert reader.execute(text("SELECT 1")).scalar_one() == 1
