# 첫 수동 대시보드

씨젠 확인과 기존 Excel 입력은 평소대로 한다. 먼저 합성 자료 8건으로 **결과 대기 → 재검 시점 기록 대기 → 환자 안내 대기 → 안내 완료** 화면을 시험한다. 약어 사전과 자동 로그인 없이 직원이 적은 짧은 결과·검사위치를 그대로 보여준다. 날짜는 원장이 정한 값을 사람이 입력하며 시스템이 계산하지 않는다.

이번 화면은 정식 v0.1의 일부를 미리 확인하는 독립 시연이다. 메모리에만 보관하므로 앱 재시작·초기화 시 입력이 사라진다. 실제 환자 입력, Excel 업로드, 로그인, 영구 저장, 접속·감사기록, LAN 배포는 이 화면의 범위가 아니다. 안내 완료는 정식 워크플로의 CLOSED 또는 F/U 완료를 뜻하지 않는다. 모든 건을 원장에게 별도 보고한다는 운영 규칙도 확정하지 않는다.

## 실행

Docker Desktop을 켜고 저장소 폴더에서 다음 명령을 실행한다. macOS 터미널과 Windows PowerShell에서 같은 명령을 쓸 수 있다.

```sh
docker compose -f docker-compose.prototype.yml --profile dashboard up -d --build dashboard
```

브라우저에서 <http://127.0.0.1:8765/dashboard>를 연다. 현재 PC에서만 접근하며 외부 자원을 불러오지 않는다. 합성 이름·차트번호만 사용한다.

1. 결과 대기 행을 선택해 예시 결과와 검사위치를 짧게 입력한다. 약어 등록은 필요 없다.
2. 원장이 정한 재검 날짜를 직접 입력하거나, 불필요 사유를 기록한다.
3. 안내 완료 또는 부재를 기록한다. 카드 숫자가 바뀌는지 확인한다.

```sh
docker compose -f docker-compose.prototype.yml --profile dashboard stop dashboard
```

## 구현과 확인 범위

- FastAPI 라우트는 `ManualDashboardService`만 호출한다. 기존 Ontology·PathologyRequest를 임의 변경하지 않는다.
- UUID 합성 8건, 앱별 독립 메모리, 순서·필수값 검증, Jinja 자동 escape, CSRF 확인, 브라우저 캐시 금지를 적용한다.
- Docker Desktop에서 `internal` network의 포트 게시가 되지 않아 시연 서버는 별도 bridge와 loopback 게시를 사용한다. `app.demo_server`가 Python audit hook으로 DNS 조회·발신 연결·UDP 전송 API를 거부한다. 이것은 이 합성 Python 시연의 발신 제한이며 정식 운영의 OS/네트워크 방화벽을 대신하지 않는다. PostgreSQL 시험은 기존 internal network를 유지한다.
- 기존 지정 스택의 FastAPI·Jinja2에 서버 실행용 uvicorn, HTML form용 python-multipart를 추가했다. httpx는 ASGI 화면 테스트 전용이다.
- 다음 작은 단계는 이 화면의 항목·순서를 확인한 후 필요한 최소 저장·개인 계정·기록 기능을 붙이는 것이다. 씨젠 자동화와 약어 자동 변환은 보류한다.

## 검증 결과 — 2026-10-22

- Python 3.12 + PostgreSQL 16 시험 환경에서 `python -m pytest -q`: **75 통과 / 0 실패**(1.39초). 기존 Excel 40개, 수동 대시보드 30개, 시연 발신·Compose 경계 5개다. Starlette의 httpx TestClient 사용에 대한 deprecation warning 1개가 있으며 실행에는 영향이 없다.
- 실제 브라우저: 수동 결과·위치 입력 → 지정 날짜 `2030-01-15` 그대로 기록 → 부재 1회(안내 대기 유지) → 안내 완료(카드·행 갱신) 확인. 체험을 위해 합성 seed 8건으로 초기화했다.
- `127.0.0.1:8765` HTTP 200과 Docker 포트 게시 확인. 호스트의 다른 주소에는 게시하지 않는다.
- 시연 앱은 메모리만 사용한다. PostgreSQL 연결 성공 시험과 앱의 영구 저장 구현은 구분한다. kernel의 Clock은 module을 import하지 않으며 모든 업무 변경은 module 서비스로 모은다. C1~C8 전체 구현은 아직 아니다.
- 개인정보 요구 P1~P14 중 실제 환자용 인증·접속/감사기록·HTTPS·파기·백업 등은 후속 구현이다. 이번 CSRF·escape·no-store·발신 API 거부 시험을 해당 요구 전체 충족으로 해석하지 않는다.

검증을 다시 실행하려면 [Excel 프로토타입의 PowerShell 명령](excel-prototype.md#정확한-실행-명령--windows-powershell)을 사용한다. macOS에서는 다음 명령으로 시험한다. 환경변수는 임시 자식 프로세스에만 전달하고 값을 출력하지 않는다.

```sh
python3 - <<'PY'
import os
import secrets
import subprocess
environment = os.environ.copy()
environment['CORIOPS_TEST_DB_PASSWORD'] = secrets.token_hex(24)
raise SystemExit(subprocess.run(
    ['docker', 'compose', '-f', 'docker-compose.prototype.yml', '--profile', 'test', 'run', '--build', '--rm', 'test'],
    env=environment,
).returncode)
PY
```
