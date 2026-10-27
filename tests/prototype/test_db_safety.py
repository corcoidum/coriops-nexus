"""접속 없이 운영 DB 혼입·초기화 설정 누락을 거부한다."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from db_safety import test_database_environment as guarded_environment


URL = "postgresql+psycopg://coriops_test@127.0.0.1:5432/coriops_test"


@pytest.mark.parametrize("changes", [
    {"CORIOPS_TEST_DATABASE_URL": ""},
    {"CORIOPS_TEST_ALLOW_RESET": ""},
    {"CORIOPS_TEST_DATABASE_URL": URL.replace("/coriops_test", "/coriops_live")},
    {"CORIOPS_TEST_DATABASE_URL": URL.replace("coriops_test@", "postgres@")},
    {"CORIOPS_TEST_DATABASE_URL": URL + "?dbname=coriops_live"},
    {"CORIOPS_TEST_DATABASE_URL": URL.replace("127.0.0.1", "example.invalid")},
    {"CORIOPS_TEST_DATABASE_URL": "not-a-url"},
    {"CORIOPS_DATABASE_URL": "postgresql+psycopg://"},
])
def test_unsafe_database_configuration_is_rejected(changes):
    environment = {"CORIOPS_TEST_DATABASE_URL": URL, "CORIOPS_TEST_ALLOW_RESET": "1", **changes}
    with pytest.raises(ValueError):
        guarded_environment(environment)


def test_valid_test_url_overrides_conflicting_libpq_defaults():
    result = guarded_environment({"CORIOPS_TEST_DATABASE_URL": URL, "CORIOPS_TEST_ALLOW_RESET": "1",
                                  "PGDATABASE": "coriops_live", "PGHOST": "example.invalid",
                                  "PGHOSTADDR": "192.0.2.10", "PGOPTIONS": "-c search_path=other"})
    assert result["CORIOPS_DATABASE_URL"] == URL
    assert result["PGDATABASE"] == "coriops_test" and result["PGHOST"] == "127.0.0.1"
    assert result["PGHOSTADDR"] is None and result["PGOPTIONS"] is None


def test_pytest_stops_before_collecting_or_connecting_when_reset_is_not_enabled():
    environment = os.environ.copy()
    environment.pop("CORIOPS_TEST_ALLOW_RESET", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                            cwd=Path(__file__).resolve().parents[2], env=environment,
                            capture_output=True, text=True)
    assert result.returncode == 4
    assert "CORIOPS_TEST_ALLOW_RESET=1" in result.stderr
    assert "collected" not in result.stdout
