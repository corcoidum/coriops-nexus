# Ontology 데이터 사전

> 원천: `ontology/coriops.yaml` · SHA-256 `7c89601323c341de2bf088f8aebbc41710b99e016ebff955eab44cd1803746e4`
> `python scripts/gen_docs.py`가 만든 문서다. 직접 고치지 말고 YAML을 고친 뒤 다시 만든다.

실제 운영 흐름(A04~A13)에 맞춘 정식 모델이다. `implemented`는 실제 테이블이 있고 시험(`tests/prototype/test_ontology.py`)이 열·타입·NULL·FK·UNIQUE 일치를 검사한다. `planned`는 표시된 단계에서 구현한다.

## 클래스 한눈에 보기

| 클래스 | 위치 | 상태 | 저장 | 설명 |
|---|---|---|---|---|
| [Staff](#staff) | kernel | 구현됨 | 테이블 `staff` | 직원 개인 계정. 공용 계정을 만들지 않는다 |
| [StaffRole](#staffrole) | kernel | 구현됨 | 테이블 `staff_roles` | 직원 1명의 역할 1개. 원장이 DOCTOR와 PRIVACY_OFFICER를 겸할 수 있다 |
| [PermissionHistory](#permissionhistory) | kernel | 구현됨 | 테이블 `permission_history` | 역할·사용 여부 변경 전후 |
| [AuthSession](#authsession) | kernel | 구현됨 | 테이블 `auth_sessions` | 로그인 세션. 토큰 원문은 저장하지 않는다 |
| [AccessLog](#accesslog) | kernel | 구현됨 | 테이블 `access_logs` | 누가 언제 어느 대상에 무엇을 했는지 한 줄. 해시 사슬로 변조를 찾는다 |
| [AccessLogReview](#accesslogreview) | kernel | 구현됨 | 테이블 `access_log_reviews` | 개인정보 책임자의 접속기록 점검 |
| [Patient](#patient) | kernel | 구현됨 | 테이블 `patients` | 차트번호당 1명. 여러 업무 모듈이 함께 쓴다 |
| [Exam](#exam) | endoscopy_pathology | 구현됨 | 테이블 `exams` | 검사 1건(조직검사·CLO·Stool). 단계는 저장하지 않고 연결된 기록으로 계산한다 |
| [Specimen](#specimen) | endoscopy_pathology | 구현됨 | 테이블 `specimens` | 검사 1건의 검체 묶음과 인계 3자(접수인·인계인·인수인) |
| [ExamResult](#examresult) | endoscopy_pathology | 구현됨 | 테이블 `exam_results` | 결과 1건. 등록 코드 표기만 저장한다(A11) |
| [DoctorReview](#doctorreview) | endoscopy_pathology | 구현됨 | 테이블 `doctor_reviews` | 원장 지시 1건(재검 필요 또는 불필요) |
| [FollowUp](#followup) | endoscopy_pathology | 구현됨 | 테이블 `followups` | 원장이 정한 재검 계획 1건. Stage C에서 Recall로 일반화한다 |
| [Handoff](#handoff) | endoscopy_pathology | 구현됨 | 테이블 `ledger_handoffs` | 하루 한 번 이상의 검체 인계. 병 수 대조 결과를 남긴다 |
| [ImportBatch](#importbatch) | endoscopy_pathology | 구현됨 | 테이블 `ledger_import_batches` | 엑셀 가져오기 1회 |
| [LedgerExport](#ledgerexport) | endoscopy_pathology | 구현됨 | 테이블 `ledger_exports` | 지정 원내 폴더로의 엑셀 출력 1회 |
| [ReportFinding](#reportfinding) | endoscopy_pathology | 구현됨 | `ExamResult.findings` 안의 JSONB | 결과 코드 1개. 예 TA#2(L) = code TA, lesion_count 2, modifiers [L] |
| [SydneyGrading](#sydneygrading) | endoscopy_pathology | 구현됨 | `ExamResult.sydney` 안의 JSONB | Sydney 표기 HP-/Neu++/Mon++/Atr+/IM-의 구조화 |
| [ResultCode](#resultcode) | endoscopy_pathology | 구현됨 | 등록값 `config/result_codes.yaml` | 등록 결과 코드. 화면에서 편집하지 않는다 |
| [Rule](#rule) | kernel | 구현됨 | 테이블 `rules` | 상태·기한·누락을 찾는 규칙 1개. 제목·담당·일수는 config/rules.yaml에서 맞춘다 |
| [RuleRun](#rulerun) | kernel | 구현됨 | 테이블 `rule_runs` | 규칙 실행 1회. 전체(ALL) 또는 방금 바뀐 검사(SUBJECTS) |
| [Task](#task) | kernel | 구현됨 | 테이블 `tasks` | 규칙이 만든 할 일 1건. 같은 규칙·대상·기준날짜는 한 번만 |

## 공통 필드

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| id | uuid | 금지 | primary_key=True |
| created_at | timestamptz | 금지 | — |
| updated_at | timestamptz | 금지 | — |

테이블이 있는 모든 클래스에 적용한다.

## 클래스

### Staff

직원 개인 계정. 공용 계정을 만들지 않는다

위치 `kernel` · 구현됨 · 테이블 `staff` · FHIR `Practitioner`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| username | string | 금지 | unique=True |
| display_name | string | 금지 | — |
| password_hash | string | 금지 | secret=True |
| active | boolean | 금지 | — |
| must_change_password | boolean | 금지 | — |
| failed_login_count | integer | 금지 | — |
| locked_until | timestamptz | 허용 | — |

제약: 비밀번호는 argon2id 해시만 저장 / 역할은 StaffRole의 복수 행으로 부여

### StaffRole

직원 1명의 역할 1개. 원장이 DOCTOR와 PRIVACY_OFFICER를 겸할 수 있다

위치 `kernel` · 구현됨 · 테이블 `staff_roles` · FHIR `PractitionerRole`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | FK → Staff (roleOf) |
| role | enum | 금지 | enum StaffRoleCode |

복합 UNIQUE: `staff_id, role`

### PermissionHistory

역할·사용 여부 변경 전후

위치 `kernel` · 구현됨 · 테이블 `permission_history` · FHIR `직접 대응 없음` · 추가만 허용

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | FK → Staff (changesPermissionOf) |
| changed_by | uuid | 허용 | FK → Staff (changedBy) |
| at | timestamptz | 금지 | — |
| before_roles | jsonb | 금지 | — |
| after_roles | jsonb | 금지 | — |
| before_active | boolean | 허용 | — |
| after_active | boolean | 금지 | — |
| reason | string | 금지 | — |

제약: changed_by가 null이면 서버 명령으로 만든 초기 계정 / 최소 3년 보유

### AuthSession

로그인 세션. 토큰 원문은 저장하지 않는다

위치 `kernel` · 구현됨 · 테이블 `auth_sessions` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | FK → Staff (sessionOf) |
| token_hash | string | 금지 | unique=True; secret=True |
| last_activity_at | timestamptz | 금지 | — |
| expires_at | timestamptz | 금지 | — |
| revoked_at | timestamptz | 허용 | — |

### AccessLog

누가 언제 어느 대상에 무엇을 했는지 한 줄. 해시 사슬로 변조를 찾는다

위치 `kernel` · 구현됨 · 테이블 `access_logs` · FHIR `AuditEvent` · 추가만 허용

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| sequence_no | bigint | 금지 | unique=True |
| at | timestamptz | 금지 | — |
| actor_id | uuid | 허용 | FK → Staff (performedBy) |
| actor_label | string | 금지 | — |
| client_ip | string | 금지 | — |
| action | enum | 금지 | enum AccessAction |
| subject_ref | string | 허용 | — |
| target_type | string | 금지 | — |
| detail_count | integer | 허용 | — |
| outcome | string | 금지 | — |
| prev_hash | string | 금지 | — |
| hash | string | 금지 | — |

제약: subject_ref는 대상 1건(차트번호) / 이름·결과·비밀번호 저장 금지 / 최소 2년 보유

### AccessLogReview

개인정보 책임자의 접속기록 점검

위치 `kernel` · 구현됨 · 테이블 `access_log_reviews` · FHIR `직접 대응 없음` · 추가만 허용

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| reviewer_id | uuid | 금지 | FK → Staff (reviewedBy) |
| reviewed_at | timestamptz | 금지 | — |
| period_start | timestamptz | 금지 | — |
| period_end | timestamptz | 금지 | — |
| last_sequence | bigint | 금지 | — |
| last_hash | string | 금지 | — |
| chain_ok | boolean | 금지 | — |
| bulk_alerts | integer | 금지 | — |
| note | string | 금지 | — |

### Patient

차트번호당 1명. 여러 업무 모듈이 함께 쓴다

위치 `kernel` · 구현됨 · 테이블 `patients` · FHIR `Patient`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| chart_no | string | 금지 | unique=True |
| name | string | 금지 | — |

제약: 같은 차트번호에 다른 이름이 들어오면 덮어쓰지 않고 거부 / 주민번호·연락처·주소는 저장하지 않음 / 성별·나이는 장부 행마다 적힌 값이라 Exam에 둔다

### Exam

검사 1건(조직검사·CLO·Stool). 단계는 저장하지 않고 연결된 기록으로 계산한다

위치 `endoscopy_pathology` · 구현됨 · 테이블 `exams` · FHIR `ServiceRequest / Procedure`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| patient_id | uuid | 금지 | FK → Patient (forPatient) |
| kind | enum | 금지 | enum ExamKind; registry=exam_kinds |
| exam_date | date | 금지 | — |
| procedure_type | enum | 허용 | enum ProcedureType |
| age | integer | 허용 | — |
| sex | enum | 허용 | enum Sex |
| report_ref | string | 허용 | — |
| source | enum | 금지 | enum EntrySource |
| import_batch_id | uuid | 허용 | FK → ImportBatch (importedIn) |
| version | integer | 금지 | — |

복합 UNIQUE: `kind, report_ref`

제약: age는 검사 당시 나이 / sex는 장부 행에 적힌 값 그대로(다른 행으로 채우지 않음) / report_ref는 수탁기관 접수번호 / version은 화면 동시 수정 확인용

### Specimen

검사 1건의 검체 묶음과 인계 3자(접수인·인계인·인수인)

위치 `endoscopy_pathology` · 구현됨 · 테이블 `specimens` · FHIR `Specimen`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| exam_id | uuid | 금지 | FK → Exam (collectedIn); unique=True |
| specimen_count | integer | 허용 | — |
| site | string | 금지 | — |
| handoff_id | uuid | 허용 | FK → Handoff (handedOverIn) |
| registered_by | string | 금지 | — |
| handed_by | string | 금지 | — |
| received_by | string | 금지 | — |
| entrusted_on | date | 허용 | — |

제약: specimen_count는 1~99병 / 인계 시 장부 병 수와 확인 병 수가 같아야 기록

### ExamResult

결과 1건. 등록 코드 표기만 저장한다(A11)

위치 `endoscopy_pathology` · 구현됨 · 테이블 `exam_results` · FHIR `DiagnosticReport`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| exam_id | uuid | 금지 | FK → Exam (resultOf); unique=True |
| reported_on | date | 허용 | — |
| result_code | string | 금지 | — |
| findings | jsonb | 금지 | items=ReportFinding |
| sydney | jsonb | 금지 | items=SydneyGrading |
| review_codes | jsonb | 금지 | — |

제약: 판독문 원문·자유서술 저장 금지 / 조직검사는 findings·CLO·Stool은 20자 이내 판정 result_code / review_codes는 사람이 확인할 표기 문제(미등록 코드 등)

### DoctorReview

원장 지시 1건(재검 필요 또는 불필요)

위치 `endoscopy_pathology` · 구현됨 · 테이블 `doctor_reviews` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| exam_id | uuid | 금지 | FK → Exam (reviews); unique=True |
| decided_at | timestamptz | 금지 | — |
| decided_by | string | 허용 | — |
| no_followup_reason | string | 금지 | — |

제약: 재검 필요 여부와 날짜는 원장이 정하며 시스템이 추천·계산하지 않음 / decided_by가 null이면 Stage A 이전 자료(기록자 미보존)

### FollowUp

원장이 정한 재검 계획 1건. Stage C에서 Recall로 일반화한다

위치 `endoscopy_pathology` · 구현됨 · 테이블 `followups` · FHIR `ServiceRequest`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| review_id | uuid | 금지 | FK → DoctorReview (plannedBy); unique=True |
| due_on | date | 금지 | — |
| done_on | date | 허용 | — |
| done_by | string | 허용 | — |

제약: 재검 계획이 있으면 DoctorReview.no_followup_reason은 빈 값 / done_on은 오늘 이전

### Handoff

하루 한 번 이상의 검체 인계. 병 수 대조 결과를 남긴다

위치 `endoscopy_pathology` · 구현됨 · 테이블 `ledger_handoffs` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| handed_at | timestamptz | 금지 | — |
| registered_by | string | 금지 | — |
| handed_by | string | 금지 | — |
| receiver_name | string | 금지 | — |
| specimen_count | integer | 금지 | — |
| case_count | integer | 금지 | — |

### ImportBatch

엑셀 가져오기 1회

위치 `endoscopy_pathology` · 구현됨 · 테이블 `ledger_import_batches` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| committed_at | timestamptz | 금지 | — |
| digest | string | 금지 | unique=True |
| accepted | integer | 금지 | — |
| skipped | integer | 금지 | — |
| sheet_counts | jsonb | 금지 | — |

제약: 원본 파일·파일명·비고 열·셀 값 저장 금지 / 같은 내용 재저장은 digest로 거부

### LedgerExport

지정 원내 폴더로의 엑셀 출력 1회

위치 `endoscopy_pathology` · 구현됨 · 테이블 `ledger_exports` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| exported_at | timestamptz | 금지 | — |
| file_name | string | 금지 | — |
| row_count | integer | 금지 | — |

제약: CORIOPS_EXPORT_DIR 안의 새 파일만 / 링크·클라우드 동기화 경로 거부

### ReportFinding

결과 코드 1개. 예 TA#2(L) = code TA, lesion_count 2, modifiers [L]

위치 `endoscopy_pathology` · 구현됨 · `ExamResult.findings` 안의 JSONB · FHIR `DiagnosticReport.conclusionCode`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| code | string | 금지 | registry=result_codes |
| lesion_count | integer | 허용 | — |
| modifiers | jsonb | 금지 | registry=result_modifiers |
| registered | boolean | 금지 | — |

제약: 미등록 코드는 registered=false로 보관하고 확인 대상으로 표시(Q19)

### SydneyGrading

Sydney 표기 HP-/Neu++/Mon++/Atr+/IM-의 구조화

위치 `endoscopy_pathology` · 구현됨 · `ExamResult.sydney` 안의 JSONB · FHIR `Observation`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| h_pylori | enum | 허용 | enum SydneyGrade |
| neutrophil | enum | 허용 | enum SydneyGrade |
| mononuclear | enum | 허용 | enum SydneyGrade |
| atrophy | enum | 허용 | enum SydneyGrade |
| intestinal_metaplasia | enum | 허용 | enum SydneyGrade |

제약: 위 검체에만 허용 / 미기재 항목은 넣지 않으며 NEG로 추정 금지

### ResultCode

등록 결과 코드. 화면에서 편집하지 않는다

위치 `endoscopy_pathology` · 구현됨 · 등록값 `config/result_codes.yaml` · FHIR `CodeSystem.concept`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| code | string | 금지 | unique=True |
| label | string | 허용 | — |
| scope | enum | 허용 | enum ResultCodeScope |
| severity_tier | enum | 허용 | enum ResultSeverityTier |

제약: label·scope·severity_tier는 Q19 약어 사전 확정 전 null / severity_tier는 화면 정렬·강조 전용이며 재검 필요 여부·기한 결정에 사용 금지

### Rule

상태·기한·누락을 찾는 규칙 1개. 제목·담당·일수는 config/rules.yaml에서 맞춘다

위치 `kernel` · 구현됨 · 테이블 `rules` · FHIR `PlanDefinition`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| rule_id | string | 금지 | unique=True |
| params | jsonb | 금지 | — |
| enabled | boolean | 금지 | — |
| config_hash | string | 금지 | — |

제약: 설정에서 빠진 규칙은 지우지 않고 끈다(기존 할 일의 출처 보존)

### RuleRun

규칙 실행 1회. 전체(ALL) 또는 방금 바뀐 검사(SUBJECTS)

위치 `kernel` · 구현됨 · 테이블 `rule_runs` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| evaluated_at | timestamptz | 금지 | — |
| finished_at | timestamptz | 금지 | — |
| scope | enum | 금지 | enum RuleRunScope |
| status | enum | 금지 | enum RuleRunStatus |
| config_hash | string | 금지 | — |
| candidate_count | integer | 금지 | — |
| created_count | integer | 금지 | — |
| resolved_count | integer | 금지 | — |
| error_code | string | 허용 | — |

제약: 이름·차트번호를 기록하지 않음 / 실패해도 업무 기록은 되돌리지 않고 실패만 남김

### Task

규칙이 만든 할 일 1건. 같은 규칙·대상·기준날짜는 한 번만

위치 `kernel` · 구현됨 · 테이블 `tasks` · FHIR `Task`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| rule_id | uuid | 금지 | FK → Rule (createdBy) |
| run_id | uuid | 금지 | FK → RuleRun (openedIn) |
| subject_type | string | 금지 | — |
| subject_id | uuid | 금지 | — |
| dedupe_key | string | 금지 | unique=True |
| title | string | 금지 | — |
| priority | enum | 금지 | enum TaskPriority |
| assignee_role | enum | 금지 | enum StaffRoleCode |
| opened_at | timestamptz | 금지 | — |
| due_at | timestamptz | 금지 | — |
| status | enum | 금지 | enum TaskStatus |
| resolved_at | timestamptz | 허용 | — |
| resolved_by | string | 허용 | — |
| resolution_note | string | 금지 | — |

제약: dedupe_key={rule_id}:{subject_type}:{subject_id}:{anchor} / 제목은 고정 문구이며 이름·차트번호·결과 금지 / OPEN이면 resolved_at 없음 / 사람이 닫은(DONE·DISMISSED) 키는 조건이 남아도 다시 만들지 않음 / DISMISSED는 사유 필수

## Enum

| 이름 | 값 |
|---|---|
| StaffRoleCode | DOCTOR, ADMIN, NURSE, PRIVACY_OFFICER |
| Sex | M, F |
| ExamKind | BIOPSY, CLO, STOOL |
| ProcedureType | stomach, colon |
| EntrySource | MANUAL, IMPORT, SEED |
| AccessAction | LOGIN, LOGOUT, LOGIN_FAIL, DENIED, LIST, VIEW, CREATE, UPDATE, IMPORT, EXPORT, ACCOUNT, LOG_VIEW, LOG_REVIEW |
| ExamStage | HANDOFF_PENDING, RESULT_PENDING, DOCTOR_PENDING, FOLLOWUP, CLOSED |
| ResultCodeScope | UPPER_GI, LOWER_GI, ANY |
| ResultSeverityTier | ROUTINE, ATTENTION, CRITICAL |
| SydneyGrade | NEG, POS1, POS2, POS3 |
| RuleRunStatus | SUCCEEDED, FAILED |
| RuleRunScope | ALL, SUBJECTS |
| TaskPriority | NORMAL, HIGH, URGENT |
| TaskStatus | OPEN, DONE, DISMISSED, AUTO_RESOLVED |

## 등록값

| 이름 | 원천 | 키 | 소유 |
|---|---|---|---|
| result_codes | `config/result_codes.yaml` | `codes` | endoscopy_pathology |
| result_modifiers | `config/result_codes.yaml` | `modifiers` | endoscopy_pathology |
| exam_kinds | `config/ledger_app.yaml` | `kinds` | endoscopy_pathology |
| permissions | `config/security.yaml` | `authentication.permissions` | kernel |

## 전환기 테이블

없음

## 규칙

- `timestamps`: UTC 저장, Asia/Seoul 표시, Clock 주입
- `immutable_tables`: 추가만 하며 UPDATE·DELETE·TRUNCATE는 DB 트리거가 거부
- `identifiers`: chart_no는 속성이며 PK 또는 FK로 사용 금지
- `nullable`: 필드의 nullable 생략은 false
- `enum_storage`: PostgreSQL TEXT(+ CHECK)
- `status`: implemented는 실제 테이블과 시험으로 일치를 검사, planned는 해당 단계에서 구현
- `generated_docs`: docs/ontology.md·erd.md·state-machine.md·fhir-mapping.md는 scripts/gen_docs.py가 만든다
