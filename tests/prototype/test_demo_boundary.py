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
