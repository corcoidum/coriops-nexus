"""장부 저장소. 시연용 메모리 저장소와 PostgreSQL 저장소가 같은 계약을 따른다."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import os
from typing import Iterable, Protocol
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, MetaData, Table, Text,
    UniqueConstraint, create_engine, delete, insert, select, update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID, insert as pg_insert
from sqlalchemy.engine import Engine

from app.kernel.patients import PatientConflict, ensure_patient, patients

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

# 검사 1건을 다섯 테이블로 나눈다(Stage A-2, A14). 단계는 저장하지 않고 어느 테이블에 행이 있는지로 계산한다.
exams = Table(
    "exams", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("patient_id", PgUUID(as_uuid=True), ForeignKey(patients.c.id), nullable=False, index=True),
    Column("kind", Text, nullable=False),
    Column("exam_date", Date, nullable=False),
    Column("procedure_type", Text),
    Column("age", Integer),
    Column("sex", Text),  # 장부 행에 적힌 값 그대로. 빈칸·불일치를 다른 행으로 채우지 않는다
    Column("report_ref", Text),
    Column("source", Text, nullable=False),
    Column("import_batch_id", PgUUID(as_uuid=True), ForeignKey("ledger_import_batches.id")),
    Column("version", Integer, nullable=False),
    *_timestamps(),
    CheckConstraint("kind IN ('BIOPSY', 'CLO', 'STOOL')", name="ck_exams_kind"),
    CheckConstraint("source IN ('MANUAL', 'IMPORT', 'SEED')", name="ck_exams_source"),
    CheckConstraint("procedure_type IS NULL OR procedure_type IN ('stomach', 'colon')", name="ck_exams_procedure"),
    CheckConstraint("sex IS NULL OR sex IN ('M', 'F')", name="ck_exams_sex"),
    UniqueConstraint("kind", "report_ref", name="uq_exams_report_ref"),
)

specimens = Table(
    "specimens", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("exam_id", PgUUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, unique=True),
    Column("specimen_count", Integer),
    Column("site", Text, nullable=False),
    Column("handoff_id", PgUUID(as_uuid=True), ForeignKey("ledger_handoffs.id"), index=True),
    Column("registered_by", Text, nullable=False),
    Column("handed_by", Text, nullable=False),
    Column("received_by", Text, nullable=False),
    Column("entrusted_on", Date),
    *_timestamps(),
    CheckConstraint("specimen_count IS NULL OR specimen_count BETWEEN 1 AND 99", name="ck_specimens_count"),
)

exam_results = Table(
    "exam_results", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("exam_id", PgUUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, unique=True),
    Column("reported_on", Date),
    Column("result_code", Text, nullable=False),
    Column("findings", JSONB, nullable=False),
    Column("sydney", JSONB, nullable=False),
    Column("review_codes", JSONB, nullable=False),
    *_timestamps(),
)

doctor_reviews = Table(
    "doctor_reviews", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("exam_id", PgUUID(as_uuid=True), ForeignKey("exams.id"), nullable=False, unique=True),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("decided_by", Text),  # NULL = Stage A 이전 자료(기록자 미보존)
    Column("no_followup_reason", Text, nullable=False),
    *_timestamps(),
)

followups = Table(
    "followups", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("review_id", PgUUID(as_uuid=True), ForeignKey("doctor_reviews.id"), nullable=False, unique=True),
    Column("due_on", Date, nullable=False),
    Column("done_on", Date),
    Column("done_by", Text),
    *_timestamps(),
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


def _findings_json(entry: LedgerEntry) -> list[dict]:
    return [{"code": f.code, "lesion_count": f.lesion_count, "modifiers": list(f.modifiers), "registered": f.registered}
            for f in entry.findings]


def _parts(entry: LedgerEntry) -> tuple[dict, dict, dict | None, dict | None, dict | None]:
    """LedgerEntry 1건 → (검사, 검체, 결과, 원장 지시, 재검) 행. 있으면 안 되는 행은 None."""
    if entry.decided_at is None and (entry.followup_due or entry.no_followup_reason or entry.decided_by):
        raise ValueError("원장 지시 없이 재검 계획·사유를 저장할 수 없다")
    if entry.followup_due is None and (entry.followup_done_on or entry.followup_done_by):
        raise ValueError("재검 계획 없이 재검 완료를 저장할 수 없다")
    stamps = {"created_at": entry.created_at, "updated_at": entry.updated_at}
    exam = {"id": entry.id, "version": entry.version, "kind": entry.kind, "exam_date": entry.exam_date,
            "procedure_type": entry.procedure_type, "age": entry.age, "sex": entry.sex,
            "report_ref": entry.report_ref or None, "source": entry.source,
            "import_batch_id": entry.import_batch_id, **stamps}
    specimen = {"specimen_count": entry.specimen_count, "site": entry.site, "handoff_id": entry.handoff_id,
                "registered_by": entry.registered_by, "handed_by": entry.handed_by,
                "received_by": entry.received_by, "entrusted_on": entry.entrusted_on}
    has_result = (entry.reported_on is not None or entry.findings or entry.sydney or entry.result_code
                  or entry.review_codes)
    result = {"reported_on": entry.reported_on, "result_code": entry.result_code,
              "findings": _findings_json(entry), "sydney": dict(entry.sydney),
              "review_codes": list(entry.review_codes)} if has_result else None
    review = {"decided_at": entry.decided_at, "decided_by": entry.decided_by,
              "no_followup_reason": entry.no_followup_reason} if entry.decided_at else None
    followup = {"due_on": entry.followup_due, "done_on": entry.followup_done_on,
                "done_by": entry.followup_done_by} if entry.followup_due else None
    return exam, specimen, result, review, followup


def _upsert(connection, table, key: str, key_value: UUID, values: dict | None, now: datetime) -> UUID | None:
    """key 기준 1:1 하위 행을 맞춘다. values가 None이면 지운다. 남은 행의 id를 돌려준다."""
    if values is None:
        connection.execute(delete(table).where(table.c[key] == key_value))
        return None
    statement = pg_insert(table).values(id=uuid4(), **{key: key_value}, **values, created_at=now, updated_at=now)
    statement = statement.on_conflict_do_update(index_elements=[key], set_={**values, "updated_at": now})
    return connection.execute(statement.returning(table.c.id)).scalar_one()


def _save_children(connection, entry: LedgerEntry, parts) -> None:
    _, specimen, result, review, followup = parts
    now = entry.updated_at
    _upsert(connection, specimens, "exam_id", entry.id, specimen, now)
    _upsert(connection, exam_results, "exam_id", entry.id, result, now)
    if review is None:
        # 재검 행을 먼저 지워야 원장 지시 행을 지울 수 있다(FK).
        connection.execute(delete(followups).where(followups.c.review_id.in_(
            select(doctor_reviews.c.id).where(doctor_reviews.c.exam_id == entry.id))))
    review_id = _upsert(connection, doctor_reviews, "exam_id", entry.id, review, now)
    if review_id is not None:
        _upsert(connection, followups, "review_id", review_id, followup, now)


def _entries_query():
    e, s, r, d, f = exams.c, specimens.c, exam_results.c, doctor_reviews.c, followups.c
    return (
        select(e.id, e.version, e.kind, e.source, patients.c.chart_no, patients.c.name.label("patient_name"), e.sex,
               e.age, e.exam_date, e.procedure_type, s.specimen_count, s.site, e.report_ref, s.registered_by,
               s.handed_by, s.received_by, s.handoff_id, s.entrusted_on, r.reported_on, r.findings, r.sydney,
               r.result_code, r.review_codes, d.decided_at, d.decided_by, f.due_on.label("followup_due"),
               d.no_followup_reason, f.done_on.label("followup_done_on"), f.done_by.label("followup_done_by"),
               e.import_batch_id, e.created_at, e.updated_at)
        .select_from(exams)
        .join(patients, patients.c.id == e.patient_id)
        .join(specimens, s.exam_id == e.id)
        .outerjoin(exam_results, r.exam_id == e.id)
        .outerjoin(doctor_reviews, d.exam_id == e.id)
        .outerjoin(followups, f.review_id == d.id)
    )


def _from_row(row) -> LedgerEntry:
    data = dict(row._mapping)
    data["findings"] = tuple(
        Finding(f["code"], f["lesion_count"], tuple(f["modifiers"]), f["registered"]) for f in data["findings"] or ()
    )
    data["sydney"] = tuple((data["sydney"] or {}).items())
    data["review_codes"] = tuple(data["review_codes"] or ())
    data["result_code"] = data["result_code"] or ""
    data["no_followup_reason"] = data["no_followup_reason"] or ""
    data["report_ref"] = data["report_ref"] or ""
    return LedgerEntry(**data)


class PostgresStore:
    """PostgreSQL 16 저장소. 스키마는 Alembic(migrations/)으로만 만든다."""

    persistent = True

    def __init__(self, engine: Engine | None = None):
        self._engine = engine or create_engine(database_url(), pool_pre_ping=True)

    def entries(self) -> list[LedgerEntry]:
        with self._engine.connect() as connection:
            return [_from_row(row) for row in connection.execute(_entries_query())]

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
                for entry in inserted:
                    parts = _parts(entry)
                    patient_id = ensure_patient(connection, entry.chart_no, entry.patient_name, entry.created_at)
                    connection.execute(insert(exams).values(**parts[0], patient_id=patient_id))
                    _save_children(connection, entry, parts)
                for entry in updated:
                    parts = _parts(entry)
                    patient_id = ensure_patient(connection, entry.chart_no, entry.patient_name, entry.updated_at)
                    values = {k: v for k, v in parts[0].items() if k not in ("id", "created_at")}
                    # version이 다르면 다른 화면에서 먼저 바꾼 것이다. 전체 변경을 되돌린다.
                    result = connection.execute(
                        update(exams)
                        .where(exams.c.id == entry.id, exams.c.version == entry.version - 1)
                        .values(**values, patient_id=patient_id))
                    if result.rowcount != 1:
                        raise ConcurrentUpdate()
                    _save_children(connection, entry, parts)
        except (IntegrityError, PatientConflict):
            # 제약 위반 메시지에는 입력값이 들어 있을 수 있어 그대로 보여주지 않는다.
            raise ConcurrentUpdate() from None


def replace_entry(entry: LedgerEntry, now: datetime, **changes) -> LedgerEntry:
    """변경본은 항상 version을 올린다."""
    return replace(entry, version=entry.version + 1, updated_at=now, **changes)
