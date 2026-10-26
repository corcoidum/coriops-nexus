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


def test_demo_guard_allows_socketpair_but_not_other_loopback_connections():
    # Windows asyncio의 self-pipe는 socketpair(loopback 연결)로 만들어지므로 서버 시작에 필요하다.
    result = run_with_guard(
        "import asyncio\n"
        "asyncio.new_event_loop().close()\n"
        "first, second = socket.socketpair()\n"
        "first.close(); second.close()\n"
        "with socket.socket() as listener:\n"
        "    listener.bind(('127.0.0.1', 0))\n"
        "    listener.listen(1)\n"
        "    try:\n"
        "        socket.socket().connect(listener.getsockname())\n"
        "    except PermissionError as error:\n"
        "        assert str(error) == 'DEMO_OUTBOUND_NETWORK_DISABLED'\n"
        "    else:\n"
        "        raise AssertionError('socketpair 밖의 loopback 연결이 열렸습니다')\n"
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


def test_db_hostname_lookup_is_allowed_with_a_string_port():
    """psycopg는 DB 이름(예: Compose의 ledger-db)을 포트 문자열 '5432'로 조회한다. 숫자 포트와 같게 본다."""
    script = (
        "import socket\n"
        "from app.demo_server import block_outbound_sockets\n"
        "block_outbound_sockets(frozenset({'localhost'}), 9)\n"
        "socket.getaddrinfo('localhost', '9', type=socket.SOCK_STREAM)\n"
        "socket.getaddrinfo('localhost', 9, type=socket.SOCK_STREAM)\n"
        "for host, port in [('localhost', '10'), ('example.invalid', '9')]:\n"
        "    try:\n"
        "        socket.getaddrinfo(host, port)\n"
        "    except PermissionError as error:\n"
        "        assert str(error) == 'DEMO_OUTBOUND_NETWORK_DISABLED'\n"
        "    else:\n"
        "        raise AssertionError('DB 외 이름 조회가 열렸습니다')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_demo_compose_needs_no_secrets():
    """메모리 시연·시험 파일에는 DB 장부의 필수 비밀값이 섞이지 않는다(.env 없이 실행)."""
    with open("docker-compose.prototype.yml", encoding="utf-8") as source:
        text = source.read()
    assert "CORIOPS_DB_PASSWORD" not in text and ":?" not in text


def test_ledger_profile_keeps_db_internal_and_mounts_only_the_export_folder():
    with open("docker-compose.ledger.yml", encoding="utf-8") as source:
        compose = yaml.safe_load(source)
    ledger, database = compose["services"]["ledger"], compose["services"]["ledger-db"]
    assert ledger["ports"] == ["127.0.0.1:8766:8000"]
    assert ledger["command"] == ["python", "-m", "app.ledger_server"]
    assert ledger["read_only"] is True
    # 읽기 전용 컨테이너에서도 엑셀 출력이 되도록 임시 폴더는 메모리(tmpfs)로만 둔다.
    assert [t.split(":")[0] for t in ledger["tmpfs"]] == ["/tmp"]
    assert [v.split(":")[-1] for v in ledger["volumes"]] == ["/exports"]
    assert ledger["environment"]["CORIOPS_EXPORT_DIR"] == "/exports"
    assert "ports" not in database
    assert database["networks"] == ["ledger-internal"]
    assert compose["networks"]["ledger-internal"]["internal"] is True
    # 비밀번호는 .env에서만 받고 compose 파일에 값을 쓰지 않는다.
    assert ledger["environment"]["PGPASSWORD"].startswith("${CORIOPS_DB_PASSWORD:?")
