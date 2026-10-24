# Ontology 데이터 사전

> 원천: `ontology/coriops.yaml` · SHA-256 `3219555deb849c8c405298597adbeacd79b3032992a172c5bc72bc5559ae6704`
> Phase 0 일회성 로컬 생성 스냅샷. 영구 생성기·CI 일치 검사는 Phase 1 예정. 직접 편집하지 않는다.


## 공통 필드

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| id | uuid | 금지 | primary_key=True |
| created_at | timestamptz | 금지 | — |
| updated_at | timestamptz | 금지 | — |

공통 필드는 연결·보안·로그 테이블에도 모두 적용한다. 불변 테이블은 updated_at=created_at이다.

## 클래스

### Patient

테이블 `patients` · 위치 `kernel` · FHIR `Patient`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| chart_no | string | 금지 | unique=True |
| name | string | 금지 | — |
| birth_date | date | 금지 | — |
| sex | enum | 금지 | enum=Sex |
| status | enum | 금지 | enum=PatientStatus |

제약: 환자 식별 속성은 chart_no·name·birth_date·sex만 허용

### Staff

테이블 `staff` · 위치 `kernel` · FHIR `Practitioner`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| username | string | 금지 | unique=True |
| display_name | string | 금지 | — |
| password_hash | string | 금지 | secret=True |
| active | boolean | 금지 | — |
| failed_login_count | integer | 금지 | — |
| locked_until | timestamptz | 허용 | — |

제약: 개인 계정만 허용 / 역할은 StaffRole의 복수 행으로 부여

### StaffRole

테이블 `staff_roles` · 위치 `kernel` · FHIR `PractitionerRole`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | references=Staff |
| role | enum | 금지 | enum=StaffRoleCode |

복합 UNIQUE: `staff_id, role`

### AuthSession

테이블 `auth_sessions` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | references=Staff |
| token_hash | string | 금지 | unique=True; secret=True |
| last_activity_at | timestamptz | 금지 | — |
| expires_at | timestamptz | 금지 | — |
| revoked_at | timestamptz | 허용 | — |

### SubjectReference

테이블 `subject_references` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| subject_type | string | 금지 | registry=subject_types |
| patient_id | uuid | 금지 | references=Patient |

복합 UNIQUE: `subject_type, id`

제약: id는 실제 대상 엔티티의 UUID와 동일 / 등록된 실제 대상 존재를 커밋 시 검증

### WorkCycle

테이블 `work_cycles` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| subject_type | string | 금지 | registry=subject_types |
| subject_id | uuid | 금지 | — |
| cycle_no | integer | 금지 | — |
| opened_at | timestamptz | 금지 | — |
| ended_at | timestamptz | 허용 | — |
| reason_code | string | 금지 | — |

복합 UNIQUE: `subject_type, subject_id, cycle_no`

### FollowUpKind

테이블 `followup_kinds` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| code | string | 금지 | unique=True |
| owner | string | 금지 | — |
| label | string | 금지 | — |

### FollowUpPlan

테이블 `followup_plans` · 위치 `kernel` · FHIR `ServiceRequest / CarePlan`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| patient_id | uuid | 금지 | references=Patient |
| subject_type | string | 금지 | registry=subject_types |
| subject_id | uuid | 금지 | — |
| source_cycle_id | uuid | 금지 | references=WorkCycle |
| kind | string | 금지 | registry=followup_kinds |
| due_date | date | 금지 | — |
| status | enum | 금지 | enum=PlanStatus |
| review_status | enum | 금지 | enum=PlanReviewStatus |
| revision_no | integer | 금지 | — |
| completed_at | timestamptz | 허용 | — |
| cancellation_reason | string | 허용 | — |

제약: 원장 지정 날짜만 저장 / 정정 시 기존 날짜 자동 변경 금지 / due_date 변경 시 새 WorkCycle

### PatientNotification

테이블 `patient_notifications` · 위치 `kernel` · FHIR `Communication`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| subject_type | string | 금지 | registry=subject_types |
| subject_id | uuid | 금지 | — |
| cycle_id | uuid | 금지 | references=WorkCycle |
| attempt_no | integer | 금지 | — |
| method | enum | 금지 | enum=NotificationMethod |
| attempted_at | timestamptz | 금지 | — |
| outcome | enum | 금지 | enum=NotificationOutcome |
| staff_id | uuid | 금지 | references=Staff |

