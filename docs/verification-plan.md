# 검증 계획 — 기술·운영·법적 확인 분리

**현재는 Phase 0 문서만 있다. 아래 테스트 이름은 계획이며 통과 실적이 아니다.** Phase 1~5 실행은 별도 승인 뒤 진행한다.

## 완료 증거의 세 종류

| 유형 | 증거 | 통과로 말할 수 있는 범위 |
|---|---|---|
| TECH | 실제 PostgreSQL·HTTP proxy·브라우저·암호화 도구 자동 테스트, 명령·버전·건수·coverage 기록 | 검증한 코드·설정의 기술 동작 |
| OPS | 다른 원내 업무 PC HTTPS·루트 신뢰, 방화벽·IP·OS, 백업 키·복원·수기 전환·교육 기록 | 해당 원내 환경의 운영 준비 |
| LEGAL | 책임자·보유근거·로그 식별·백업 잔존·파기 방법·정책에 대한 원장 결재·필요한 전문 확인 | 승인 범위의 정책 확인. 자동 테스트로 대체 불가 |

이번 실행에서는 OPS/LEGAL을 수행하지 않는다. 설계 문서 정합성 검사는 TECH 구현 성공과 구분한다.

## Phase별 핵심 테스트

| 단계 | 테스트 | 기대 증거 |
|---|---|---|
| 1 | migrations up/down/up, role grants, YAML↔ORM↔DDL, PK/timestamps, module boundary | 깨끗한 PostgreSQL16 DB에 적용·되돌리기·재적용, C1~C4 |
| 1 | seed_synthetic | 테스트 이름 접두 30명·시행40·의뢰25, 전 상태 및 BOTH/부분·정정 합성 fixture. 상태 seed도 이후 Engine 또는 승인 migration 경유 |
| 2 | 전이 표의 모든 행 성공·권한/guard/사유 실패, 나머지 미등록 전이 실패 | from/to뿐 아니라 action별 검사, rollback 시 Audit·상태 모두 원자성 |
| 2 | ORM 할당·bulk/raw SQL·초기 DRAFT 외 INSERT·가짜 전이 함수 인자 | 서비스·Engine 경유 강제, 전이·Audit 우회 거부 |
| 2 | VIEW/PRINT/CREATE/UPDATE/LOGIN/LOGOUT/FAIL/DENIED 로그·필수 항목 | 목록에 반환된 환자별 기록, 실패 actor 및 환자 없는 사유 |
| 2 | app 계정 로그 UPDATE/DELETE/TRUNCATE, migrator 변조 후 검증기 | 권한 오류, 단일행/중간삭제/마지막삭제/순서/전체 재작성+checkpoint 탐지 |
| 3 | R01~08 각각 발생/미발생/해소, idempotency, DISMISSED 유지·해소·재발 | 연속2회 Task 수 불변, 회차 변경 신규 업무, Rule 실패 시 해소 안 함 |
| 3 | KR 공휴일 2026-10-09·일요일·임시휴진·수토 반일·UTC/KST 경계 | 고정 Clock으로 결정적 검증, 기한 직전/동일/직후 |
| 3/4 | 수정 E2E 2026-11-05→2027-10-18, partial/정정·F/U 재검토 | rules.md의 상태·회차·Task·기한 일치 |
| 4 | password/CSRF/cookie/5회 잠금/15분 idle/IP spoof/role matrix | 실제 쿠키·거부 로그·권한 말소 즉시 적용, HTMX polling idle 미연장 |
| 4 | privacy 화면·인쇄·기본 마스킹·Export 없음 | 책임자만 접근, 대량 경고·점검 이력 |
| 5 | ignore sentinel를 DB 전체 TEXT/JSON·Audit/로그·preview·오류에서 검색, spool 감시 | 무시 값·원본 파일·원본 해시 미저장, 업로드 디스크 쓰기 없음 |
| 5 | purge approval/manifest 변경/활성 의존성/rollback/재시도/복원 재파기 | 대상 hard delete, 별도 기록·보유 정책 일치. 물리 파기는 OPS/LEGAL 추가 |
| 5 | encrypted backup/decrypt/restore/변조/실패 파이프/만료/symlink·junction 우회 | 평문 dump 없음, PostgreSQL 실제 복원, 실패 상태 표시 |
| 5 | 실제 Caddy HTTP redirect/HTTPS, compose ports, 외부 통신 차단 | app/postgres host port 없음, DB만 허용하고 egress 0 |

