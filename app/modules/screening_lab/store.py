"""혈액 장부 저장소. 환자 식별은 공통 테이블, 결과·처리는 별도 테이블에 둔다."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from datetime import datetime
from threading import RLock
from uuid import UUID

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, MetaData, Table, Text, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.kernel.database import connection, transaction
from app.kernel.patients import PatientConflict, ensure_patient, patients
from app.kernel.web import UserError

from .ledger import LabItem, LabRecord
from .model import LabCase


metadata = MetaData()
lab_cases = Table(
    "lab_cases", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("patient_id", PgUUID(as_uuid=True), ForeignKey(patients.c.id), nullable=False),
    Column("received_date", Date, nullable=False), Column("report_ref", Text, nullable=False),
    Column("sex", Text), Column("age", Text), Column("exam_kinds", JSONB, nullable=False),
    Column("entrusted_date", Date), Column("report_date", Date), Column("items", JSONB, nullable=False),
    Column("result_received", Boolean, nullable=False), Column("followup_note", Text),
    *[Column(name, DateTime(timezone=True)) for name in
      ("critical_marked_at", "critical_reported_at", "result_entered_at", "checked_at")],
    *[Column(name, Text, nullable=False) for name in
      ("critical_marked_by", "critical_reported_by", "result_entered_by", "checked_by", "registered_by")],
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False), Column("version", Integer, nullable=False),
)
Index("uq_lab_report_ref", lab_cases.c.report_ref, unique=True, postgresql_where=text("report_ref <> ''"))
Index("ix_lab_received_date", lab_cases.c.received_date)


class MemoryLabStore:
    persistent = False

    def __init__(self):
        self._cases: dict[UUID, LabCase] = {}
        self._lock = RLock()

    @contextmanager
    def transaction(self):
        with self._lock:
            before = self._cases.copy()
            try:
                yield
            except BaseException:
                self._cases = before
                raise

    def cases(self) -> list[LabCase]:
        with self._lock:
            return list(self._cases.values())

    def write(self, case: LabCase, now: datetime, expected: int | None = None) -> None:
        with self._lock:
            old = self._cases.get(case.id)
            if (expected is None and old) or (expected is not None and (not old or old.version != expected)):
                raise UserError("다른 화면에서 먼저 처리했습니다. 다시 조회해 주세요.", 409)
            for other in self._cases.values():
                if other.record.chart_no == case.record.chart_no and other.record.patient_name != case.record.patient_name:
                    raise UserError("같은 차트번호의 이름이 다릅니다. 원본을 대조해 주세요.", 409)
                if other.id != case.id and case.record.report_ref and other.record.report_ref == case.record.report_ref:
                    raise UserError("이미 사용한 접수번호입니다. 원본을 대조해 주세요.", 409)
            self._cases[case.id] = replace(case, version=(expected or 0) + 1,
                                          created_at=case.created_at or now, updated_at=now)

    def reset(self, cases: dict[UUID, LabCase]) -> None:
        with self._lock:
            self._cases = cases


def _from_row(row) -> LabCase:
    values = row._mapping
    record = LabRecord(**{f.name: values[f.name] for f in fields(LabRecord) if f.name != "items"},
                       items=tuple(LabItem(**item) for item in values["items"]))
    record = replace(record, exam_kinds=tuple(record.exam_kinds))
    return LabCase(record=record, **{f.name: values[f.name] for f in fields(LabCase) if f.name != "record"})


class PostgresLabStore:
    persistent = True

    def __init__(self, engine: Engine):
        self.engine = engine

    def transaction(self):
        return transaction(self.engine)

    def cases(self) -> list[LabCase]:
        query = select(lab_cases, patients.c.chart_no, patients.c.name.label("patient_name")).join(
            patients, lab_cases.c.patient_id == patients.c.id).order_by(lab_cases.c.created_at, lab_cases.c.id)
        with connection(self.engine) as connected:
            return [_from_row(row) for row in connected.execute(query)]

    def write(self, case: LabCase, now: datetime, expected: int | None = None) -> None:
        try:
            with transaction(self.engine) as connected:
                patient_id = ensure_patient(connected, case.record.chart_no, case.record.patient_name, now)
                values = {f.name: getattr(case, f.name) for f in fields(LabCase) if f.name != "record"}
                record = asdict(case.record)
                record.pop("chart_no")
                record.pop("patient_name")
                values.update(record, patient_id=patient_id, created_at=case.created_at or now,
                              updated_at=now, version=(expected or 0) + 1)
                if expected is None:
                    connected.execute(insert(lab_cases).values(**values))
                else:
                    changed = connected.execute(update(lab_cases).where(
                        lab_cases.c.id == case.id, lab_cases.c.version == expected).values(**values))
                    if changed.rowcount != 1:
                        raise UserError("다른 화면에서 먼저 처리했습니다. 다시 조회해 주세요.", 409)
        except PatientConflict:
            raise UserError("같은 차트번호의 이름이 다릅니다. 원본을 대조해 주세요.", 409) from None
        except IntegrityError:
            raise UserError("접수번호 또는 접수 요청이 겹칩니다. 기존 기록을 확인해 주세요.", 409) from None
