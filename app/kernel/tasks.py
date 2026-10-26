"""규칙 실행기와 할 일(Task). 커널 소유이며 업무 모듈을 알지 못한다(Stage B, A17).

- 업무 모듈은 `evaluate(now) -> list[Candidate]`만 준다. 저장·중복 방지·자동 해소·실행 기록은 여기서 한다.
- 같은 규칙·같은 대상·같은 기준(anchor)은 한 번만 저장한다. 사람이 닫은 할 일은 조건이 남아도 다시 만들지 않는다.
- 제목은 config의 고정 문구만 쓴다. 이름·차트번호·결과를 할 일과 실행 기록에 넣지 않는다.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
import json
import logging
from pathlib import Path
from threading import RLock
from typing import Callable, Iterable, Iterator, Protocol
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, MetaData, Table, Text, insert, select, text, update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.engine import Engine
import yaml

from .clock import Clock, SystemClock


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "rules.yaml"
LOCK_KEY = 7_340_012  # 규칙 실행 전용 advisory lock 번호(접속기록 7_340_011과 다름)
STATUSES = ("OPEN", "DONE", "DISMISSED", "AUTO_RESOLVED")
PRIORITIES = ("NORMAL", "HIGH", "URGENT")
ROLES = ("DOCTOR", "ADMIN", "NURSE", "PRIVACY_OFFICER")
RESOLUTION_NOTE_MAX = 120
logger = logging.getLogger(__name__)

metadata = MetaData()


def _timestamps() -> list[Column]:
    return [Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False)]


def _in(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


rules = Table(
    "rules", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("rule_id", Text, nullable=False, unique=True),
    Column("params", JSONB, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("config_hash", Text, nullable=False),
    *_timestamps(),
)

rule_runs = Table(
    "rule_runs", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("evaluated_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("scope", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("config_hash", Text, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("created_count", Integer, nullable=False),
    Column("resolved_count", Integer, nullable=False),
    Column("error_code", Text),
    *_timestamps(),
    CheckConstraint(_in("scope", ("ALL", "SUBJECTS")), name="ck_rule_runs_scope"),
    CheckConstraint(_in("status", ("SUCCEEDED", "FAILED")), name="ck_rule_runs_status"),
    Index("ix_rule_runs_scope_evaluated", "scope", "evaluated_at"),
)

tasks = Table(
    "tasks", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("rule_id", PgUUID(as_uuid=True), ForeignKey("rules.id"), nullable=False),
    Column("run_id", PgUUID(as_uuid=True), ForeignKey("rule_runs.id"), nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", PgUUID(as_uuid=True), nullable=False, index=True),
    Column("dedupe_key", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("priority", Text, nullable=False),
    Column("assignee_role", Text, nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("due_at", DateTime(timezone=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    Column("resolved_by", Text),
    Column("resolution_note", Text, nullable=False),
    *_timestamps(),
    CheckConstraint(_in("status", STATUSES), name="ck_tasks_status"),
    CheckConstraint(_in("priority", PRIORITIES), name="ck_tasks_priority"),
    CheckConstraint(_in("assignee_role", ROLES), name="ck_tasks_assignee_role"),
    CheckConstraint("(status = 'OPEN') = (resolved_at IS NULL)", name="ck_tasks_resolution"),
    Index("ix_tasks_open_due", "status", "due_at"),
)


# ---------- 설정


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    name: str
    title: str
    assignee_role: str
    priority: str
    params: dict


@dataclass(frozen=True)
class RuleBook:
    specs: dict[str, RuleSpec]
    full_run_interval: timedelta
    done_window_days: int
    config_hash: str

    @classmethod
    def load(cls, path: Path | None = None) -> RuleBook:
        source = (path or DEFAULT_CONFIG).read_bytes()
        raw = yaml.safe_load(source)
        specs = {}
        for rule_id, spec in raw["rules"].items():
            if spec["assignee_role"] not in ROLES or spec["priority"] not in PRIORITIES:
                raise ValueError(f"규칙 설정 오류: {rule_id}")
            specs[rule_id] = RuleSpec(rule_id, spec["name"], spec["title"], spec["assignee_role"], spec["priority"],
                                      dict(spec.get("params") or {}))
        engine = raw["engine"]
        return cls(specs, timedelta(minutes=engine["full_run_interval_minutes"]),
                   engine["dashboard_done_window_days"], sha256(source).hexdigest())


# ---------- 값


@dataclass(frozen=True)
class Candidate:
    """규칙이 찾은 '지금 할 일이 있어야 하는' 대상. anchor는 회차(같은 대상의 다른 기준날짜를 구분)다."""

    rule_id: str
    subject_type: str
    subject_id: UUID
    anchor: str
    due_at: datetime

    @property
    def dedupe_key(self) -> str:
        return f"{self.rule_id}:{self.subject_type}:{self.subject_id}:{self.anchor}"


@dataclass(frozen=True)
class Task:
    id: UUID
    rule_id: str
    run_id: UUID
    subject_type: str
    subject_id: UUID
    dedupe_key: str
    title: str
    priority: str
    assignee_role: str
    opened_at: datetime
    due_at: datetime
    status: str = "OPEN"
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str = ""

    def overdue(self, now: datetime) -> bool:
        return self.status == "OPEN" and now > self.due_at


@dataclass(frozen=True)
class RuleRun:
    id: UUID
    evaluated_at: datetime
    finished_at: datetime
    scope: str
    status: str
    config_hash: str
    candidate_count: int = 0
    created_count: int = 0
    resolved_count: int = 0
    error_code: str | None = None


class TaskClosed(Exception):
    """이미 닫힌 할 일. 다른 화면에서 먼저 닫았다."""


# ---------- 저장소


class TaskTx(Protocol):
    def existing_keys(self, keys: set[str]) -> set[str]: ...
    def open_tasks(self, subjects: set[UUID] | None) -> list[Task]: ...
    def insert(self, new: list[Task]) -> None: ...
    def auto_resolve(self, ids: list[UUID], at: datetime) -> None: ...
    def record_run(self, run: RuleRun) -> None: ...


class TaskStore(Protocol):
    def sync_rules(self, book: RuleBook, now: datetime) -> None: ...
    @contextmanager
    def locked(self) -> Iterator[TaskTx]: ...
    def tasks(self) -> list[Task]: ...
    def runs(self) -> list[RuleRun]: ...
    def last_full_run(self) -> datetime | None: ...
    def close(self, task_id: UUID, status: str, by: str, note: str, at: datetime) -> Task: ...


class _MemoryTx:
    def __init__(self, store: MemoryTaskStore):
        self._store = store
        self._new: list[Task] = []
        self._resolved: list[tuple[UUID, datetime]] = []
        self._run: RuleRun | None = None

    def existing_keys(self, keys):
        return {t.dedupe_key for t in self._store._tasks.values()} & keys

    def open_tasks(self, subjects):
        return [t for t in self._store._tasks.values()
                if t.status == "OPEN" and (subjects is None or t.subject_id in subjects)]

    def insert(self, new):
        self._new.extend(new)

    def auto_resolve(self, ids, at):
        self._resolved.extend((i, at) for i in ids)

    def record_run(self, run):
        self._run = run

    def commit(self):
        for task_id, at in self._resolved:
            self._store._tasks[task_id] = replace(self._store._tasks[task_id], status="AUTO_RESOLVED", resolved_at=at)
        for task in self._new:
            self._store._tasks[task.id] = task
        if self._run:
            self._store._runs.append(self._run)


class MemoryTaskStore:
    """시연·단위시험용."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}
        self._runs: list[RuleRun] = []
        self._lock = RLock()

    def sync_rules(self, book, now):
        return None

    @contextmanager
    def locked(self):
        with self._lock:
            tx = _MemoryTx(self)
            yield tx
            tx.commit()

    def tasks(self):
        return list(self._tasks.values())

    def runs(self):
        return list(self._runs)

    def last_full_run(self):
        return max((r.evaluated_at for r in self._runs if r.scope == "ALL"), default=None)

    def close(self, task_id, status, by, note, at):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status != "OPEN":
                raise TaskClosed()
            self._tasks[task_id] = replace(task, status=status, resolved_at=at, resolved_by=by, resolution_note=note)
            return self._tasks[task_id]

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._runs.clear()


