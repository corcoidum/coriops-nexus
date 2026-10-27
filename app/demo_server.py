"""localhost 시연 서버. 실행 중 Python의 발신 socket API를 거부한다."""

import functools
import ipaddress
import socket
import sys
import threading

import uvicorn


_SOCKETPAIR = threading.local()


def scoped_socketpair(original):
    """socketpair 호출 동안에만 loopback 연결을 표시하는 wrapper를 만든다."""
    if getattr(original, "_loopback_scoped", False):
        return original

    @functools.wraps(original)
    def socketpair(*args, **kwargs):
        _SOCKETPAIR.active = True
        try:
            return original(*args, **kwargs)
        finally:
            _SOCKETPAIR.active = False

    socketpair._loopback_scoped = True
    return socketpair


def is_socketpair_loopback(address: object) -> bool:
    """Windows socketpair 대체 구현이 만드는 loopback 연결인지 확인한다.

    Windows asyncio는 내부 self-pipe를 socket.socketpair로 만들고, Windows의 socketpair는
    loopback listen 후 connect로 구현된다. 그 호출 안의 IP 리터럴 loopback 연결만 인정한다.
    """
    if not getattr(_SOCKETPAIR, "active", False):
        return False
    if not isinstance(address, tuple) or not address or not isinstance(address[0], str):
        return False
    try:
        return ipaddress.ip_address(address[0].split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def block_outbound_sockets(allowed_hosts: frozenset[str] = frozenset(), allowed_port: int | None = None) -> None:
    """수신 HTTP는 허용하고 DNS 조회·발신 연결·UDP 전송은 막는다.

    allowed_hosts·allowed_port를 주면 그 DB 주소로 가는 TCP 연결과 이름 조회만 예외로 둔다.
    """
    socket.socketpair = scoped_socketpair(socket.socketpair)

    def guard(event: str, args: tuple) -> None:
        # psycopg는 DB 이름을 포트 문자열('5432')로 조회하므로 숫자와 문자열을 같게 본다.
        if (event == "socket.getaddrinfo" and args[0] in allowed_hosts and allowed_port is not None
                and str(args[1]) == str(allowed_port)):
            return
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] in allowed_hosts and address[1] == allowed_port:
                return
            if is_socketpair_loopback(address):
                return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise PermissionError("DEMO_OUTBOUND_NETWORK_DISABLED")

    sys.addaudithook(guard)


def main() -> None:
    block_outbound_sockets()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
