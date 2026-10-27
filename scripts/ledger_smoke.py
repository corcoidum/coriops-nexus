"""docker-compose.ledger.yml로 띄운 장부 컨테이너를 밖에서 두드려 보는 연기 시험(smoke test).

CI(.github/workflows/ci.yml의 ledger-container 작업)에서 쓴다. 표준 라이브러리만 쓰며 합성 자료만 넣는다.

    CORIOPS_SMOKE_PASSWORD=… CORIOPS_SMOKE_NEW_PASSWORD=… CORIOPS_EXPORT_HOST_DIR=… \
        python scripts/ledger_smoke.py --username ci-smoke

순서: 로그인 화면 → 로그인 → 첫 로그인 비밀번호 변경 → 합성 검사 1건 접수 → 지정 폴더 엑셀 출력
→ 출력 파일 확인 → 접속기록에 출력이 남았는지 확인. 하나라도 어긋나면 0이 아닌 값으로 끝난다.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from http.client import HTTPConnection, HTTPResponse
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo


SESSION_COOKIE = "coriops_session"
CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
KST = ZoneInfo("Asia/Seoul")


class SmokeError(Exception):
    pass


class Client:
    """세션 쿠키를 직접 들고 다닌다. 쿠키가 Secure라 http 위에서는 표준 쿠키 처리기가 보내지 않기 때문이다."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.origin = f"http://{host}:{port}"
        self.session = ""

    def request(self, method: str, path: str, form: dict | None = None) -> tuple[HTTPResponse, str]:
        connection = HTTPConnection(self.host, self.port, timeout=30)
        headers = {"Host": f"{self.host}:{self.port}"}
        if self.session:
            headers["Cookie"] = f"{SESSION_COOKIE}={self.session}"
        body = None
        if method == "POST":
            # 앱은 같은 사이트 Origin만 받는다(app/kernel/web.py same_origin).
            headers["Origin"] = self.origin
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urlencode(form or {}, doseq=True).encode("utf-8")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", errors="replace")
        connection.close()
        for header in response.headers.get_all("Set-Cookie") or []:
            name, _, rest = header.partition("=")
            if name.strip() == SESSION_COOKIE:
                self.session = rest.split(";", 1)[0]
        return response, text

    def csrf(self, path: str) -> str:
        response, text = self.request("GET", path)
        expect(response.status == 200, f"GET {path} → {response.status}")
        found = CSRF.search(text)
        expect(found is not None, f"GET {path}에 csrf_token이 없습니다")
        return found.group(1)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def location(response: HTTPResponse) -> str:
    parts = urlsplit(response.headers.get("Location", ""))
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def step(name: str) -> None:
    print(f"· {name}", flush=True)


def wait_for_login(client: Client, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last = "응답 없음"
    while time.monotonic() < deadline:
        try:
            response, text = client.request("GET", "/login")
            if response.status == 200:
                return text
            last = f"상태 {response.status}"
        except OSError as error:
            last = str(error)
        time.sleep(1)
    raise SmokeError(f"{timeout:.0f}초 안에 /login이 200을 돌려주지 않았습니다({last})")


def run(args: argparse.Namespace) -> None:
    password = os.environ["CORIOPS_SMOKE_PASSWORD"]
    new_password = os.environ["CORIOPS_SMOKE_NEW_PASSWORD"]
    export_dir = Path(os.environ["CORIOPS_EXPORT_HOST_DIR"])
    client = Client(args.host, args.port)

    step("GET /login")
    page = wait_for_login(client, args.wait)
    expect('action="/login"' in page, "로그인 화면에 로그인 양식이 없습니다")

    step("POST /login (임시 비밀번호)")
    response, text = client.request("POST", "/login", {"username": args.username, "password": password})
    # DB 연결이 막히면(예: 발신 차단이 psycopg 이름 조회를 막음) 여기서 303이 아니라 500이 된다.
    expect(response.status == 303, f"로그인 → {response.status}: {text[:300]}")
    expect(bool(client.session), "로그인 응답에 세션 쿠키가 없습니다")
    expect(location(response) == "/account/password", f"첫 로그인이 비밀번호 변경으로 가지 않았습니다: {location(response)}")

    step("POST /account/password")
    token = client.csrf("/account/password")
    response, text = client.request("POST", "/account/password", {
        "csrf_token": token, "current": password, "new": new_password, "confirm": new_password})
    expect(response.status == 303, f"비밀번호 변경 → {response.status}: {text[:300]}")
    response, _ = client.request("GET", "/")
    expect(response.status == 200, f"비밀번호 변경 뒤 첫 화면 → {response.status}")

    step("POST /ledger/register (합성 1건: T-0001 테스트환자)")
    token = client.csrf("/dashboard")
    today = datetime.now(KST).date().isoformat()
    response, text = client.request("POST", "/ledger/register", {
        "csrf_token": token, "kind": "BIOPSY", "chart_no": "T-0001", "patient_name": "테스트환자",
        "exam_date": today, "sex": "M", "age": "50", "procedure_type": "stomach", "specimen_count": "2"})
    expect(response.status == 303, f"접수 → {response.status}: {text[:300]}")

    step("POST /ledger/export")
    before = set(export_dir.glob("*.xlsx"))
    token = client.csrf("/ledger/excel")
    response, text = client.request("POST", "/ledger/export", {"csrf_token": token})
    # 읽기 전용 컨테이너에 /tmp가 없으면 openpyxl 저장이 실패해 500이 된다.
    expect(response.status == 303, f"엑셀 출력 → {response.status}: {text[:300]}")
    expect("notice=exported" in location(response), f"엑셀 출력 뒤 위치가 다릅니다: {location(response)}")

    step(f"출력 파일 확인 ({export_dir})")
    created = sorted(set(export_dir.glob("*.xlsx")) - before)
    expect(len(created) == 1, f"새 .xlsx가 1개가 아닙니다: {[p.name for p in created]}")
    with open(created[0], "rb") as source:
        expect(source.read(2) == b"PK", f"{created[0].name}이 xlsx(zip) 형식이 아닙니다")
    print(f"  {created[0].name} ({created[0].stat().st_size} bytes)")

    step("GET /privacy/access-logs (엑셀 출력 기록)")
    response, text = client.request("GET", f"/privacy/access-logs?{urlencode({'actor': args.username})}")
    expect(response.status == 200, f"접속기록 → {response.status}")
    expect("체인 일치" in text, "접속기록 해시 체인이 정상으로 표시되지 않습니다")
    rows = re.findall(r"<tr><td>\d+</td>(.*?)</tr>", text, re.S)
    cells = [re.findall(r"<td[^>]*>(.*?)</td>", row, re.S) for row in rows]
    # 열: 일시·아이디·접속지·업무·정보주체·대상·건수·결과
    expect(any(c[1] == args.username and c[3] == "엑셀 출력" and c[7] == "OK" for c in cells),
           "접속기록에 이 계정의 엑셀 출력 행이 없습니다")
    expect(any(c[3] == "등록" and c[4] == "T-0001" for c in cells), "접속기록에 T-0001 등록 행이 없습니다")
    expect(any(c[3] == "로그인" for c in cells), "접속기록에 로그인 행이 없습니다")


def main() -> int:
    parser = argparse.ArgumentParser(prog="python scripts/ledger_smoke.py")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--username", default="ci-smoke")
    parser.add_argument("--wait", type=float, default=90, help="/login이 뜰 때까지 기다리는 초")
    args = parser.parse_args()
    try:
        run(args)
    except SmokeError as error:
        print(f"연기 시험 실패: {error}", file=sys.stderr)
        return 1
    print("연기 시험 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
