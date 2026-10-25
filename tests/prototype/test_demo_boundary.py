"""시연 서버의 발신 제한은 별도 프로세스에서 시험한다."""

import subprocess
import sys

import pytest
import yaml


@pytest.mark.parametrize("operation", [
    "socket.getaddrinfo('example.invalid', 443)",
    "socket.socket().connect(('127.0.0.1', 9))",
    "socket.socket().connect_ex(('127.0.0.1', 9))",
    "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'synthetic', ('127.0.0.1', 9))",
])
def test_demo_rejects_outbound_socket_apis(operation):
    # audit hook은 제거할 수 없으므로 pytest·PostgreSQL 연결과 격리한다.
    script = (
        "import socket\n"
        "from app.demo_server import block_outbound_sockets\n"
        "block_outbound_sockets()\n"
        "try:\n"
        f"    {operation}\n"
        "except PermissionError as error:\n"
        "    assert str(error) == 'DEMO_OUTBOUND_NETWORK_DISABLED'\n"
        "else:\n"
        "    raise AssertionError('발신 API가 거부되지 않았습니다')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_dashboard_only_publishes_to_loopback_and_has_no_data_mount():
    with open("docker-compose.prototype.yml", encoding="utf-8") as source:
        compose = yaml.safe_load(source)
    dashboard = compose["services"]["dashboard"]
    assert dashboard["ports"] == ["127.0.0.1:8765:8000"]
    assert dashboard["command"] == ["python", "-m", "app.demo_server"]
    assert dashboard["read_only"] is True
    assert "volumes" not in dashboard
    assert "ports" not in compose["services"]["postgres-test"]


def test_db_allowance_only_opens_the_database_address():
    script = (
        "import socket\n"
        "from app.demo_server import block_outbound_sockets\n"
        "block_outbound_sockets(frozenset({'127.0.0.1'}), 9)\n"
        "try:\n"
        "    socket.socket().connect(('127.0.0.1', 9))\n"
        "except PermissionError:\n"
        "    raise AssertionError('DB 주소까지 막혔습니다')\n"
        "except OSError:\n"
        "    pass\n"
        "for target in [('127.0.0.1', 10), ('10.0.0.1', 9)]:\n"
        "    try:\n"
        "        socket.socket().connect(target)\n"
        "    except PermissionError as error:\n"
        "        assert str(error) == 'DEMO_OUTBOUND_NETWORK_DISABLED'\n"
        "    else:\n"
        "        raise AssertionError('DB 외 주소가 열렸습니다')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_ledger_profile_keeps_db_internal_and_mounts_only_the_export_folder():
    with open("docker-compose.prototype.yml", encoding="utf-8") as source:
        compose = yaml.safe_load(source)
    ledger, database = compose["services"]["ledger"], compose["services"]["ledger-db"]
    assert ledger["ports"] == ["127.0.0.1:8766:8000"]
    assert ledger["command"] == ["python", "-m", "app.ledger_server"]
    assert ledger["read_only"] is True
    assert [v.split(":")[-1] for v in ledger["volumes"]] == ["/exports"]
    assert ledger["environment"]["CORIOPS_EXPORT_DIR"] == "/exports"
    assert "ports" not in database
    assert database["networks"] == ["ledger-internal"]
    assert compose["networks"]["ledger-internal"]["internal"] is True
    # 비밀번호는 .env에서만 받고 compose 파일에 값을 쓰지 않는다.
    assert ledger["environment"]["PGPASSWORD"].startswith("${CORIOPS_DB_PASSWORD:?")
