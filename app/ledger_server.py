"""DB 저장 장부 서버. 시작할 때 Alembic으로 스키마를 맞추고, DB 외 발신 연결은 막는다."""

import os
from pathlib import Path
import socket

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
import uvicorn

from app.demo_server import block_outbound_sockets
from app.modules.endoscopy_pathology.ledger_db import database_url


ROOT = Path(__file__).resolve().parents[1]


def migrate() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


def database_address() -> tuple[frozenset[str], int]:
    url = make_url(database_url())
    host = url.host or os.environ.get("PGHOST", "localhost")
    port = url.port or int(os.environ.get("PGPORT", "5432"))
    # 이름과 실제 IP를 모두 허용 목록에 넣은 뒤 차단을 건다.
    addresses = {host, *(entry[4][0] for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))}
    return frozenset(addresses), port


def main() -> None:
    if not os.environ.get("CORIOPS_DATABASE_URL"):
        raise SystemExit("CORIOPS_DATABASE_URL이 없습니다. 메모리 시연은 app.demo_server를 사용하세요.")
    migrate()
    hosts, port = database_address()
    block_outbound_sockets(hosts, port)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)


if __name__ == "__main__":
    main()
