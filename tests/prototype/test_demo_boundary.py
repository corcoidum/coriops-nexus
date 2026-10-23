"""시연 서버의 발신 제한은 별도 프로세스에서 시험한다."""

import subprocess
import sys

import pytest
import yaml


def run_with_guard(body: str) -> subprocess.CompletedProcess:
    # audit hook은 제거할 수 없으므로 pytest·PostgreSQL 연결과 격리한다.
    script = (
        "import socket\n"
        "from app.demo_server import block_outbound_sockets\n"
        "block_outbound_sockets()\n"
        f"{body}"
    )
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)


@pytest.mark.parametrize("operation", [
    "socket.getaddrinfo('example.invalid', 443)",
    # 192.0.2.0/24는 문서용 주소이며 hook이 연결 전에 거부하므로 실제 발신은 없다.
    "socket.socket().connect(('192.0.2.1', 9))",
    "socket.socket().connect_ex(('192.0.2.1', 9))",
    "socket.socket().connect(('localhost', 9))",
    "socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'synthetic', ('127.0.0.1', 9))",
])
def test_demo_rejects_outbound_socket_apis(operation):
    result = run_with_guard(
        "try:\n"
        f"    {operation}\n"
        "except PermissionError as error:\n"
        "    assert str(error) == 'DEMO_OUTBOUND_NETWORK_DISABLED'\n"
        "else:\n"
        "    raise AssertionError('발신 API가 거부되지 않았습니다')\n"
    )
    assert result.returncode == 0, result.stderr


def test_demo_guard_allows_event_loop_and_loopback_connections():
    # Windows asyncio의 self-pipe는 loopback 연결로 만들어지므로 서버 시작에 필요하다.
    result = run_with_guard(
        "import asyncio\n"
        "asyncio.new_event_loop().close()\n"
        "with socket.socket() as listener:\n"
        "    listener.bind(('127.0.0.1', 0))\n"
        "    listener.listen(1)\n"
        "    with socket.socket() as client:\n"
        "        client.connect(listener.getsockname())\n"
    )
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
