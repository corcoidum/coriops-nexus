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
| P7 | IP allowlist, trusted proxy, 403·기록 | 제6조①1·2호. 외부 원격접속은 지원 안 함 | test_outside_network_is_denied_and_logged, test_forwarded_header_from_untrusted_peer_is_ignored, test_trusted_proxy_uses_rightmost_untrusted_hop | 4 TECH + LAN OPS | TECH 구현(2026-10-25). 실제 LAN 대역·Caddy 프록시 주소는 Q10 OPS |
| P8 | 필수 5항목, 2년 이상, 해시 체인, app append-only | 제2조3호·제8조①③. 로그 식별·파기는 Q06 | test_access_log_required_fields, test_app_cannot_mutate_logs, test_tamper_detected, test_tail_truncation_detected | 1/2/5 TECH + checkpoint OPS | 미확정 |
| P9 | 책임자 검색·대량 조회 경고·점검 완료 기록 | 제8조②. 월 1회·임계값은 내부 제안 | test_privacy_only_log_review, test_bulk_view_warning, test_review_saved | 4 TECH + 월간 OPS | 미구현 |
| P10 | 대상→책임자 승인→재검증→hard delete·파기기록 | 법 제21조·고시 제13조. Q06의 저장매체·로그·백업 범위 미확정 | test_purge_approval_and_hard_delete, test_active_dependencies_block_purge, test_restore_reapplies_purge | 5 TECH + OPS + LEGAL | 결정 필요 |
| P11 | pg_dump→age 공개키 암호화, 최대 30일, 경로 제한 | 제10조②·제21조② 등 원문 대응은 확인 필요. 30일 잔존을 허용하는 조항으로 해석 금지 | test_backup_encrypted_restore, test_backup_expiry, test_sync_path_rejected | 5 TECH + 복원 OPS + LEGAL | 결정 필요 |
| P12 | 이름 기본 마스킹, PRINT 로그, Export 기능 없음 | 제12조. 인쇄물 회수·폐기는 OPS | test_name_masking_default, test_print_logged, test_export_absent | 4 TECH + OPS | 미구현 |
| P13 | vendoring, 외부 egress 0, DB host port 없음 | 제6조①③과 연계한 내부 통제. 제6조의2 적용 여부 별도 확인 | test_runtime_egress_blocked_db_allowed, test_no_external_assets, test_compose_db_not_published | 4/5 TECH + firewall OPS | 미구현 |
| P14 | mapping ignore/allowlist, 업로드 원본 디스크 미저장 | 최소 처리 원칙. 파서 내부 읽기까지 금지하는지 Q16 결정 필요 | test_ignored_values_absent, test_upload_never_spools, test_import_preview_redaction | 5 TECH + 헤더 검토 OPS | 결정 필요 |

## 법령 원문 대조 — 2026-10-25 (A17)

법제처 현행 본문으로 확인했다: 개인정보 보호법(시행 2026-09-11), 의료법(시행 2026-10-02), 개인정보의 안전성 확보조치 기준(고시 제2026-9호, 시행 2026-07-01). 의료법은 2026-11-12 이후 시행예정 개정이 여러 건 있어 운영 전 다시 확인한다. **법률 자문이 아니다.**

