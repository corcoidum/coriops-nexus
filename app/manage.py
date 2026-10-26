"""오프라인 관리 명령. 처음 원장(책임자) 계정을 만들 때 쓴다.

    python -m app.manage create-staff --username wonjang --display-name 원장 --roles DOCTOR,PRIVACY_OFFICER

비밀번호는 명령행 인자가 아니라 화면 입력(getpass)으로 두 번 받는다. 명령행 기록·로그에 남지 않게 하기 위해서다.
"""

import argparse
from getpass import getpass
import sys

from sqlalchemy import create_engine

from app.kernel.access_log import AccessLogger
from app.kernel.auth import AuthError, AuthService
from app.ledger_server import migrate
from app.modules.endoscopy_pathology.ledger_db import database_url


def main(argv: list[str] | None = None, read_password=getpass) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-staff", help="개인 계정 만들기(초기 책임자 포함)")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--roles", required=True, help="쉼표로 구분: DOCTOR,ADMIN,NURSE,PRIVACY_OFFICER")
    create.add_argument("--reason", default="오프라인 초기 계정 생성")
    args = parser.parse_args(argv)

    migrate()
    engine = create_engine(database_url())
    auth = AuthService(engine)
    password = read_password("임시 비밀번호: ")
    if password != read_password("다시 입력: "):
        print("두 비밀번호가 다릅니다.", file=sys.stderr)
        return 2
    roles = [r.strip().upper() for r in args.roles.split(",") if r.strip()]
    try:
        auth.create_staff(args.username, args.display_name, roles, password, changed_by=None,
                                     reason=args.reason, must_change_password=True)
    except AuthError as error:
        print(error.message, file=sys.stderr)
        return 1
    AccessLogger(engine).record(actor_id=None, actor_label="SYSTEM:manage", client_ip="local", action="ACCOUNT",
                                target_type=f"staff_create:{args.username.strip().lower()}")
    print(f"계정을 만들었습니다: {args.username} (첫 로그인 때 비밀번호를 바꿔야 합니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
