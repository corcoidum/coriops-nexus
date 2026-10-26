"""시험은 내부 PostgreSQL만 허용하고 외부 연결은 즉시 거부한다."""

import os
import socket

import pytest

from app.demo_server import is_socketpair_loopback, scoped_socketpair


@pytest.fixture(scope="session")
def allowed_database():
    """허용된 DB 주소를 시험 세션마다 한 번만 미리 해석한다."""
    host = os.environ.get("PGHOST", "postgres-test")
    port = int(os.environ.get("PGPORT", "5432"))
    allowed = {host}
    try:
        allowed.update(entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
    except socket.gaierror:
        # 시험 DB가 없는 PC에서도 DB 비의존 시험은 실행하고, DB 시험만 연결 실패로 남긴다.
        pass
    return frozenset(allowed), port


@pytest.fixture(autouse=True)
def restrict_network(monkeypatch, allowed_database):
    """허용된 DB 주소 외의 DNS와 직접 socket을 제한한다."""
    allowed, port = allowed_database
    original_resolve = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(address):
        # Windows asyncio·TestClient의 socketpair 대체 구현이 만드는 loopback 연결만 예외로 둔다.
        if is_socketpair_loopback(address):
            return
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

    monkeypatch.setattr(socket, "socketpair", scoped_socketpair(socket.socketpair))
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
