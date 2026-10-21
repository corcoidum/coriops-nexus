# Phase 0 검토 보고

작성일: 2026-10-21 (Asia/Seoul). 상태: **설계 산출물 작성 완료, 미확정 결정·승인 대기. Phase 1 미착수.**

## [완료] 만든 파일

| 묶음 | 파일 |
|---|---|
| 진입·보호 | README.md, .gitignore |
| 원천·설계 설정 | ontology/coriops.yaml; config/clinic.yaml, rules.yaml, security.yaml, import_mapping.yaml |
| YAML 파생 스냅샷 | docs/ontology.md, erd.md, state-machine.md, fhir-mapping.md |
| 설계·결정 | docs/architecture.md, conflict-resolution.md, open-questions.md, rules.md, roadmap.md, backlog.md, ui-flow.md, verification-plan.md, phase-0-report.md |
| ADR | docs/decisions/ADR-001-postgresql.md, ADR-002-graph-strategy.md, ADR-003-tls-caddy.md, ADR-004-module-boundary.md |
| 개인정보 초안 | docs/privacy/compliance-matrix.md, retention-policy.md, backup-recovery.md, access-log-review.md, incident-response.md, internal-plan-addendum.md, processing-policy-checklist.md |

총 31파일. 28클래스, 28명명 관계, 24전이, PATH.R01~R08을 정의했다. 모든 클래스에 UUID PK·공통 timestamp를 선언했다. 추가 클래스는 역할·세션·다형 참조·회차·보고서 coverage·로그 점검·파기·Import 최소 메타데이터용이며 미래 모듈 구현이 아니다.

## [결정·근거]

- **확정:** 사용자 답변 A01에 따라 R03/R04/R06 즉시 생성, 기한과 지연 판정 분리. E2E R06을 '2 진료일 후 생성'에서 '기존 Task 지연'으로 수정했다.
- **확정:** A02에 따라 검체별 결과 coverage·보고서 버전·정정 시 새 회차/재확인/재안내·기존 F/U 재검토를 설계했다.
- **제안:** dedupe에 WorkCycle UUID 추가, 복수 역할 StaffRole, SubjectReference 복합 FK·deferred 검사, F/U REQUIRED/NOT_REQUIRED 명시 필드.
- **제안:** 무인 암호화와 서버 개인키 미보관을 양립시키는 age 공개키 백업. 키·잔존은 미승인이다.
- 지정 스택은 변경하지 않았다. 새 production 패키지 설치 0개. YAML 검증 전용 PyYAML 6.0.3을 `/private/tmp/coriops-nexus-phase0-tools` 임시 venv에만 설치했다. 향후 runtime YAML용 PyYAML과 시험용 pytest-cov는 명시적인 추가 의존성 제안이다.
- Git 저장소가 아닌 빈 작업 폴더에서 시작했다. Git 초기화·커밋·원격 연결·앱/DB 코드 작성·컨테이너 배포는 수행하지 않았다.

## [가정]과 미확정 결정

전체 원문 Assumptions 12항목을 open-questions.md에 옮겼다. 일반 기본값과 Phase 1 전에 필요한 결정을 구분했다.

| Gate | 필요한 답 |
|---|---|
| Q01 | 원장 복수 역할·계정관리자·자기 승인 범위 |
| Q02 | 부분 결과 조기 원장 전달·미발행·부적합·재채취 절차 |
| Q04 | NEXT_VISIT 안내 기한·NONE 승인·F/U 취소와 종결 조건 |
| Q06 | 로그 식별 연결·보유기간·백업 잔존·물리 잔존 포함 파기 방법 |
| Q09 | age 공개키 백업·오프라인 개인키·분실 및 복원 담당 |
| Q16 | Import ignore의 앱 처리 금지와 openpyxl 내부 읽기 금지 중 요구 범위 |

Q06은 사용자 답변 A03에 따라 원장 확인 대상으로 남겼다. 법적 적정성·30일 잔존이 승인된 것으로 처리하지 않았다. 업무 누락·파기에 영향을 주는 항목은 config 기본값으로 확정하지 않았다.

## [검증] 실행 증거

최종 정적 검사 결과는 아래에 기록한다. 테스트 파일·앱·마이그레이션·Compose는 이번 Phase에 만들지 않았다. 따라서 pytest·coverage·PostgreSQL 기능·보안 통과를 주장하지 않는다.