| 조문 | 요구 | 이 앱의 대응 | 증거 유형 · 남은 일 |
|---|---|---|---|
| 개인정보 보호법 제23조① | 건강 정보는 민감정보. 별도 동의 또는 법령의 요구·허용이 있어야 처리 | 결과는 코드·H/L 등 최소 표기만 저장(A11), 판독문 원문 미저장. 혈액 탭은 아직 저장하지 않음 | LEGAL: 처리 근거와 처리방침 반영(Q21, [체크리스트](processing-policy-checklist.md)) |
| 개인정보 보호법 제23조② | 민감정보는 제29조의 안전조치 | 아래 고시 항목 전체 | TECH 일부 + OPS |
| 고시 제6조①1호 | 접속 권한을 IP 주소 등으로 제한 | DB 모드에서 `allowed_client_cidrs` 밖 접속 403(로그인 화면 포함), 헤더 위조 무시, 신뢰 프록시만 X-Forwarded-For 사용 | TECH 구현. OPS: 실제 LAN 대역(Q10), 서버 방화벽 |
| 고시 제6조①2호 | 접속 IP를 분석해 유출 시도 탐지·대응 | 거부도 접속기록 `DENIED`·`network`로 남기고 점검 화면에서 조회 | TECH 구현. OPS: 월간 점검 때 거부 기록 확인 |
| 고시 제6조② | 외부에서 접속하면 안전한 인증수단 | 외부 접속 경로를 두지 않음(127.0.0.1 게시, 원내 대역만 허용) | OPS: 원격접속 프로그램으로 우회하지 않기 |
| 고시 제6조③ | P2P·공유설정 등으로 공개·유출 방지 | 엑셀 출력은 지정 폴더 하나, 클라우드 경로 거부(A13) | OPS: PC 공유폴더·동기화 점검([내부 보안 제안](internal-security-proposal.md)) |
| 고시 제6조④ | 일정 시간 미사용 시 자동 차단 | 15분 미사용 만료, 12시간 절대 만료(P6) | TECH 구현 |
| 고시 제6조⑤ | 업무용 모바일 기기 보호 | 휴대폰 화면을 지원하지만 원내 대역에서만 접속 가능 | OPS: 업무 휴대폰을 쓴다면 화면 잠금 |
| 의료법 제19조① | 업무 중 알게 된 다른 사람의 정보 누설 금지 | 로그인 화면 고지, 목록 이름 가림, 상세 조회·변경 접속기록, 외부 통신 차단 | OPS: 직원 교육·비밀유지 서약 |
| 의료법 제21조② | 환자가 아닌 사람에게 기록 열람·사본 제공 금지 | 환자·제3자용 화면·공유 링크 없음. 엑셀 출력은 권한자만, 출력 기록 | OPS: 출력물 관리. 제3항 예외 요청은 EMR·원무 절차로 처리 |
| 의료법 제23조③④ | 전자의무기록 탐지·누출·변조 금지, 추가기재·수정 접속기록 별도 보관 | 이 앱은 보조 업무대장 전제. 그래도 변경·조회 접속기록은 추가 전용·해시 체인 | LEGAL: 해당 여부(Q21) |

## 법적 확인과 기술 한계

- 현재 Excel·종이 장부 운영부터 앱 시범 운영·실데이터 운영까지의 단계별 내부 보안 조치는 [내부 보안 유지 제안](internal-security-proposal.md)에 정리했다(2026-10-24).

- 로그의 환자 UUID는 다른 자료와 연결 가능한 식별자다. 이름을 빼거나 hash를 썼다고 익명정보라고 단정하지 않는다(Q06).
- `DELETE` 후 조회 불가 시험은 논리 삭제 증거다. WAL·MVCC 페이지·볼륨 snapshot·백업·장치 잔존의 복구 불가 증거는 별도다.
- 접속기록 append-only 권한과 전체 관리자 재작성 탐지는 다르다. 독립 체크포인트와 관리 절차를 검증한다.
- 2026-10-25 장부 앱(DB 모드)에 P2(argon2id·10자)·P3(개인 계정·역할표, Q01 가정)·P4(5회/30분)·P5(권한 이력·추가 전용)·P6(15분 미사용·서버 세션)·P8(필수 항목·해시 체인·추가 전용 트리거)·P9(책임자 점검·대량 조회 경고·점검 기록)를 구현하고 시험했다. 남은 것: P1 HTTPS(Caddy), P7 IP 허용 대역, P8 외부 체크포인트·DB 계정 분리(app/migrator/backup), 접속기록 2년 보관의 운영 확인.
- A13(2026-10-25)으로 엑셀 출력이 조건부 허용 제안으로 바뀌었다(P12 개정 필요). 출력은 지정 원내 폴더 하나, 새 파일만, 출력 기록 저장, 링크·클라우드 경로 거부다. 과거 엑셀 이관은 미리보기 무저장·비고 열 미저장·셀 값 없는 오류 보고로 처리한다(P14). 실데이터 이관 전 개인 로그인·접속기록(P3·P8)이 먼저 필요하다.
- A11로 조직검사 결과 코드·Sydney 등급(건강정보)을 저장한다. 원문 미저장이어도 진단 정보이므로 최소 처리 범위·처리방침·접근 권한 반영을 원장이 결재해야 한다(Q19). 결과 코드는 Audit before/after·로그·Task 제목·URL에 넣지 않는다.
- 보조 업무대장에 진료기록부의 법정 보존기간을 자동 적용하지 않는다. 5년은 원문 [가정]이고 법적 확인을 기다린다.
- 법정 의무 이행 전체를 pytest로 증명할 수 없다. [검증 계획](../verification-plan.md)의 TECH/OPS/LEGAL을 각각 완료해야 실운영 판단을 할 수 있다.
