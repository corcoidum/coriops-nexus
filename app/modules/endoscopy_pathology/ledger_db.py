"""장부 저장소. 시연용 메모리 저장소와 PostgreSQL 저장소가 같은 계약을 따른다."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import os
from typing import Iterable, Protocol
from uuid import UUID

from sqlalchemy import (
    CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, MetaData, Table, Text,
    UniqueConstraint, create_engine, insert, select, update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.engine import Engine

from .ledger_model import ExportRecord, Handoff, ImportBatch, LedgerEntry
from .result_notation import Finding


class ConcurrentUpdate(Exception):
    """다른 화면에서 먼저 바꾼 행을 덮어쓰지 않는다."""


def database_url() -> str:
    # 값이 없으면 PGHOST·PGUSER 등 libpq 환경변수로 접속한다. URL·비밀번호를 출력하지 않는다.
    return os.environ.get("CORIOPS_DATABASE_URL") or "postgresql+psycopg://"


metadata = MetaData()


def _timestamps() -> list[Column]:
    return [Column("created_at", DateTime(timezone=True), nullable=False),
            Column("updated_at", DateTime(timezone=True), nullable=False)]


handoffs = Table(
    "ledger_handoffs", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("handed_at", DateTime(timezone=True), nullable=False),
    Column("registered_by", Text, nullable=False),
    Column("handed_by", Text, nullable=False),
    Column("receiver_name", Text, nullable=False),
    Column("specimen_count", Integer, nullable=False),
    Column("case_count", Integer, nullable=False),
    *_timestamps(),
)

import_batches = Table(
    "ledger_import_batches", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("committed_at", DateTime(timezone=True), nullable=False),
    Column("digest", Text, nullable=False, unique=True),
    Column("accepted", Integer, nullable=False),
    Column("skipped", Integer, nullable=False),
    Column("sheet_counts", JSONB, nullable=False),
    *_timestamps(),
)

exports = Table(
    "ledger_exports", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("exported_at", DateTime(timezone=True), nullable=False),
    Column("file_name", Text, nullable=False),
    Column("row_count", Integer, nullable=False),
    *_timestamps(),
)

entries = Table(
    "ledger_entries", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("version", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("chart_no", Text, nullable=False),
    Column("patient_name", Text, nullable=False),
    Column("sex", Text),
    Column("age", Integer),
    Column("exam_date", Date, nullable=False),
    Column("procedure_type", Text),
    Column("specimen_count", Integer),
    Column("site", Text, nullable=False),
    Column("report_ref", Text),
    Column("registered_by", Text, nullable=False),
    Column("handed_by", Text, nullable=False),
    Column("received_by", Text, nullable=False),
    Column("handoff_id", PgUUID(as_uuid=True), ForeignKey("ledger_handoffs.id")),
    Column("entrusted_on", Date),
    Column("reported_on", Date),
    Column("findings", JSONB, nullable=False),
    Column("sydney", JSONB, nullable=False),
    Column("result_code", Text, nullable=False),
    Column("review_codes", JSONB, nullable=False),
    Column("decided_at", DateTime(timezone=True)),
    Column("followup_due", Date),
    Column("no_followup_reason", Text, nullable=False),
    Column("followup_done_on", Date),
    Column("import_batch_id", PgUUID(as_uuid=True), ForeignKey("ledger_import_batches.id")),
    *_timestamps(),
    CheckConstraint("kind IN ('BIOPSY', 'CLO', 'STOOL')", name="ck_ledger_entries_kind"),
    CheckConstraint("source IN ('MANUAL', 'IMPORT', 'SEED')", name="ck_ledger_entries_source"),
    CheckConstraint("procedure_type IS NULL OR procedure_type IN ('stomach', 'colon')",
                    name="ck_ledger_entries_procedure"),
    CheckConstraint("specimen_count IS NULL OR specimen_count BETWEEN 1 AND 99", name="ck_ledger_entries_count"),
    CheckConstraint("followup_due IS NULL OR no_followup_reason = ''", name="ck_ledger_entries_decision"),
    UniqueConstraint("kind", "report_ref", name="uq_ledger_entries_report_ref"),
)


class LedgerStore(Protocol):
    def entries(self) -> list[LedgerEntry]: ...
    def handoffs(self) -> list[Handoff]: ...
    def imports(self) -> list[ImportBatch]: ...
    def exports(self) -> list[ExportRecord]: ...

    def write(self, *, inserted: Iterable[LedgerEntry] = (), updated: Iterable[LedgerEntry] = (),
              handoff: Handoff | None = None, import_batch: ImportBatch | None = None,
              export: ExportRecord | None = None) -> None:
        """한 번의 업무 변경을 원자적으로 저장한다. updated는 version이 1 올라간 값이어야 한다."""


class MemoryStore:
    """시연·단위시험용. 프로세스가 끝나면 사라진다."""

    persistent = False

    def __init__(self) -> None:
        self._entries: dict[UUID, LedgerEntry] = {}
        self._handoffs: list[Handoff] = []
        self._imports: list[ImportBatch] = []
        self._exports: list[ExportRecord] = []

    def entries(self) -> list[LedgerEntry]:
        return list(self._entries.values())

    def handoffs(self) -> list[Handoff]:
        return list(self._handoffs)

    def imports(self) -> list[ImportBatch]:
        return list(self._imports)

    def exports(self) -> list[ExportRecord]:
        return list(self._exports)

    def write(self, *, inserted=(), updated=(), handoff=None, import_batch=None, export=None) -> None:
        inserted, updated = list(inserted), list(updated)
        for entry in updated:
            current = self._entries.get(entry.id)
            if current is None or current.version != entry.version - 1:
                raise ConcurrentUpdate()
        refs = {(e.kind, e.report_ref) for e in self._entries.values() if e.report_ref}
        for entry in inserted:
            if entry.id in self._entries or (entry.report_ref and (entry.kind, entry.report_ref) in refs):
                raise ConcurrentUpdate()
        if import_batch and any(b.digest == import_batch.digest for b in self._imports):
            raise ConcurrentUpdate()
        # 검사를 모두 통과한 뒤에만 반영해 일부만 저장되는 일을 막는다.
        for entry in [*inserted, *updated]:
            self._entries[entry.id] = entry
        if handoff:
            self._handoffs.append(handoff)
        if import_batch:
            self._imports.append(import_batch)
        if export:
            self._exports.append(export)

    def replace_all(self, seed: Iterable[LedgerEntry]) -> None:
        self.__init__()
        self._entries = {entry.id: entry for entry in seed}


def _to_row(entry: LedgerEntry) -> dict:
    return {
        "id": entry.id, "version": entry.version, "kind": entry.kind, "source": entry.source,
        "chart_no": entry.chart_no, "patient_name": entry.patient_name, "sex": entry.sex,
        "age": entry.age, "exam_date": entry.exam_date, "procedure_type": entry.procedure_type,
        "specimen_count": entry.specimen_count, "site": entry.site, "report_ref": entry.report_ref or None,
        "registered_by": entry.registered_by, "handed_by": entry.handed_by, "received_by": entry.received_by,
        "handoff_id": entry.handoff_id, "entrusted_on": entry.entrusted_on, "reported_on": entry.reported_on,
        "findings": [
            {"code": f.code, "lesion_count": f.lesion_count, "modifiers": list(f.modifiers), "registered": f.registered}
            for f in entry.findings
        ],
        "sydney": dict(entry.sydney), "result_code": entry.result_code,
        "review_codes": list(entry.review_codes), "decided_at": entry.decided_at,
        "followup_due": entry.followup_due, "no_followup_reason": entry.no_followup_reason,
        "followup_done_on": entry.followup_done_on, "import_batch_id": entry.import_batch_id,
        "created_at": entry.created_at, "updated_at": entry.updated_at,
    }


def _from_row(row) -> LedgerEntry:
    data = dict(row._mapping)
    data["findings"] = tuple(
        Finding(f["code"], f["lesion_count"], tuple(f["modifiers"]), f["registered"]) for f in data["findings"]
    )
    data["sydney"] = tuple(data["sydney"].items())
    data["review_codes"] = tuple(data["review_codes"])
    data["report_ref"] = data["report_ref"] or ""
    return LedgerEntry(**data)


class PostgresStore:
    """PostgreSQL 16 저장소. 스키마는 Alembic(migrations/)으로만 만든다."""

    persistent = True

    def __init__(self, engine: Engine | None = None):
        self._engine = engine or create_engine(database_url(), pool_pre_ping=True)

    def entries(self) -> list[LedgerEntry]:
        with self._engine.connect() as connection:
            return [_from_row(row) for row in connection.execute(select(entries))]

    def handoffs(self) -> list[Handoff]:
        columns = [handoffs.c[name] for name in ("id", "handed_at", "registered_by", "handed_by",
                                                 "receiver_name", "specimen_count", "case_count")]
        with self._engine.connect() as connection:
            return [Handoff(*row) for row in connection.execute(select(*columns).order_by(handoffs.c.handed_at))]

    def imports(self) -> list[ImportBatch]:
        columns = [import_batches.c[name] for name in ("id", "committed_at", "digest", "accepted",
                                                       "skipped", "sheet_counts")]
        with self._engine.connect() as connection:
            return [ImportBatch(*row) for row in connection.execute(
                select(*columns).order_by(import_batches.c.committed_at))]

    def exports(self) -> list[ExportRecord]:
        columns = [exports.c[name] for name in ("id", "exported_at", "file_name", "row_count")]
        with self._engine.connect() as connection:
            return [ExportRecord(*row) for row in connection.execute(
                select(*columns).order_by(exports.c.exported_at))]

    def write(self, *, inserted=(), updated=(), handoff=None, import_batch=None, export=None) -> None:
        from sqlalchemy.exc import IntegrityError

        try:
            with self._engine.begin() as connection:
                if handoff:
                    connection.execute(insert(handoffs).values(
                        id=handoff.id, handed_at=handoff.handed_at, registered_by=handoff.registered_by,
                        handed_by=handoff.handed_by, receiver_name=handoff.receiver_name,
                        specimen_count=handoff.specimen_count, case_count=handoff.case_count,
                        created_at=handoff.handed_at, updated_at=handoff.handed_at))
                if import_batch:
                    connection.execute(insert(import_batches).values(
                        id=import_batch.id, committed_at=import_batch.committed_at, digest=import_batch.digest,
                        accepted=import_batch.accepted, skipped=import_batch.skipped,
                        sheet_counts=import_batch.sheet_counts,
                        created_at=import_batch.committed_at, updated_at=import_batch.committed_at))
                if export:
                    connection.execute(insert(exports).values(
                        id=export.id, exported_at=export.exported_at, file_name=export.file_name,
                        row_count=export.row_count, created_at=export.exported_at, updated_at=export.exported_at))
                rows = [_to_row(entry) for entry in inserted]
                if rows:
                    connection.execute(insert(entries), rows)
                for entry in updated:
                    # version이 다르면 다른 화면에서 먼저 바꾼 것이다. 전체 변경을 되돌린다.
                    result = connection.execute(
                        update(entries)
                        .where(entries.c.id == entry.id, entries.c.version == entry.version - 1)
                        .values(**{k: v for k, v in _to_row(entry).items() if k != "id"}))
                    if result.rowcount != 1:
                        raise ConcurrentUpdate()
        except IntegrityError:
            # 제약 위반 메시지에는 입력값이 들어 있을 수 있어 그대로 보여주지 않는다.
            raise ConcurrentUpdate() from None


def replace_entry(entry: LedgerEntry, now: datetime, **changes) -> LedgerEntry:
    """변경본은 항상 version을 올린다."""
    return replace(entry, version=entry.version + 1, updated_at=now, **changes)
