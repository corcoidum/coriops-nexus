"""환자 테이블. 차트번호당 1명이며 여러 업무 모듈이 함께 쓴다(A14).

이름이 다른 같은 차트번호는 덮어쓰지 않고 거부한다. 주민번호·연락처·주소는 저장하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, MetaData, Table, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID, insert
from sqlalchemy.engine import Connection


metadata = MetaData()

patients = Table(
    "patients", metadata,
    Column("id", PgUUID(as_uuid=True), primary_key=True),
    Column("chart_no", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class PatientConflict(Exception):
    """같은 차트번호에 다른 이름. 메시지에 차트번호·이름을 넣지 않는다."""


def ensure_patient(connection: Connection, chart_no: str, name: str, now: datetime) -> UUID:
    """차트번호의 환자 id. 없으면 만들고, 이름이 다르면 거부한다."""
    connection.execute(insert(patients).values(id=uuid4(), chart_no=chart_no, name=name, created_at=now,
                                               updated_at=now).on_conflict_do_nothing(index_elements=["chart_no"]))
    patient_id, stored_name = connection.execute(
        select(patients.c.id, patients.c.name).where(patients.c.chart_no == chart_no)).one()
    if stored_name != name:
        raise PatientConflict()
    return patient_id
