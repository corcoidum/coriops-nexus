"""실제 PostgreSQL 16 시험 환경과 외부 통신 경계를 확인한다."""

import socket

import psycopg
import pytest


def test_postgresql_16_is_available():
    with psycopg.connect("") as connection:
        version = int(connection.execute("SHOW server_version_num").fetchone()[0])
    assert 160000 <= version < 170000


def test_unapproved_external_connection_is_rejected():
    with pytest.raises(PermissionError, match="EXTERNAL_NETWORK_DISABLED"):
        socket.create_connection(("example.invalid", 443), timeout=1)