_TASK_COLUMNS = (tasks.c.id, rules.c.rule_id, tasks.c.run_id, tasks.c.subject_type, tasks.c.subject_id,
                 tasks.c.dedupe_key, tasks.c.title, tasks.c.priority, tasks.c.assignee_role, tasks.c.opened_at,
                 tasks.c.due_at, tasks.c.status, tasks.c.resolved_at, tasks.c.resolved_by, tasks.c.resolution_note)


def _task_query():
    return select(*_TASK_COLUMNS).select_from(tasks.join(rules, rules.c.id == tasks.c.rule_id))


class _PostgresTx:
    def __init__(self, connection, rule_ids: dict[str, UUID]):
        self._c = connection
        self._rule_ids = rule_ids

    def existing_keys(self, keys):
        if not keys:
            return set()
        return set(self._c.execute(select(tasks.c.dedupe_key).where(tasks.c.dedupe_key.in_(keys))).scalars())

    def open_tasks(self, subjects):
        query = _task_query().where(tasks.c.status == "OPEN")
        if subjects is not None:
            query = query.where(tasks.c.subject_id.in_(subjects))
        return [Task(*row) for row in self._c.execute(query)]

    def insert(self, new):
        if new:
            self._c.execute(insert(tasks), [{
                "id": t.id, "rule_id": self._rule_ids[t.rule_id], "run_id": t.run_id, "subject_type": t.subject_type,
                "subject_id": t.subject_id, "dedupe_key": t.dedupe_key, "title": t.title, "priority": t.priority,
                "assignee_role": t.assignee_role, "opened_at": t.opened_at, "due_at": t.due_at, "status": t.status,
                "resolved_at": None, "resolved_by": None, "resolution_note": "", "created_at": t.opened_at,
                "updated_at": t.opened_at} for t in new])

    def auto_resolve(self, ids, at):
        if ids:
            self._c.execute(update(tasks).where(tasks.c.id.in_(ids), tasks.c.status == "OPEN")
                            .values(status="AUTO_RESOLVED", resolved_at=at, updated_at=at))

    def record_run(self, run):
        self._c.execute(insert(rule_runs).values(
            id=run.id, evaluated_at=run.evaluated_at, finished_at=run.finished_at, scope=run.scope, status=run.status,
            config_hash=run.config_hash, candidate_count=run.candidate_count, created_count=run.created_count,
            resolved_count=run.resolved_count, error_code=run.error_code, created_at=run.finished_at,
            updated_at=run.finished_at))