복합 UNIQUE: `cycle_id, attempt_no`

### Rule

테이블 `rules` · 위치 `kernel` · FHIR `PlanDefinition`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| rule_id | string | 금지 | unique=True |
| params | jsonb | 금지 | — |
| enabled | boolean | 금지 | — |
| config_hash | string | 금지 | — |

### RuleRun

테이블 `rule_runs` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| rule_id | uuid | 금지 | references=Rule |
| actor_type | enum | 금지 | enum=ActorType |
| evaluated_at | timestamptz | 금지 | — |
| finished_at | timestamptz | 허용 | — |
| status | enum | 금지 | enum=RuleRunStatus |
| config_hash | string | 금지 | — |
| candidate_count | integer | 금지 | — |
| error_code | string | 허용 | — |

### Task

테이블 `tasks` · 위치 `kernel` · FHIR `Task`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| rule_id | uuid | 금지 | references=Rule |
| subject_type | string | 금지 | registry=subject_types |
| subject_id | uuid | 금지 | — |
| cycle_id | uuid | 금지 | references=WorkCycle |
| dedupe_key | string | 금지 | unique=True |
| title | string | 금지 | — |
| priority | enum | 금지 | enum=Priority |
| assignee_role | enum | 금지 | enum=StaffRoleCode |
| opened_at | timestamptz | 금지 | — |
| due_at | timestamptz | 금지 | — |
| status | enum | 금지 | enum=TaskStatus |
| resolved_at | timestamptz | 허용 | — |
| condition_cleared_at | timestamptz | 허용 | — |
| resolution_note | string | 허용 | — |

제약: dedupe_key={namespaced_rule_id}:{subject_type}:{subject_id}:{cycle_id} / 제목은 고정 문구로 식별정보 금지

### AuditEvent

테이블 `audit_events` · 위치 `kernel` · FHIR `AuditEvent` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| actor_type | enum | 금지 | enum=ActorType |
| actor_id | uuid | 허용 | references=Staff |
| at | timestamptz | 금지 | — |
| entity_type | string | 금지 | — |
| entity_id | uuid | 금지 | — |
| action | string | 금지 | — |
| before | jsonb | 허용 | — |
| after | jsonb | 허용 | — |
| reason_code | string | 허용 | — |
| reason | string | 허용 | — |
| correlation_id | uuid | 금지 | — |

제약: 상태·기한·분류·UUID 허용목록만 기록 / 이름·차트번호·생년월일·비밀번호·원문 저장 금지

### AccessLogSegment

테이블 `access_log_segments` · 위치 `kernel` · FHIR `직접 대응 없음` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| period_start | timestamptz | 금지 | unique=True |
| period_end | timestamptz | 금지 | — |
| opening_checkpoint | string | 금지 | — |
| previous_segment_hash | string | 허용 | — |

### AccessLog

테이블 `access_logs` · 위치 `kernel` · FHIR `AuditEvent` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| segment_id | uuid | 금지 | references=AccessLogSegment |
| sequence_no | bigint | 금지 | unique=True |
| actor_type | enum | 금지 | enum=ActorType |
| actor_id | uuid | 허용 | references=Staff |
| actor_label | string | 금지 | — |
| at | timestamptz | 금지 | — |
| client_ip | inet | 금지 | — |
| patient_ref | uuid | 허용 | — |
| action | enum | 금지 | enum=AccessAction |
| target_type | string | 금지 | — |
| target_id | uuid | 허용 | — |
| outcome_code | string | 금지 | — |
| correlation_id | uuid | 금지 | — |
| prev_hash | string | 금지 | — |
| hash | string | 금지 | — |

제약: patient_ref는 보유기간 독립인 논리 참조이며 삭제 cascade 금지 / EXPORT는 예약 값이며 기능 없음

### AccessLogReview

