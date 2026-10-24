# 개인정보 안전조치 대응표 — Phase 0

**법률 자문이 아닌 초안, 원장 결재·확인 필요.** 아래 구현·테스트는 계획이며 현재 충족 증거가 아니다. R-5의 내부 요구사항을 보수적으로 설계하되 특정 제품·숫자가 법에서 직접 지정됐다고 해석하지 않는다.

2026-10-22 범위 변경 요청: 씨젠 자동 조회·Excel 갱신은 [ADR-005](../decisions/ADR-005-seegene-excel-integration.md)에서 설계 중이다. 아래 P12의 Export 없음·P13의 외부 통신 0은 **변경 전 기준**이며, 제안을 채택할 때 허용 출력·목적지와 검증 기준을 명시적으로 개정한다. 원문을 저장할지, 일시 취급 자료·추가 Excel 사본의 보유·파기 범위가 무엇인지도 확인해야 한다. 기존 통제를 충족했다고 표시하지 않는다.

공식 출처 확인일: 2026-10-21. [안전성 고시 제2026-9호](https://law.go.kr/admRulLsInfoP.do?admRulSeq=2100000281400), [공식 본문 조회](https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulId=73493&efYd=0), [개인정보 보호법 제21조](https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900078981)를 참조했다. 2025-9호 부칙의 일부 조항 1년 유예에 따라 목표일 2026-10-31을 문서에 반영했다. 적용 대상·해석은 별도 확인한다.

| 항목 | 요구·설계 | 원문 대응 조항 / 확인점 | 계획 테스트 | Phase·증거 유형 | 현재 |
|---|---|---|---|---|---|
| P1 | Caddy internal TLS, redirect, secure cookie, CSRF | 제7조①. CSRF·쿠키 상세는 내부 통제 | test_http_redirects_to_https, test_session_cookie_flags, test_csrf_rejected | 4/5 TECH + PC OPS | 미구현 |
| P2 | argon2id, 최소 10자 | 제7조①. 알고리즘·10자는 설계 요구 | test_argon2id_hash_and_minimum_length | 4 TECH | 미구현 |
| P3 | 개인 계정, 복수 역할 최소 권한 | 제5조①④. 역할·자기승인은 Q01 | test_role_action_matrix, test_shared_bootstrap_disabled | 4 TECH + OPS | 미확정 |
| P4 | 5회 실패, 30분 잠금·해제 Audit | 제5조⑥. 횟수·시간은 설정 | test_five_failures_lock_and_log, test_unlock_logged | 4 TECH | 미구현 |
| P5 | 부여·변경·말소 PermissionHistory, 3년 이상 | 제5조③. 퇴사 계정 식별 보유도 확인 | test_permission_changes_have_history, test_history_retention_floor | 1/4 TECH + OPS | 미구현 |
| P6 | 15분 미사용 만료, 서버 세션·직접 활동 기준 | 제6조④. polling은 활동 아님 | test_idle_session_expires, test_polling_does_not_refresh_idle | 4 TECH | 미구현 |
| P7 | IP allowlist, trusted proxy, 403·기록 | 제6조①. 외부 원격접속은 지원 안 함 | test_ip_denied_and_logged, test_spoofed_forwarding_header_rejected | 4 TECH + LAN OPS | 미구현 |
| P8 | 필수 5항목, 2년 이상, 해시 체인, app append-only | 제2조3호·제8조①③. 로그 식별·파기는 Q06 | test_access_log_required_fields, test_app_cannot_mutate_logs, test_tamper_detected, test_tail_truncation_detected | 1/2/5 TECH + checkpoint OPS | 미확정 |
| P9 | 책임자 검색·대량 조회 경고·점검 완료 기록 | 제8조②. 월 1회·임계값은 내부 제안 | test_privacy_only_log_review, test_bulk_view_warning, test_review_saved | 4 TECH + 월간 OPS | 미구현 |
| P10 | 대상→책임자 승인→재검증→hard delete·파기기록 | 법 제21조·고시 제13조. Q06의 저장매체·로그·백업 범위 미확정 | test_purge_approval_and_hard_delete, test_active_dependencies_block_purge, test_restore_reapplies_purge | 5 TECH + OPS + LEGAL | 결정 필요 |
| P11 | pg_dump→age 공개키 암호화, 최대 30일, 경로 제한 | 제10조②·제21조② 등 원문 대응은 확인 필요. 30일 잔존을 허용하는 조항으로 해석 금지 | test_backup_encrypted_restore, test_backup_expiry, test_sync_path_rejected | 5 TECH + 복원 OPS + LEGAL | 결정 필요 |
| P12 | 이름 기본 마스킹, PRINT 로그, Export 기능 없음 | 제12조. 인쇄물 회수·폐기는 OPS | test_name_masking_default, test_print_logged, test_export_absent | 4 TECH + OPS | 미구현 |
| P13 | vendoring, 외부 egress 0, DB host port 없음 | 제6조①③과 연계한 내부 통제. 제6조의2 적용 여부 별도 확인 | test_runtime_egress_blocked_db_allowed, test_no_external_assets, test_compose_db_not_published | 4/5 TECH + firewall OPS | 미구현 |
| P14 | mapping ignore/allowlist, 업로드 원본 디스크 미저장 | 최소 처리 원칙. 파서 내부 읽기까지 금지하는지 Q16 결정 필요 | test_ignored_values_absent, test_upload_never_spools, test_import_preview_redaction | 5 TECH + 헤더 검토 OPS | 결정 필요 |

## 법적 확인과 기술 한계

- 로그의 환자 UUID는 다른 자료와 연결 가능한 식별자다. 이름을 빼거나 hash를 썼다고 익명정보라고 단정하지 않는다(Q06).
- `DELETE` 후 조회 불가 시험은 논리 삭제 증거다. WAL·MVCC 페이지·볼륨 snapshot·백업·장치 잔존의 복구 불가 증거는 별도다.
- 접속기록 append-only 권한과 전체 관리자 재작성 탐지는 다르다. 독립 체크포인트와 관리 절차를 검증한다.
- A11로 조직검사 결과 코드·Sydney 등급(건강정보)을 저장한다. 원문 미저장이어도 진단 정보이므로 최소 처리 범위·처리방침·접근 권한 반영을 원장이 결재해야 한다(Q19). 결과 코드는 Audit before/after·로그·Task 제목·URL에 넣지 않는다.
- 보조 업무대장에 진료기록부의 법정 보존기간을 자동 적용하지 않는다. 5년은 원문 [가정]이고 법적 확인을 기다린다.
- 법정 의무 이행 전체를 pytest로 증명할 수 없다. [검증 계획](../verification-plan.md)의 TECH/OPS/LEGAL을 각각 완료해야 실운영 판단을 할 수 있다.