class PostgresTaskStore:
    """PostgreSQL 16. 실행 하나는 한 트랜잭션이고, 동시에 두 실행이 섞이지 않게 advisory lock을 건다."""

    def __init__(self, engine: Engine):
        self._engine = engine
        self._rule_ids: dict[str, UUID] = {}

    def sync_rules(self, book, now):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
            stored = {row.rule_id: row for row in connection.execute(select(rules))}
            for rule_id, spec in book.specs.items():
                params = json.loads(json.dumps(spec.params))
                if rule_id in stored:
                    connection.execute(update(rules).where(rules.c.rule_id == rule_id).values(
                        params=params, enabled=True, config_hash=book.config_hash, updated_at=now))
                else:
                    connection.execute(insert(rules).values(
                        id=uuid4(), rule_id=rule_id, params=params, enabled=True, config_hash=book.config_hash,
                        created_at=now, updated_at=now))
            # 설정에서 빠진 규칙은 지우지 않고 끈다(기존 할 일의 출처를 남긴다).
            for rule_id in set(stored) - set(book.specs):
                connection.execute(update(rules).where(rules.c.rule_id == rule_id).values(enabled=False, updated_at=now))
            self._rule_ids = {row.rule_id: row.id for row in connection.execute(select(rules.c.rule_id, rules.c.id))}

    @contextmanager
    def locked(self):
        with self._engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
            yield _PostgresTx(connection, self._rule_ids)

    def tasks(self):
        with self._engine.connect() as connection:
            return [Task(*row) for row in connection.execute(_task_query().order_by(tasks.c.due_at))]

    def runs(self):
        columns = [rule_runs.c[name] for name in ("id", "evaluated_at", "finished_at", "scope", "status",
                                                  "config_hash", "candidate_count", "created_count",
                                                  "resolved_count", "error_code")]
        with self._engine.connect() as connection:
            return [RuleRun(*row) for row in connection.execute(select(*columns).order_by(rule_runs.c.evaluated_at))]

    def last_full_run(self):
        with self._engine.connect() as connection:
            return connection.execute(select(rule_runs.c.evaluated_at).where(rule_runs.c.scope == "ALL")
                                      .order_by(rule_runs.c.evaluated_at.desc()).limit(1)).scalar()

    def close(self, task_id, status, by, note, at):
        with self._engine.begin() as connection:
            result = connection.execute(update(tasks).where(tasks.c.id == task_id, tasks.c.status == "OPEN").values(
                status=status, resolved_at=at, resolved_by=by, resolution_note=note, updated_at=at))
            if result.rowcount != 1:
                raise TaskClosed()
            return Task(*connection.execute(_task_query().where(tasks.c.id == task_id)).one())


