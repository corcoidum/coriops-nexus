"""localhost 시연 서버. 실행 중 Python의 발신 socket API를 거부한다."""

import sys

import uvicorn


def block_outbound_sockets(allowed_hosts: frozenset[str] = frozenset(), allowed_port: int | None = None) -> None:
    """수신 HTTP는 허용하고 DNS 조회·발신 연결·UDP 전송은 막는다.

    allowed_hosts·allowed_port를 주면 그 DB 주소로 가는 TCP 연결과 이름 조회만 예외로 둔다.
    """
    def guard(event: str, args: tuple) -> None:
        # psycopg는 DB 이름을 포트 문자열('5432')로 조회하므로 숫자와 문자열을 같게 본다.
        if (event == "socket.getaddrinfo" and args[0] in allowed_hosts and allowed_port is not None
                and str(args[1]) == str(allowed_port)):
            return
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] in allowed_hosts and address[1] == allowed_port:
                return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise PermissionError("DEMO_OUTBOUND_NETWORK_DISABLED")

    sys.addaudithook(guard)


def main() -> None:
    block_outbound_sockets()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
