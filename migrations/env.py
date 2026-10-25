"""Alembic 실행 환경. 접속 문자열을 로그에 출력하지 않는다."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.modules.endoscopy_pathology.ledger_db import database_url, metadata


def run_migrations_online() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