테이블 `access_log_reviews` · 위치 `kernel` · FHIR `직접 대응 없음` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| reviewer_id | uuid | 금지 | references=Staff |
| reviewed_at | timestamptz | 금지 | — |
| period_start | timestamptz | 금지 | — |
| period_end | timestamptz | 금지 | — |
| filters | jsonb | 금지 | — |
| last_sequence | bigint | 금지 | — |
| last_hash | string | 금지 | — |
| disposition | enum | 금지 | enum=ReviewDisposition |
| followup_note | string | 허용 | — |

### PermissionHistory

테이블 `permission_history` · 위치 `kernel` · FHIR `직접 대응 없음` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| staff_id | uuid | 금지 | references=Staff |
| changed_by | uuid | 금지 | references=Staff |
| at | timestamptz | 금지 | — |
| before_roles | jsonb | 금지 | — |
| after_roles | jsonb | 금지 | — |
| before_active | boolean | 금지 | — |
| after_active | boolean | 금지 | — |
| reason | string | 금지 | — |

제약: 복수 역할 전체 집합의 전후 비교 / 최소 3년 보유

### PurgeBatch

테이블 `purge_batches` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| requested_by | uuid | 금지 | references=Staff |
| approved_by | uuid | 허용 | references=Staff |
| approved_at | timestamptz | 허용 | — |
| completed_at | timestamptz | 허용 | — |
| status | enum | 금지 | enum=PurgeStatus |
| policy_version | string | 금지 | — |
| manifest_hash | string | 금지 | — |
| error_code | string | 허용 | — |

### PurgeItem

테이블 `purge_items` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| batch_id | uuid | 금지 | references=PurgeBatch |
| subject_type | string | 금지 | — |
| subject_id | uuid | 금지 | — |
| eligibility_snapshot_hash | string | 금지 | — |
| deleted_at | timestamptz | 허용 | — |

제약: 복원 재파기용 최소 UUID 목록의 보유·파기 정책은 Q06 승인 필요

### ImportBatch

테이블 `import_batches` · 위치 `kernel` · FHIR `직접 대응 없음`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| committed_by | uuid | 금지 | references=Staff |
| mapping_version | string | 금지 | — |
| normalized_digest | string | 금지 | unique=True |
| status | enum | 금지 | enum=ImportStatus |
| accepted_count | integer | 금지 | — |
| rejected_count | integer | 금지 | — |

제약: 원본파일·파일명·무시컬럼·원본해시 저장 금지 / 허용 필드 정규화 후 해시

### EndoscopyProcedure

테이블 `endoscopy_procedures` · 위치 `endoscopy_pathology` · FHIR `Procedure`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| patient_id | uuid | 금지 | references=Patient |
| performed_at | timestamptz | 금지 | — |
| type | enum | 금지 | enum=ProcedureType |
| sedation | boolean | 금지 | — |
| performer_id | uuid | 금지 | references=Staff |

### ExternalLab

테이블 `external_labs` · 위치 `endoscopy_pathology` · FHIR `Organization`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| name | string | 금지 | unique=True |
| active | boolean | 금지 | — |

### PathologyRequest

테이블 `pathology_requests` · 위치 `endoscopy_pathology` · FHIR `ServiceRequest`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| procedure_id | uuid | 금지 | references=EndoscopyProcedure; unique=True |
| external_lab_id | uuid | 금지 | references=ExternalLab |
| shipped_at | timestamptz | 허용 | — |
| external_ref | string | 허용 | — |
| status | enum | 금지 | enum=RequestStatus; write_via=WorkflowEngine |
| active_cycle_id | uuid | 금지 | references=WorkCycle |
| current_review_id | uuid | 허용 | references=PhysicianReview |
| version_no | integer | 금지 | — |
| result_complete_at | timestamptz | 허용 | — |
| notified_at | timestamptz | 허용 | — |
| notification_skip_reason | string | 허용 | — |
| notification_waived_at | timestamptz | 허용 | — |
| closed_at | timestamptz | 허용 | — |
| terminal_at | timestamptz | 허용 | — |

복합 UNIQUE: `external_lab_id, external_ref`

제약: id는 SubjectReference의 공유 PK / 처음부터 WorkCycle 동시 생성 / terminal_at은 CANCELLED 또는 LOST 시각

### Specimen

