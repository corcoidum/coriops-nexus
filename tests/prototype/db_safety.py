"""DB에 접속하기 전에 시험 전용 주소와 초기화 의도를 확인한다."""

from collections.abc import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def test_database_environment(environment: Mapping[str, str]) -> dict[str, str | None]:
    value = environment.get("CORIOPS_TEST_DATABASE_URL", "")
    if not value or environment.get("CORIOPS_TEST_ALLOW_RESET") != "1":
        raise ValueError("시험 전용 CORIOPS_TEST_DATABASE_URL과 CORIOPS_TEST_ALLOW_RESET=1이 필요합니다.")
    try:
        url = make_url(value)
        valid = (url.drivername == "postgresql+psycopg" and url.database == "coriops_test"
                 and url.username == "coriops_test" and url.host in {"127.0.0.1", "localhost", "::1", "postgres-test"}
                 and url.port is not None and 1 <= url.port <= 65535 and not url.query)
    except (ArgumentError, ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("로컬 PostgreSQL의 coriops_test 사용자·DB와 명시적 포트만 시험에 허용합니다.")
    runtime = environment.get("CORIOPS_DATABASE_URL", "")
    if runtime and runtime != value:
        raise ValueError("앱 DB 설정이 시험 DB와 다릅니다. CORIOPS_DATABASE_URL을 해제하고 다시 실행하세요.")
    return {"CORIOPS_DATABASE_URL": value, "PGHOST": url.host, "PGPORT": str(url.port),
            "PGUSER": url.username, "PGDATABASE": url.database, "PGSERVICE": None, "PGSERVICEFILE": None,
            "PGHOSTADDR": None, "PGOPTIONS": None}
