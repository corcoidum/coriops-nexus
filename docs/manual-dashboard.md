# 조직검체 장부 대시보드 (합성 시연)

> 2026-10-25: DB 저장·엑셀 가져오기/대조/출력·새 검사 접수·CLO/Stool이 추가됐다. 최신 사용법은 [장부 앱 문서](ledger-app.md)를 본다. 이 문서의 메모리 시연(합성 14건, 포트 8765)도 계속 쓸 수 있다.

씨젠 확인과 기존 Excel 장부는 평소대로 한다. 이 화면은 매일 하는 **접수 → 인계 → 결과 → 원장 지시 → 재검** 흐름을 한 화면에서 누락 없이 보는지 합성 자료 12건으로 시험한다. 결과 설명·환자 안내는 EMR에서 관리하므로 이 화면에서 기록하지 않는다(A12).

이번 화면은 정식 v0.1의 일부를 미리 확인하는 독립 시연이다. 메모리에만 보관하므로 앱 재시작·초기화 시 입력이 사라진다. 실제 환자 입력, Excel 업로드, 로그인, 영구 저장, 접속·감사기록, LAN 배포는 범위가 아니다. 종결은 정식 워크플로의 CLOSED를 뜻하지 않는다.

## 화면 구성

| 구역 | 하는 일 | 기준 |
|---|---|---|
| 오늘 씨젠 인계 | 인계 대기 건수·병 수, 수령 마감까지 남은 시간. 접수인·인계인·인수인과 **직접 센 병 수**를 입력하면 대기 검체 전체가 결과 대기로 넘어간다 | 수령 시각 `config/clinic.yaml` (월화목금 15:00, 수토 11:00, 휴진일 없음). 병 수가 장부와 다르면 기록하지 않는다 |
| 단계 카드 5개 | 인계 대기 / 결과 대기(지연) / 원장 지시 대기(코드 검토) / 재검 예정(경과·30일 이내) / 종결 | `config/manual_dashboard.yaml` |
| 결과 대기 | 위탁 후 진료일 수. 기준 초과 시 **지연** | 2진료일 초과 [가정]. 일요일·KR 공휴일·임시 휴진 제외 |
| 결과 입력 | 접수번호, **결과 코드**(`TA#2(L), H#1`), 위 검체만 Sydney 등급(`HP-/Neu++/…`), 검사위치 | A11: 문장형 판독문은 형식 오류로 거부. 미등록 코드는 저장하되 약어 사전(Q19) 검토 표시 |
| 원장 지시 | 원장이 정한 재검 날짜 또는 불필요 사유를 그대로 기록 | 날짜를 추천·계산하지 않는다 |
| 재검 예정 | 기한 경과 → 30일 이내 → 그 이후 순서. 재검 시행일을 기록하면 종결 | 정식 R07·R08과 같은 기준 |
| 검색 | 차트번호·접수번호·결과 코드(대소문자 무시) | 검색어 30자 이하 |

## 실행

Docker Desktop을 켜고 저장소 폴더에서 다음 명령을 실행한다. macOS 터미널과 Windows PowerShell에서 같은 명령을 쓸 수 있다.

```sh
docker compose -f docker-compose.prototype.yml --profile dashboard up -d --build dashboard
```

브라우저에서 <http://127.0.0.1:8765/dashboard>를 연다. 현재 PC에서만 접근하며 외부 자원을 불러오지 않는다. 합성 이름·차트번호만 사용한다.

1. **오늘 씨젠 인계**에서 병 수를 일부러 틀리게 넣어 거부되는지 보고, 장부 병 수를 넣어 인계한다.
2. 결과 대기에서 **지연** 표시된 행을 골라 `TA#2(L), H#1` 형식으로 결과를 입력한다. 문장을 넣으면 거부된다.
3. 원장 지시 대기에서 재검 날짜를 입력하면 재검 예정으로, 불필요 사유를 입력하면 종결로 간다.
4. 왼쪽 **재검 대상**에서 기한 경과 건에 재검 시행일을 기록한다.

```sh
docker compose -f docker-compose.prototype.yml --profile dashboard stop dashboard
```

## 구현과 확인 범위

- FastAPI 라우트는 `ManualDashboardService`만 호출한다. 진료일 계산은 kernel `ClinicCalendar`, 결과 표기 구조화는 module `ResultCodeBook`(`config/result_codes.yaml`)이 맡는다. kernel은 module을 import하지 않는다.
- 2026-10-22 시연의 환자 안내 단계(안내 완료·부재 기록)는 A12에 따라 제거했다.
- 공휴일은 `holidays` 패키지에 포함된 KR 데이터만 사용하고 실행 중 내려받지 않는다. 지정 스택에 있던 패키지를 이번에 `pyproject.toml`에 고정했다.
- UUID 합성 12건, 앱별 독립 메모리, 단계 순서·필수값 검증, Jinja 자동 escape, CSRF 확인, 브라우저 캐시 금지, 오류 화면에 입력값 미표시를 적용한다.
- Docker Desktop에서 `internal` network의 포트 게시가 되지 않아 시연 서버는 별도 bridge와 loopback 게시를 사용한다. `app.demo_server`가 Python audit hook으로 DNS 조회·발신 연결·UDP 전송 API를 거부한다. Windows asyncio가 `socket.socketpair`를 loopback 연결로 만들기 때문에 그 호출 안의 loopback 연결만 예외로 둔다. 이것은 이 합성 Python 시연의 발신 제한이며 정식 운영의 OS/네트워크 방화벽을 대신하지 않는다.
- 내부 보안 유지 방법은 [단계별 제안](privacy/internal-security-proposal.md)을 따른다. 이 시연의 통제를 실데이터 운영 준비로 해석하지 않는다.

## 검증 결과 — 2026-10-24

- Python 3.12 + PostgreSQL 16 시험 환경에서 `python -m pytest -q`: **164 통과 / 0 실패**. Excel·DB 환경 40개, 대시보드 81개, 진료일 13개, 결과 표기 25개, 시연 발신·Compose 경계 5개다.
- 실제 Chromium(1366px): 병 수 불일치 거부 → 인계 완료(접수·인계·인수 3자 표시) → 지연 건 결과 코드·Sydney 입력 → 원장 지시 대기 이동 → 재검 대상 정렬을 확인했다.
- 개인정보 요구 P1~P14 중 실제 환자용 인증·접속/감사기록·HTTPS·파기·백업 등은 후속 구현이다.

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