테이블 `specimens` · 위치 `endoscopy_pathology` · FHIR `Specimen`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| procedure_id | uuid | 금지 | references=EndoscopyProcedure |
| request_id | uuid | 금지 | references=PathologyRequest |
| seq_no | integer | 금지 | — |
| site | string | 금지 | — |
| method | enum | 금지 | enum=SpecimenMethod |
| collected_at | timestamptz | 금지 | — |

복합 UNIQUE: `request_id, seq_no`

제약: 동일 procedure 일치 / 발송 후 검체 수 변경은 정정 사유 필요 / site는 해부학 부위만

### PathologyReport

테이블 `pathology_reports` · 위치 `endoscopy_pathology` · FHIR `DiagnosticReport` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| request_id | uuid | 금지 | references=PathologyRequest |
| received_at | timestamptz | 금지 | — |
| report_ref | string | 금지 | — |
| logical_report_key | string | 금지 | — |
| version_no | integer | 금지 | — |
| supersedes_id | uuid | 허용 | references=PathologyReport |
| source | enum | 금지 | enum=ReportSource |
| correction_reason | string | 허용 | — |

복합 UNIQUE: `request_id, logical_report_key, version_no`

제약: 판독문 원문·자유서술 소견·첨부파일 없음 / 결과는 등록 코드(ReportFinding)와 Sydney 등급(SydneyGrading)만 저장 / 정정 버전은 이전 버전 전체 coverage와 결과 코드를 명시적으로 대체

### ReportSpecimen

테이블 `report_specimens` · 위치 `endoscopy_pathology` · FHIR `DiagnosticReport.specimen` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| report_id | uuid | 금지 | references=PathologyReport |
| specimen_id | uuid | 금지 | references=Specimen |

복합 UNIQUE: `report_id, specimen_id`

제약: 동일 의뢰 내 검체만 / 보고서 한 버전은 검체 한 개 이상 포함

### ResultCode

테이블 `result_codes` · 위치 `endoscopy_pathology` · FHIR `CodeSystem.concept`

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| code | string | 금지 | unique=True |
| label | string | 허용 | — |
| scope | enum | 허용 | enum=ResultCodeScope |
| severity_tier | enum | 허용 | enum=ResultSeverityTier |
| active | boolean | 금지 | — |

제약: config/result_codes.yaml에서 적재하며 화면 편집 없음 / label·scope·severity_tier는 Q19 약어 사전 확정 전 null / severity_tier는 화면 정렬·강조 전용이며 임상 판단·F/U 필요성·기한 자동 결정에 사용 금지 / 코드 추가·tier 변경은 원장 승인 후 config 변경 절차

### ReportFinding

테이블 `report_findings` · 위치 `endoscopy_pathology` · FHIR `DiagnosticReport.conclusionCode` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| report_id | uuid | 금지 | references=PathologyReport |
| display_order | integer | 금지 | — |
| result_code | string | 금지 | registry=result_codes |
| modifiers | jsonb | 금지 | registry=result_modifiers |
| lesion_count | integer | 허용 | — |

복합 UNIQUE: `report_id, display_order`

제약: 대장 표기 예 TA#2(L)는 result_code=TA·lesion_count=2·modifiers=[L] / modifiers는 등록 코드 배열만이며 빈 배열 허용 / 자유서술·판독문 원문 저장 금지 / 결과를 기록한 보고서 버전은 finding 1개 이상

### SydneyGrading

테이블 `sydney_gradings` · 위치 `endoscopy_pathology` · FHIR `Observation` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| report_id | uuid | 금지 | references=PathologyReport; unique=True |
| h_pylori | enum | 허용 | enum=SydneyGrade |
| neutrophil | enum | 허용 | enum=SydneyGrade |
| mononuclear | enum | 허용 | enum=SydneyGrade |
| atrophy | enum | 허용 | enum=SydneyGrade |
| intestinal_metaplasia | enum | 허용 | enum=SydneyGrade |

제약: 대장 표기 HP-/Neu++/Mon++/Atr+/IM-의 구조화 / 위 검체가 포함된 보고서에만 허용 / 미기재 항목은 null이며 NEG로 추정 금지

### PhysicianReview

