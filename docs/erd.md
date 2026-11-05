# ERD

> 원천: `ontology/coriops.yaml` · SHA-256 `7c89601323c341de2bf088f8aebbc41710b99e016ebff955eab44cd1803746e4`
> `python scripts/gen_docs.py`가 만든 문서다. 직접 고치지 말고 YAML을 고친 뒤 다시 만든다.

공통 필드(id·created_at·updated_at)는 모든 테이블에 있다. 관계는 각 클래스의 `references` 필드에서 만든다. JSONB 안에 들어가는 구성 요소(ReportFinding·SydneyGrading)와 config 등록값(ResultCode)은 그림에서 뺐다.

```mermaid
erDiagram
    Staff {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        string username
        string display_name
        string password_hash
        boolean active
        boolean must_change_password
        integer failed_login_count
        timestamptz locked_until
    }
    StaffRole {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid staff_id FK
        enum role
    }
    PermissionHistory {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid staff_id FK
        uuid changed_by FK
        timestamptz at
        jsonb before_roles
        jsonb after_roles
        boolean before_active
        boolean after_active
        string reason
    }
    AuthSession {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid staff_id FK
        string token_hash
        timestamptz last_activity_at
        timestamptz expires_at
        timestamptz revoked_at
    }
    AccessLog {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        bigint sequence_no
        timestamptz at
        uuid actor_id FK
        string actor_label
        string client_ip
        enum action
        string subject_ref
        string target_type
        integer detail_count
        string outcome
        string prev_hash
        string hash
    }
    AccessLogReview {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid reviewer_id FK
        timestamptz reviewed_at
        timestamptz period_start
        timestamptz period_end
        bigint last_sequence
        string last_hash
        boolean chain_ok
        integer bulk_alerts
        string note
    }
    Patient {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        string chart_no
        string name
    }
    Exam {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid patient_id FK
        enum kind
        date exam_date
        enum procedure_type
        integer age
        enum sex
        string report_ref
        enum source
        uuid import_batch_id FK
        integer version
    }
    Specimen {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid exam_id FK
        integer specimen_count
        string site
        uuid handoff_id FK
        string registered_by
        string handed_by
        string received_by
        date entrusted_on
    }
    ExamResult {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid exam_id FK
        date reported_on
        string result_code
        jsonb findings
        jsonb sydney
        jsonb review_codes
    }
    DoctorReview {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid exam_id FK
        timestamptz decided_at
        string decided_by
        string no_followup_reason
    }
    FollowUp {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid review_id FK
        date due_on
        date done_on
        string done_by
    }
    Handoff {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        timestamptz handed_at
        string registered_by
        string handed_by
        string receiver_name
        integer specimen_count
        integer case_count
    }
    ImportBatch {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        timestamptz committed_at
        string digest
        integer accepted
        integer skipped
        jsonb sheet_counts
    }
    LedgerExport {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        timestamptz exported_at
        string file_name
        integer row_count
    }
    Rule {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        string rule_id
        jsonb params
        boolean enabled
        string config_hash
    }
    RuleRun {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        timestamptz evaluated_at
        timestamptz finished_at
        enum scope
        enum status
        string config_hash
        integer candidate_count
        integer created_count
        integer resolved_count
        string error_code
    }
    Task {
        uuid id PK
        timestamptz created_at
        timestamptz updated_at
        uuid rule_id FK
        uuid run_id FK
        string subject_type
        uuid subject_id
        string dedupe_key
        string title
        enum priority
        enum assignee_role
        timestamptz opened_at
        timestamptz due_at
        enum status
        timestamptz resolved_at
        string resolved_by
        string resolution_note
    }
    StaffRole }o--|| Staff : roleOf
    PermissionHistory }o--|| Staff : changesPermissionOf
    PermissionHistory }o--o| Staff : changedBy
    AuthSession }o--|| Staff : sessionOf
    AccessLog }o--o| Staff : performedBy
    AccessLogReview }o--|| Staff : reviewedBy
    Exam }o--|| Patient : forPatient
    Exam }o--o| ImportBatch : importedIn
    Specimen |o--|| Exam : collectedIn
    Specimen }o--o| Handoff : handedOverIn
    ExamResult |o--|| Exam : resultOf
    DoctorReview |o--|| Exam : reviews
    FollowUp |o--|| DoctorReview : plannedBy
    Task }o--|| Rule : createdBy
    Task }o--|| RuleRun : openedIn
```

## 단계별 테이블

| 클래스 | 테이블 | 상태 |
|---|---|---|
| Staff | `staff` | 구현됨 |
| StaffRole | `staff_roles` | 구현됨 |
| PermissionHistory | `permission_history` | 구현됨 |
| AuthSession | `auth_sessions` | 구현됨 |
| AccessLog | `access_logs` | 구현됨 |
| AccessLogReview | `access_log_reviews` | 구현됨 |
| Patient | `patients` | 구현됨 |
| Exam | `exams` | 구현됨 |
| Specimen | `specimens` | 구현됨 |
| ExamResult | `exam_results` | 구현됨 |
| DoctorReview | `doctor_reviews` | 구현됨 |
| FollowUp | `followups` | 구현됨 |
| Handoff | `ledger_handoffs` | 구현됨 |
| ImportBatch | `ledger_import_batches` | 구현됨 |
| LedgerExport | `ledger_exports` | 구현됨 |
| Rule | `rules` | 구현됨 |
| RuleRun | `rule_runs` | 구현됨 |
| Task | `tasks` | 구현됨 |
