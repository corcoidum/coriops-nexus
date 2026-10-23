"""localhost 시연 서버. 실행 중 Python의 발신 socket API를 거부한다."""

import ipaddress
import sys

import uvicorn


def is_loopback_address(address: object) -> bool:
    """IP 리터럴 loopback만 인정한다. 이름은 내부 DNS 조회를 거치므로 거부한다."""
    if not isinstance(address, tuple) or not address or not isinstance(address[0], str):
        return False
    try:
        return ipaddress.ip_address(address[0].split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def block_outbound_sockets() -> None:
    """수신 HTTP는 허용하고 DNS 조회·발신 연결·UDP 전송은 막는다."""
    def guard(event: str, args: tuple) -> None:
        # Windows asyncio는 socketpair를 loopback 연결로 대체 구현하므로 loopback 연결만 허용한다.
        if event == "socket.connect" and is_loopback_address(args[1]):
            return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise PermissionError("DEMO_OUTBOUND_NETWORK_DISABLED")

    sys.addaudithook(guard)


def main() -> None:
    block_outbound_sockets()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