테이블 `physician_reviews` · 위치 `endoscopy_pathology` · FHIR `직접 대응 없음` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| request_id | uuid | 금지 | references=PathologyRequest |
| cycle_id | uuid | 금지 | references=WorkCycle; unique=True |
| report_set_hash | string | 금지 | — |
| ordered_by | uuid | 금지 | references=Staff |
| entered_by | uuid | 금지 | references=Staff |
| reviewed_at | timestamptz | 금지 | — |
| result_category | enum | 금지 | enum=ResultCategory |
| urgency | enum | 금지 | enum=Urgency |
| instruction | enum | 금지 | enum=Instruction |
| instruction_note | string | 허용 | max_length=200 |
| followup_directive | enum | 금지 | enum=FollowUpDirective |
| followup_kind | string | 허용 | registry=followup_kinds |
| followup_due_date | date | 허용 | — |
| no_followup_reason | string | 허용 | — |

제약: ordered_by는 active DOCTOR / entered_by는 실제 actor / REQUIRED이면 kind·날짜 필수 / NOT_REQUIRED이면 불필요 사유 필수

### ReviewReport

테이블 `review_reports` · 위치 `endoscopy_pathology` · FHIR `직접 대응 없음` · 불변 기록

| 필드 | 타입 | NULL | 제약 |
|---|---|---|---|
| review_id | uuid | 금지 | references=PhysicianReview |
| report_id | uuid | 금지 | references=PathologyReport |

복합 UNIQUE: `review_id, report_id`

제약: 확인 당시 유효한 보고서 버전 집합을 고정

## Enum

| 이름 | 값 |
|---|---|
| PatientStatus | ACTIVE, PURGE_PENDING |
| StaffRoleCode | DOCTOR, ADMIN, NURSE, PRIVACY_OFFICER |
| Sex | FEMALE, MALE, OTHER, UNKNOWN |
| ActorType | STAFF, SYSTEM, AGENT |
| ProcedureType | EGD, COLONOSCOPY, BOTH |
| SpecimenMethod | BIOPSY, POLYPECTOMY, OTHER |
| RequestStatus | DRAFT, SHIPPED, RESULT_RECEIVED, REVIEWED, NOTIFIED, CLOSED, CANCELLED, LOST |
| ReportSource | MANUAL, IMPORT |
| ResultCategory | NORMAL, BENIGN, NEEDS_ATTENTION, MALIGNANT, UNKNOWN |
| Urgency | ROUTINE, PRIORITY, URGENT |
| Instruction | CALL, NEXT_VISIT, NONE |
| FollowUpDirective | REQUIRED, NOT_REQUIRED |
| PlanStatus | PLANNED, BOOKED, DONE, CANCELLED |
| PlanReviewStatus | CURRENT, RECONFIRM_REQUIRED |
| NotificationMethod | PHONE, VISIT, LETTER |
| NotificationOutcome | REACHED, NO_ANSWER, WRONG_NUMBER, REFUSED |
| TaskStatus | OPEN, DONE, DISMISSED, AUTO_RESOLVED |
| Priority | NORMAL, HIGH, URGENT |
| AccessAction | VIEW, PRINT, EXPORT, CREATE, UPDATE, PURGE, LOGIN, LOGOUT, LOGIN_FAIL, DENIED |
| RuleRunStatus | RUNNING, SUCCEEDED, FAILED |
| PurgeStatus | PROPOSED, APPROVED, COMPLETED, FAILED |
| ReviewDisposition | CHECKED, INVESTIGATE |
| ImportStatus | COMMITTED, REJECTED |
| ResultCodeScope | UPPER_GI, LOWER_GI, ANY |
| ResultSeverityTier | ROUTINE, ATTENTION, CRITICAL |
| SydneyGrade | NEG, POS1, POS2, POS3 |

## 명명된 관계