| 명령·확인 | 결과 |
|---|---|
| `docker version` | 성공: Docker Client/Engine 29.8.0, Docker Desktop 4.91.0. daemon 접근 확인만 수행 |
| `python3 -c ...` 환경 확인 | 호스트 Python 3.14.3, 전역 PyYAML 없음. 일회성 검사 venv로 해결. 앱 목표 Python은 3.12 유지 |
| 임시 venv에 `pip install PyYAML==6.0.3` | 성공. 설치 단계 네트워크만 사용, runtime 앱은 없음 |
| 임시 `coriops_phase0_docs.py` | YAML에서 데이터 사전·ERD·상태도·FHIR 4개 문서 생성 |
| 임시 `coriops_phase0_check.py` | 정적 검사 **35 통과 / 0 실패**. YAML 5개, enum/FK/관계/전이 참조·회차 key·8 Rule·문서 링크·원천 hash·재생성 동일성 확인 |
| `git status --short` | 실패: 빈 폴더에 .git 없음. 기존 변경 충돌 없음, 초기화하지 않음 |
| pytest / Alembic / DB 권한 / verify_access_log / backup restore / Compose up | **미실행 — Phase 1~5 대상**, 통과/실패 건수 N/A |
| app/kernel·modules coverage | **N/A — 코드 미작성** |

일회성 도구 위치는 `/private/tmp`이며 repository에 Python 구현을 추가하지 않았다. 문서 생성 및 정합성 검사는 실제 PostgreSQL 계약 테스트를 대신하지 않는다. 실행·빌드 산출물은 없다.

작성 환경에서 실제 실행한 생성·검사 명령(macOS, 임시 도구):

```sh
/private/tmp/coriops-nexus-phase0-tools/bin/python /private/tmp/coriops_phase0_docs.py
/private/tmp/coriops-nexus-phase0-tools/bin/python /private/tmp/coriops_phase0_check.py
```

검사 결과: `RESULT: 35/35 passed; files=31, yaml=5, classes=28, relations=28, transitions=24`. 이는 pytest 35개 통과라는 뜻이 아니다.

## [개인정보]

P1~P14 각각을 compliance-matrix.md의 설계·계획 테스트 이름·Phase·증거 유형에 매핑했다. **이번 Phase에서 구현·테스트로 충족한 P 항목은 0개**다. 로그 append-only와 파기, 백업 잔존, DELETE의 물리 복구 한계를 명시했다. 법적 자료는 공식 출처만 확인했으며 해석·도입 결재는 남았다. 개인정보 문서 전체에 초안·원장 확인 필요를 표시했다.

## [확장 계약]

C1~C8 설계상 위반은 발견하지 않았다. 모듈·원천 YAML·UUID·범용 엔티티·전이·Rule registry·Importer·Actor/서비스 계약과 계획 테스트를 roadmap.md에 정의했다. **구현 검증은 아직 N/A**다. 커널 import·라우트 DB 우회가 없는 앱을 만들었다고 주장하지 않는다.

## [실행 방법] Windows + Docker Desktop

```powershell
Get-Content -Encoding UTF8 .\README.md
Get-Content -Encoding UTF8 .\docs\conflict-resolution.md
Get-Content -Encoding UTF8 .\docs\open-questions.md
Get-Content -Encoding UTF8 .\docs\privacy\compliance-matrix.md
docker version
```

현재 실행 가능한 범위는 문서 검토와 Docker 환경 확인이다. 향후 승인 후 제공할 DB/pytest 명령은 verification-plan.md에서 '아직 실행 불가'로 구분했다.

## [리스크]

- 사용자 승인된 결과 버전·Task 시점 외 나머지 업무·권한·파기 제안은 미확정이다.
- SQL DELETE만으로 WAL/디스크/백업까지 복구 불가를 입증할 수 없다. 파기 완료의 법적·운영 기준을 먼저 확정해야 한다.
- P14의 파서 내부 무시 값 읽기까지 금지하는 해석은 openpyxl의 sharedStrings 선로딩과 충돌한다. Q16 요구 정의를 확정하기 전 충족 가능하다고 처리하지 않는다.
- root 신뢰·IP·방화벽·백업 복원·현장 업무 PC·실제 PostgreSQL은 아직 확인하지 않았다.
- .gitignore는 실수 예방이며 이미 포함된 파일을 지우는 수단이나 접근 통제가 아니다. 실제 환자 파일을 받거나 처리하지 않았다.
- 실제 LAN 배포와 실데이터 사용은 이번 실행 범위 밖이다.

## [다음 Phase] 미리보기

1. Gate 질문 답변과 Phase 0 승인 후에만 Python 3.12·PostgreSQL 16 모델과 마이그레이션을 시작한다.
2. DB 역할·UUID·FK·Ontology 계약 테스트, 문서 생성기와 합성 seed를 만든다.
3. up/down/up·모델 계약·합성 분포 증거를 보고하고 다시 멈춘다.

명시된 중단 근거: 목표 파일 R-9의 **“각 Phase 종료 시 멈추고 보고하고, 승인 후 다음 Phase로 간다”**, 마지막 범위의 **“이번 실행 범위는 Phase 0 설계와 충돌 해소 보고까지다.”** 현재 Phase 1로 진행할 승인을 요청·대체한 상태가 아니며 검토 대기 상태로 종료한다.
