"""localhost 시연 서버. 실행 중 Python의 발신 socket API를 거부한다."""

import sys

import uvicorn


def block_outbound_sockets(allowed_hosts: frozenset[str] = frozenset(), allowed_port: int | None = None) -> None:
    """수신 HTTP는 허용하고 DNS 조회·발신 연결·UDP 전송은 막는다.

    allowed_hosts·allowed_port를 주면 그 DB 주소로 가는 TCP 연결과 이름 조회만 예외로 둔다.
    """
    def same_port(value: object) -> bool:
        # psycopg는 이름 조회 때 포트를 문자열('5432')로 넘긴다. 숫자와 문자열을 같은 포트로 본다.
        return allowed_port is not None and str(value) == str(allowed_port)

    def guard(event: str, args: tuple) -> None:
        if event == "socket.getaddrinfo" and args[0] in allowed_hosts and same_port(args[1]):
            return
        if event == "socket.connect":
            address = args[1]
            if isinstance(address, tuple) and address[0] in allowed_hosts and same_port(address[1]):
                return
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg"}:
            raise PermissionError("DEMO_OUTBOUND_NETWORK_DISABLED")

    sys.addaudithook(guard)


def main() -> None:
    block_outbound_sockets()
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
