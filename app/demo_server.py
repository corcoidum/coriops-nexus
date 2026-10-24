"""localhost 시연 서버. 실행 중 Python의 발신 socket API를 거부한다."""

import sys

import uvicorn


def block_outbound_sockets() -> None:
    """수신 HTTP는 허용하고 DNS 조회·발신 연결·UDP 전송은 막는다."""
    def guard(event: str, args: tuple) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise PermissionError("DEMO_OUTBOUND_NETWORK_DISABLED")

    sys.addaudithook(guard)


def main() -> None:
    block_outbound_sockets()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
