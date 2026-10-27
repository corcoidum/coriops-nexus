"""동일 업무 안의 저장소·접속기록이 DB 연결과 commit/rollback을 공유한다."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy.engine import Connection, Engine


@dataclass
class _Transaction:
    engine: Engine
    connection: Connection
    rollback_actions: list[Callable[[], None]] = field(default_factory=list)


_current: ContextVar[_Transaction | None] = ContextVar("database_transaction", default=None)


def _bound(engine: Engine) -> _Transaction | None:
    current = _current.get()
    if current is not None and current.engine is not engine:
        raise RuntimeError("TRANSACTION_ENGINE_MISMATCH")
    return current


def on_rollback(action: Callable[[], None]) -> None:
    """DB와 함께 되돌려야 하는 이번 업무의 부수 효과만 등록한다."""
    current = _current.get()
    if current is not None:
        current.rollback_actions.append(action)


def _undo(current: _Transaction, start: int = 0) -> None:
    actions = current.rollback_actions[start:]
    del current.rollback_actions[start:]
    for action in reversed(actions):
        action()


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    current = _bound(engine)
    if current is not None:
        start = len(current.rollback_actions)
        try:
            # 규칙 실행 등에서 잡은 DB 오류가 바깥 업무까지 무효화하지 않도록 savepoint를 둔다.
            with current.connection.begin_nested():
                yield current.connection
        except BaseException:
            _undo(current, start)
            raise
        return
    current = None
    try:
        with engine.begin() as connection:
            current = _Transaction(engine, connection)
            token = _current.set(current)
            try:
                yield connection
            finally:
                _current.reset(token)
    except BaseException:
        if current is not None:
            _undo(current)
        raise


@contextmanager
def connection(engine: Engine) -> Iterator[Connection]:
    current = _bound(engine)
    if current is not None:
        yield current.connection
    else:
        with engine.connect() as connected:
            yield connected
