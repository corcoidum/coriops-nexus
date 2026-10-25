# Roadmap과 확장 계약

> 2026-10-25: 전체 방향·단계·현재 상태는 저장소 최상위 [ROADMAP.md](../ROADMAP.md)가 기준이다. 이 문서는 최초 Phase 0 설계의 Gate 기록과 확장 계약 C1~C8을 보존한다.

2026-10-22 A09에 따라 약어 사전은 나중에 받고 합성 Excel 프로토타입부터 진행한다. [독립 소규모 구현·검증](excel-prototype.md)은 정식 앱 Phase 1 전체 완료·실데이터 전환과 구분하며, 아래 최초 Gate의 모든 구현이 끝났다는 의미가 아니다.

## Phase 0~5 Gate

| Phase | 산출물 | 통과 증거 | 현재 |
|---|---|---|---|
| 0 | YAML·설계·충돌 보고·ADR·대응표·질문 | 문서 정합성, 기존 Gate 및 Q17/18·ADR-005 반영·사용자 승인 | 산출물 작성, 씨젠 일일 조회·Excel 갱신 범위 재검토 |
| 1 | kernel/module 모델·Alembic·DB role SQL·문서 생성기·합성 seed | PostgreSQL up/down/up, C1~C3, 테스트 환자 30/시행 40/의뢰 25·모든 상태 | 미착수 |
| 2 | WorkflowEngine·서비스·Audit·AccessLog, 테스트 먼저 | 전 전이 허용/금지·status 우회 차단·해시 조작·조회 기록 | 미착수 |
| 3 | Calendar·Rule registry/Engine·R01~08, 테스트 먼저 | 발생/미발생/해소·반복/경합·Clock E2E | 미착수 |
| 4 | 웹 폼·HTMX·인증·권한·점검 화면 | 보안 E2E·compliance, 업무 PC 수동 재현 | 미착수 |
| 5 | Import·파기·암호화 백업·Caddy·운영문서 | Success Criteria 전체 TECH + 별도 OPS/LEGAL 증거 | 미착수 |

각 Phase 종료 시 보고하고 명시적 승인 전 다음 단계에 가지 않는다. 이번 실행은 Phase 0까지만 허용되었다.

## C1~C8 검증 계약

| 계약 | v0.1 구조 | 계획 테스트·Phase |
|---|---|---|
| C1 | kernel과 endoscopy_pathology 분리, app/main 조립 | test_kernel_has_no_module_imports, 정적·동적 import 경계, P1부터 |
| C2 | ontology YAML에 클래스/속성/enum/관계/FHIR/전이, 생성 문서 | test_ontology_matches_models(타입/null/enum/FK/unique/PK/공통 필드), test_generated_docs_are_current, P1 |
| C3 | 모든 PK UUID, 연결·기록 테이블 포함, chart_no는 속성 | test_all_primary_keys_are_uuid, test_every_table_has_timestamps, P1 |
| C4 | kernel의 Patient/Staff/Task/Rule/Run/Audit/Access/Notification/FollowUpPlan, kind 등록 테이블 | test_polymorphic_reference_integrity, test_unknown_followup_kind_rejected, P1~2 |
| C5 | YAML 전이 표·권한·사유·named guard, kernel Engine | test_direct_status_assignment_rejected, test_raw_status_update_rejected, 전 전이 행 테스트, P2 |
| C6 | module이 PATH.R01~08 등록, kernel은 evaluate 계약만 앎 | test_rule_registry_is_module_agnostic, test_rule_evaluation_has_no_writes, P3 |
| C7 | parse/validate/preview/commit + mapping YAML, 조직 장부 어댑터 1개 | test_importer_contract, test_ignored_values_absent, P5 |
| C8 | 모든 조회·변경·인쇄 서비스 통과, Actor STAFF/SYSTEM, AGENT 비활성 | test_routes_do_not_access_db, test_all_patient_reads_logged, test_agent_actor_disabled, P2~4 |

C1 정적 검사에는 ImportFrom/Import와 동적 importlib 사용도 포함한다. 라우트는 DB dependency나 모델 lazy-load로 우회하지 못한다. C2는 단순 이름 비교로 끝내지 않는다. ORM↔DDL↔YAML 세 층의 FK·CHECK·UUID·timestamp 일치를 확인한다.

## 이후 버전 — 코드 구현 금지

| 버전 | 향후 범위 | 지금 지킬 경계 |
|---|---|---|
| v0.2 | Lab 파일 import | importer adapter·모듈 등록 |
| v0.3 | 검진 F/U | Rule registry·범용 Task/Notification/Plan |
| v0.4 | Recall BMD/Vaccine/Injection | kind registry·Calendar |
| v0.5 | Clinic Ontology | YAML 명명 관계·UUID |
| v1.0 | KG + Workflow Engine | 같은 PostgreSQL·선언형 전이, AGE 미설치 |
| v2.0 | 원내 AI Agent | Actor 예약·서비스 단일 통로, AGENT 실행 금지 |
