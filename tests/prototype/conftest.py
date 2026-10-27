"""시험은 내부 PostgreSQL만 허용하고 외부 연결은 즉시 거부한다."""

import os
import socket

import pytest

from db_safety import test_database_environment


def pytest_configure(config):
    # 수집 중 app.main을 import하기 전 검사한다. fixture 시점에는 이미 늦다.
    try:
        settings = test_database_environment(os.environ)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from None
    for name, value in settings.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def restrict_network(monkeypatch):
    """허용된 DB 주소만 미리 해석한 뒤 DNS와 직접 socket도 제한한다."""
    host = os.environ.get("PGHOST", "postgres-test")
    port = int(os.environ.get("PGPORT", "5432"))
    original_resolve = socket.getaddrinfo
    allowed = {host}
    allowed.update(entry[4][0] for entry in original_resolve(host, port, type=socket.SOCK_STREAM))
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(address):
        if not isinstance(address, tuple) or address[0] not in allowed or address[1] != port:
            raise PermissionError("EXTERNAL_NETWORK_DISABLED")

    def resolve(node, service, *args, **kwargs):
        if node not in allowed or int(service) != port:
            raise PermissionError("EXTERNAL_NETWORK_DISABLED")
        return original_resolve(node, service, *args, **kwargs)

    def connect(sock, address):
        check(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
