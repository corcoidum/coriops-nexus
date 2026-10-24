# FHIR 개념 대응

> 원천: `ontology/coriops.yaml` · SHA-256 `e5278a645eed4a36a56400d3dab24e5ad7f020ca01173a3b331e0bdc240a48d0`
> Phase 0 일회성 로컬 생성 스냅샷. 영구 생성기·CI 일치 검사는 Phase 1 예정. 직접 편집하지 않는다.


참조판: FHIR R4 4.0.1. 아래는 개념 대응이며 FHIR 적합성·profile·변환·서버 구현을 의미하지 않는다. [HL7 공식 Resource Index](https://hl7.org/fhir/R4/resourcelist.html)

| 내부 클래스 | 개념 대응 |
|---|---|
| Patient | Patient |
| Staff | Practitioner |
| StaffRole | PractitionerRole |
| AuthSession | 직접 대응 없음 — 내부 운영 엔티티 |
| SubjectReference | 직접 대응 없음 — 내부 운영 엔티티 |
| WorkCycle | 직접 대응 없음 — 내부 운영 엔티티 |
| FollowUpKind | 직접 대응 없음 — 내부 운영 엔티티 |
| FollowUpPlan | ServiceRequest / CarePlan |
| PatientNotification | Communication |
| Rule | PlanDefinition |
| RuleRun | 직접 대응 없음 — 내부 운영 엔티티 |
| Task | Task |
| AuditEvent | AuditEvent |
| AccessLogSegment | 직접 대응 없음 — 내부 운영 엔티티 |
| AccessLog | AuditEvent |
| AccessLogReview | 직접 대응 없음 — 내부 운영 엔티티 |
| PermissionHistory | 직접 대응 없음 — 내부 운영 엔티티 |
| PurgeBatch | 직접 대응 없음 — 내부 운영 엔티티 |
| PurgeItem | 직접 대응 없음 — 내부 운영 엔티티 |
| ImportBatch | 직접 대응 없음 — 내부 운영 엔티티 |
| EndoscopyProcedure | Procedure |
| ExternalLab | Organization |
| PathologyRequest | ServiceRequest |
| Specimen | Specimen |
| PathologyReport | DiagnosticReport |
| ReportSpecimen | DiagnosticReport.specimen |
| ResultCode | CodeSystem.concept |
| ReportFinding | DiagnosticReport.conclusionCode |
| SydneyGrading | Observation |
| PhysicianReview | 직접 대응 없음 — 내부 운영 엔티티 |
| ReviewReport | 직접 대응 없음 — 내부 운영 엔티티 |

PhysicianReview는 v0.1 내부 확인 기록이다. DiagnosticReport는 보고서 번호·버전·검체 coverage metadata 대응이며 판독문 원문을 저장하지 않는다. ReportFinding은 등록 결과 코드만 담는 conclusionCode 개념 대응이고, SydneyGrading은 등급 코드만 담는 Observation 개념 대응이다(A04). Audit/Access의 개념 대응은 리소스 변환을 허용하는 것이 아니다. 동사형 관계와 UUID는 ontology YAML을 유지한다.