# ---------- 실행기


class TaskEngine:
    def __init__(self, store: TaskStore, book: RuleBook, evaluate: Callable[[datetime], list[Candidate]],
                 clock: Clock | None = None):
        self.store = store
        self.book = book
        self._evaluate = evaluate
        self._clock = clock or SystemClock()
        self._synced = False

    def _sync(self, now: datetime) -> None:
        if not self._synced:
            self.store.sync_rules(self.book, now)
            self._synced = True

    def run(self, subjects: set[UUID] | None = None) -> RuleRun:
        """규칙을 돌려 할 일을 맞춘다. subjects를 주면 그 대상만 열고 닫는다(업무 기록 직후)."""
        now = self._clock.now()
        self._sync(now)
        scope = "ALL" if subjects is None else "SUBJECTS"
        try:
            candidates = [c for c in self._evaluate(now) if c.rule_id in self.book.specs]
            if subjects is not None:
                candidates = [c for c in candidates if c.subject_id in subjects]
            run_id = uuid4()
            wanted = {c.dedupe_key: c for c in candidates}
            with self.store.locked() as tx:
                # 조건이 풀린 열린 할 일은 저절로 닫는다.
                stale = [t.id for t in tx.open_tasks(subjects) if t.dedupe_key not in wanted]
                # 처음 보는 키만 만든다. 이미 있던 키(열림·닫힘 모두)는 다시 만들지 않는다.
                known = tx.existing_keys(set(wanted))
                new = [self._task(c, run_id, now) for key, c in wanted.items() if key not in known]
                run = RuleRun(run_id, now, self._clock.now(), scope, "SUCCEEDED", self.book.config_hash,
                              len(candidates), len(new), len(stale))
                # 할 일이 출처(실행 기록)를 가리키므로 실행 기록을 먼저 저장한다.
                tx.record_run(run)
                tx.auto_resolve(stale, now)
                tx.insert(new)
            return run
        except Exception as error:  # 업무 기록은 이미 끝났다. 실패를 실행 기록에 남기고 화면은 계속 쓴다.
            # DB 오류 문구에는 입력값이 섞일 수 있어 예외 종류만 남긴다.
            logger.error("규칙 실행 실패: %s", type(error).__name__)
            run = RuleRun(uuid4(), now, self._clock.now(), scope, "FAILED", self.book.config_hash,
                          error_code=type(error).__name__)
            try:
                with self.store.locked() as tx:
                    tx.record_run(run)
            except Exception:  # DB 자체가 안 되면 기록도 못 한다. 업무 화면은 막지 않는다.
                pass
            return run

    def run_if_stale(self) -> RuleRun | None:
        last = self.store.last_full_run()
        if last is not None and self._clock.now() - last < self.book.full_run_interval:
            return None
        return self.run()

    def close(self, task_id: UUID, status: str, by: str, note: str = "") -> Task:
        """사람이 닫는다. DONE(확인 완료) 또는 DISMISSED(해당 없음, 사유 필수)."""
        note = note.strip()
        if status not in ("DONE", "DISMISSED"):
            raise ValueError("닫기 상태 오류")
        if status == "DISMISSED" and not note:
            raise ValueError("해당 없음 사유를 입력해 주세요.")
        if len(note) > RESOLUTION_NOTE_MAX:
            raise ValueError(f"사유는 {RESOLUTION_NOTE_MAX}자 이내로 입력해 주세요.")
        return self.store.close(task_id, status, by, note, self._clock.now())

    def _task(self, candidate: Candidate, run_id: UUID, now: datetime) -> Task:
        spec = self.book.specs[candidate.rule_id]
        return Task(uuid4(), spec.rule_id, run_id, candidate.subject_type, candidate.subject_id,
                    candidate.dedupe_key, spec.title, spec.priority, spec.assignee_role, now, candidate.due_at)
