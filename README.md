# CoriOps Nexus v0.1

내시경 검체 채취 → 수탁 의뢰 → 결과 수신 → 원장 확인 → 환자 안내 → F/U 등록을 관리할 원내 LAN 전용 보조 업무대장이다. 진단·치료·F/U 주기는 원장이 결정한다. 결과 원문, 연락처, 주소, 주민등록번호, 보험정보는 저장하지 않는다.

**지금은 수동 입력으로 첫 화면을 확인한다.** 씨젠은 직접 확인하고 기존 Excel 장부는 평소대로 관리한다. 자동 로그인·약어 자동 변환은 뒤로 미룬다. 약어 사전 없이 합성 자료 8건으로 결과 입력 → 원장 지시 기록 → 환자 안내 흐름을 눌러볼 수 있다.

```sh
docker compose -f docker-compose.prototype.yml --profile dashboard up -d --build dashboard
```

브라우저: <http://127.0.0.1:8765/dashboard> · [수동 대시보드 사용법](docs/manual-dashboard.md)

**합성 시연 전용이며 재시작하면 입력이 초기화된다.** 실제 자료 입력·인증·영구 DB 저장·접속/감사기록·LAN 운영은 정식 앱에서 구현할 후속 범위다. 아래는 최초 Phase 0 설계 기록이며 오늘 시연을 위해 모든 문서를 먼저 검토할 필요는 없다. [17열 Excel 프로토타입](docs/excel-prototype.md)도 유지한다.

GitHub 저장소: [corcoidum/coriops-nexus](https://github.com/corcoidum/coriops-nexus). Phase 1은 확인 질문과 승인 후 시작한다.

2026-10-22 업무 확인: 씨젠의 환자별 전체 결과 공개 후 사무장·지정 직원 1명이 확인하고 필요한 내용을 원장에게 보고한다. 전건 원장 확인을 전제했던 YAML·상태 머신·R03은 [Q17의 후속 처리 기준](docs/open-questions.md)을 확인한 뒤 수정할 이전 검토안이다.

같은 날 제안한 씨젠 자동 조회·Excel 갱신 설계 [ADR-005](docs/decisions/ADR-005-seegene-excel-integration.md)는 보류한다. 환자별 다음 내시경 시점은 원장이 결정하며, 첫 화면에서는 사람이 그 날짜를 입력한다.

2026-10-25: 검진 혈액검체 결과 대장을 조직검체 대장과 별도 모듈로 진행하는 [계획 초안](docs/blood-ledger-plan.md)을 추가했다. 열 목록 확인(B01~B06) 전에는 코드를 작성하지 않는다.

## 먼저 검토할 문서

1. [명세 충돌 8개와 결정 상태](docs/conflict-resolution.md)
2. [Phase 1 전 확인할 질문](docs/open-questions.md)
3. [Phase 0 검증 보고](docs/phase-0-report.md)
4. [데이터 사전](docs/ontology.md), [ERD](docs/erd.md), [상태 머신](docs/state-machine.md), [Rule](docs/rules.md)
5. [서비스·권한·트랜잭션 설계](docs/architecture.md)
6. [개인정보 대응표](docs/privacy/compliance-matrix.md), [보유·파기 초안](docs/privacy/retention-policy.md)
7. [확장 계약·Phase Gate](docs/roadmap.md), [검증 계획](docs/verification-plan.md)

`ontology/coriops.yaml`이 클래스·속성·enum·관계·FHIR 대응·전이의 단일 원천이다. `docs/ontology.md`, `erd.md`, `state-machine.md`, `fhir-mapping.md`는 이 파일에서 일회성 로컬 도구로 만든 스냅샷이다. 영구 생성기 `scripts/gen_docs.py`와 재생성 검사는 Phase 1에서 작성한다. `config/`는 설계 데이터이며 실행 설정으로 사용하지 않는다.

## 지정 기술 스택

Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / PostgreSQL 16 + psycopg 3 / Jinja2 + HTMX + Alpine.js / APScheduler / holidays / openpyxl / argon2-cffi / pytest / Docker Compose + Caddy. SQLite·Redis·외부 API·AI 기능을 추가하지 않는다.

Alembic은 DB 구조 변경을 순서가 있는 파일로 관리하는 도구다. Phase 1에서 `upgrade`로 적용하고 `downgrade`로 되돌리는 과정을 PostgreSQL에 검증한다.

선언형 상태 머신은 상태 전이를 조건문 곳곳에 흩어놓지 않고 표로 정의한다. 공통 Engine이 표의 권한·사유·조건을 검사해 변경과 감사기록을 한 트랜잭션에 저장한다.

## 지금 가능한 확인 — Windows PowerShell

저장소를 받은 폴더에서 실행한다. Python·패키지·DB가 없어도 설계 문서를 확인할 수 있다.

```powershell
Get-Content -Encoding UTF8 .\docs\phase-0-report.md
Get-Content -Encoding UTF8 .\docs\conflict-resolution.md
Get-Content -Encoding UTF8 .\docs\open-questions.md
Get-Content -Encoding UTF8 .\ontology\coriops.yaml
docker version
```

현재 실행은 `docker-compose.prototype.yml`을 사용한다. [첫 대시보드](docs/manual-dashboard.md) 또는 [Excel 프로토타입](docs/excel-prototype.md)을 시험·시연할 수 있으며, 정식 앱의 Alembic 마이그레이션은 아직 준비되지 않았다. 전체 검증 계획은 [검증 계획](docs/verification-plan.md)을 참고한다.

## 배포 전에 확인할 운영 절차 — 아직 실행하지 않음

Phase 5에서 Caddy `tls internal`로 원내 인증서를 발급하고 HTTP를 HTTPS로 리다이렉트한다. 다른 업무 PC에는 **공개 루트 인증서만** 전달한다. 원장이 대조한 SHA-256 지문과 일치하는지 확인한 후 `certlm.msc` → 신뢰할 수 있는 루트 인증 기관 → 인증서 가져오기를 사용한다. 개인키·CA 키는 배포하지 않는다. 실제 SAN/서버 주소로 접속해 인증서 경고 없음·리다이렉트·쿠키 속성을 검증한다. [Caddy 공식 문서](https://caddyserver.com/docs/automatic-https)

서버 주소·업무 PC IP·방화벽·루트 신뢰·백업 매체·복원 리허설은 원내 운영 증거가 있어야 완료다. 자동 테스트 성공만으로 LAN 배포 또는 법적 적합성을 완료 처리하지 않는다.

개발·시연은 이름이 `테스트`로 시작하는 합성 데이터만 사용한다. 개인정보 문서는 **법률 자문이 아닌 초안이며 원장 결재·확인이 필요**하다.
