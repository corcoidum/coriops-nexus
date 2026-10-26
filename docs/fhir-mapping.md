# FHIR 개념 대응

> 원천: `ontology/coriops.yaml` · SHA-256 `c35b8a3d18f2da87859f3ab5770c10c19a83fd7f0dc120a01d5a14801ea67f71`
> `python scripts/gen_docs.py`가 만든 문서다. 직접 고치지 말고 YAML을 고친 뒤 다시 만든다.

참조판: FHIR R4 4.0.1. 아래는 개념 대응이며 FHIR 적합성·profile·변환·서버 구현을 의미하지 않는다(Stage G). [HL7 공식 Resource Index](https://hl7.org/fhir/R4/resourcelist.html)

| 내부 클래스 | 상태 | 개념 대응 |
|---|---|---|
| Staff | 구현됨 | Practitioner |
| StaffRole | 구현됨 | PractitionerRole |
| PermissionHistory | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| AuthSession | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| AccessLog | 구현됨 | AuditEvent |
| AccessLogReview | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| Patient | 구현됨 | Patient |
| Exam | 구현됨 | ServiceRequest / Procedure |
| Specimen | 구현됨 | Specimen |
| ExamResult | 구현됨 | DiagnosticReport |
| DoctorReview | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| FollowUp | 구현됨 | ServiceRequest |
| Handoff | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| ImportBatch | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| LedgerExport | 구현됨 | 직접 대응 없음 — 내부 운영 엔티티 |
| ReportFinding | 구현됨 | DiagnosticReport.conclusionCode |
| SydneyGrading | 구현됨 | Observation |
| ResultCode | 구현됨 | CodeSystem.concept |
| Rule | 예정(Stage B) | PlanDefinition |
| RuleRun | 예정(Stage B) | 직접 대응 없음 — 내부 운영 엔티티 |
| Task | 예정(Stage B) | Task |