| 이름 | 출발 → 도착 | 개수 | 연결 |
|---|---|---|---|
| undergoes | Patient → EndoscopyProcedure | 1:N | patient_id |
| performedBy | EndoscopyProcedure → Staff | N:1 | performer_id |
| hasRequest | EndoscopyProcedure → PathologyRequest | 1:0..1 | procedure_id |
| hasSpecimen | PathologyRequest → Specimen | 1:N | request_id |
| collectedDuring | Specimen → EndoscopyProcedure | N:1 | procedure_id |
| sentTo | PathologyRequest → ExternalLab | N:1 | external_lab_id |
| resultOf | PathologyReport → PathologyRequest | N:1 | request_id |
| coversSpecimen | PathologyReport → Specimen | N:M | ReportSpecimen |
| supersedes | PathologyReport → PathologyReport | 0..1:1 | supersedes_id |
| hasFinding | PathologyReport → ReportFinding | 1:N | report_id |
| usesResultCode | ReportFinding → ResultCode | N:1 | result_code |
| hasGrading | PathologyReport → SydneyGrading | 1:0..1 | report_id |
| reviewsReports | PhysicianReview → PathologyReport | N:M | ReviewReport |
| reviewsRequest | PhysicianReview → PathologyRequest | N:1 | request_id |
| reviewedBy | PhysicianReview → Staff | N:1 | ordered_by |
| usesCurrentReview | PathologyRequest → PhysicianReview | N:0..1 | current_review_id |
| enteredBy | PhysicianReview → Staff | N:1 | entered_by |
| hasRole | Staff → StaffRole | 1:N | staff_id |
| identifiesSubject | SubjectReference → Patient | N:1 | patient_id |
| hasCycle | SubjectReference → WorkCycle | 1:N | subject_type+subject_id |
| createsTask | Rule → Task | 1:N | rule_id |
| evaluatesRule | RuleRun → Rule | N:1 | rule_id |
| concernsSubject | Task → SubjectReference | N:1 | subject_type+subject_id |
| belongsToCycle | Task → WorkCycle | N:1 | cycle_id |
| notifiesAbout | PatientNotification → SubjectReference | N:1 | subject_type+subject_id |
| followsFrom | FollowUpPlan → SubjectReference | N:1 | subject_type+subject_id |
| plansFor | FollowUpPlan → Patient | N:1 | patient_id |
| usesKind | FollowUpPlan → FollowUpKind | N:1 | kind |
| belongsToSegment | AccessLog → AccessLogSegment | N:1 | segment_id |
| changesPermissionOf | PermissionHistory → Staff | N:1 | staff_id |
| includesPurge | PurgeBatch → PurgeItem | 1:N | batch_id |

## 등록형 확장

FollowUpKind·subject type은 문자열 enum 하드코딩 대신 모듈 등록 값만 허용한다. AGENT는 enum에만 예약하고 진입을 거부한다.

```yaml
followup_kinds:
  PATH.ENDOSCOPY:
    owner: endoscopy_pathology
    meaning: 원장 지정 재내시경
subject_types:
  PATH.Request:
    class: PathologyRequest
    owner: endoscopy_pathology
  CORE.FollowUpPlan:
    class: FollowUpPlan
    owner: kernel
disabled_actor_types:
- AGENT
result_codes:
  source: config/result_codes.yaml
  key: codes
  owner: endoscopy_pathology
result_modifiers:
  source: config/result_codes.yaml
  key: modifiers
  owner: endoscopy_pathology
```

## 무결성 정책

- `shared_subject_pk_classes`: ['PathologyRequest', 'FollowUpPlan']
- `polymorphic_fk_classes`: ['WorkCycle', 'Task', 'PatientNotification', 'FollowUpPlan']
- `composite_subject_fk`: {'local': ['subject_type', 'subject_id'], 'remote_class': 'SubjectReference', 'remote': ['subject_type', 'id']}
- `cycle_subject_consistency`: Task·PatientNotification의 subject는 WorkCycle과 일치
- `one_active_cycle`: subject_type·subject_id별 ended_at이 null인 WorkCycle은 최대 1개
- `patient_consistency`: FollowUpPlan.patient_id와 source의 patient_id 일치
- `report_consistency`: ReportSpecimen·ReviewReport는 동일 의뢰 행만 연결
- `result_code_storage`: 결과는 ReportFinding·SydneyGrading의 등록 코드만 저장하고 판독문 원문·자유서술은 어느 테이블·로그·Audit에도 저장 금지
- `timestamps_on_all_tables`: True
- `initial_status_insert`: DRAFT 외 상태의 INSERT 금지
- `report_versioning`: supersedes는 동일 의뢰·동일 logical_report_key의 직전 version_no이며 분기 금지
- `correction_transaction`: 새 버전·새 회차·이전 Task 해소·F/U 재확인 표시·Audit를 원자적으로 저장