Import의 sentinel 미저장 시험은 파서 내부에서 해당 값이 한 번도 읽히지 않았다는 증거가 아니다. P14의 해석 충돌(Q16)을 먼저 확정하고 그 범위에 맞는 입력 정책·검증을 추가한다.

## 네트워크 차단 시험의 정확한 뜻

`socket`을 무조건 전부 막으면 PostgreSQL 테스트도 실행되지 않는다. 목적지 allowlist에 전용 테스트 DB 내부 주소·port와 테스트 harness loopback만 허용하고 그 외 IPv4/IPv6·DNS·HTTP·직접 socket 접속을 실패시키는 pytest fixture를 사용한다. app은 DB에 정상 연결한 상태로 전체 pytest를 통과해야 한다.

Python monkeypatch만으로 Caddy·하위 프로세스·브라우저 egress까지 검증했다고 주장하지 않는다. Docker internal network·host firewall 아래 앱 기동·브라우저 폼·백업 도구를 실행하고 외부 TCP/UDP/DNS/HTTP probe와 네트워크 관찰을 함께 기록한다. 외부 리소스 URL을 HTML·CSS·JS에서 검사한다. 패키지·이미지 설치는 사전 단계이며 runtime 측정에서 분리한다.

## Coverage

최종 pytest는 `app/kernel`, `app/modules`에 대해 총합과 각 디렉터리 90% 이상을 요구한다. branch coverage도 산출하고 핵심 보안 경로는 명시적인 실패 테스트를 둔다. pytest-cov/coverage는 **시험용 추가 의존성 제안**이며 production 설치 대상이 아니다. 현재 tests와 앱이 없어 coverage는 N/A이며 0개 통과를 성공으로 보지 않는다.

## 향후 명령 계약 — Windows PowerShell, 아직 실행 불가

Phase 1 승인 후 Compose에 `test` profile을 만들고 pytest/migrator가 내부 전용 PostgreSQL에 연결하도록 한다. production 볼륨을 공유하지 않으며 시험 profile의 단명 컨테이너는 상시 서비스에 포함하지 않는다. 다음은 그때 제공해야 할 명령 계약이다.

```powershell
# Phase 1: 합성 테스트 DB 전용. profile과 서비스 생성 후에만 실행한다.
docker compose --profile test up -d postgres-test
docker compose --profile test run --rm test alembic upgrade head
docker compose --profile test run --rm test alembic downgrade base
docker compose --profile test run --rm test alembic upgrade head
docker compose --profile test run --rm test python scripts/seed_synthetic.py
docker compose --profile test run --rm test pytest tests/contracts -q

# Phase 2~5: 각 구현과 승인 후 추가한다.
docker compose --profile test run --rm test pytest --cov=app/kernel --cov=app/modules --cov-branch --cov-report=term-missing --cov-fail-under=90
docker compose --profile test run --rm test python scripts/verify_access_log.py
docker compose config
```

자격증명은 env/보호된 secret 파일로 주입하고 DSN을 명령행·로그에 출력하지 않는다. 테스트 종료 시 볼륨 삭제 명령을 자동 실행하지 않는다. 실제 DB·백업·LAN 배포 명령은 이번 Phase에서 제공·실행하지 않는다.

## 현재 문서 확인 — 바로 실행 가능

```powershell
Get-ChildItem .\docs -Recurse -File
Get-Content -Encoding UTF8 .\docs\phase-0-report.md
Get-Content -Encoding UTF8 .\docs\open-questions.md
docker version
```

Phase 0 작성 환경의 일회성 YAML·관계·enum·전이·문서 링크 검사 결과는 phase-0-report.md에 기록한다. 이 도구는 `/private/tmp`에만 두며 프로젝트의 앱 코드·테스트·영구 생성기 구현으로 간주하지 않는다. Phase 1에서 생성기와 계약 테스트를 저장소에 만들고 재현 가능한 명령으로 대체한다.
