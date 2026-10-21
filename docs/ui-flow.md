# 화면·수동 조작 계약

Phase 0 설계이며 구현은 없다. 화면은 한국어, 업무 PC 폭 1366px 기준이며 모바일 대응은 만들지 않는다.

| URL | 입력·표시 | 서비스·기록 | 수동 복구 |
|---|---|---|---|
| /dashboard | Today/Overdue/Pending/Done, 우선순위·경과일, 내 역할 filter, 지금 점검 | DashboardService VIEW, Rule SYSTEM 실행·RuleRun | 마지막 성공시각, 실패 시 재점검 |
| /procedures/new | 환자 최소 4항목, 시행시각/type/sedation/performer, 검체 N병·부위·방법, 수탁기관 | ProcedureService, DRAFT·첫 cycle 일괄 생성, Audit/CREATE | 전체 rollback, 중복 입력 거부 |
| /requests/{id} | 상태·보고서 coverage/version·확인/안내/F/U·Audit·Task timeline | RequestService VIEW, 변경은 WorkflowEngine | version 불일치 시 재조회, 사유 있는 정정 |
| /requests/{id} 내부 폼 | 발송, 보고서 번호·대상 검체, 원장 확인, 안내 시도, F/U | 짧은 POST+CSRF, 성공 시 HTMX 부분 갱신, 일반 form submit fallback | 미저장 입력 주의, 이중 제출 방지 |
| /patients/{chart_no} | 마스킹 이름, 시행·의뢰·F/U 이력 | PatientService VIEW, 접속기록은 patient UUID | 같은 chart_no의 다른 사람 의심 시 자동 덮어쓰기 중단 |
| /admin/import | Excel→신규/중복/오류/무시 헤더 preview→확정 | ImportService, 허용 항목만, 만료 있는 actor-bound token | 만료·재시작은 재업로드, 충돌 시 전체 rollback |
| /admin/rules | config 임계값, enabled, 최근 실행 로그, 읽기 전용 | RuleService VIEW, 값 편집 route 없음 | 설정 변경은 관리 절차·리뷰 경유 |
| /admin/staff | 개인 계정·역할 집합·active, 변경 사유 | StaffService, PermissionHistory+Audit, 세션 폐기 | 마지막 책임자 삭제 금지, 초기 복구는 오프라인 절차 |
| /privacy/access-logs | 기간/직원/환자 filter, 대량 경고, 점검 완료 | PrivacyService, 책임자만, 조회도 기록 | checkpoint 불일치는 사고 대응 |
| /privacy/purge | 후보·의존성·manifest→승인→결과 | PurgeService, 책임자만, 재검증·삭제 기록 | 승인 뒤 변경은 재승인, 실패 시 원자적 rollback |

이름은 화면·인쇄 모두 가운데 글자 마스킹(2글자는 끝 글자, 1글자는 전체 마스킹)을 제안한다. 전체 이름이 필요한 입력·본인 대조 때만 권한에 따라 표시하고 VIEW 기록을 남긴다. Task title·오류·URL query에 이름을 넣지 않는다. 인쇄용 POST/GET 분리와 CSRF 세부는 Phase 4에서 고정한다.

원장 확인은 분류·긴급도·지시·F/U 필요성·kind·원장 지정 날짜를 사람이 입력한다. 메모는 200자 이내, 임상 소견 기재 금지 안내를 표시한다. 현 회차에서 REACHED가 기록되어야 NOTIFIED로 전이한다. 전화번호는 EMR에서 확인하고 이 시스템에 입력하지 않는다.

부분 결과·NEXT_VISIT·책임자 자기 승인은 Q01/Q02/Q04 답변 대기다. 승인 전 제안을 UI 기본 동작으로 구현하지 않는다. Alpine/HTMX는 로컬 vendor만 사용하며 polling으로 idle session을 연장하지 않는다.
