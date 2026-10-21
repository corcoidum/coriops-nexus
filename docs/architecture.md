# v0.1 구조·무결성 설계

상태: Phase 0 제안. 구현은 Phase 1 승인 후. `ontology/coriops.yaml`의 엔티티·전이 표가 원천이며 이 문서는 실행·검증 방법을 설명한다.

## 입력 → 처리 → 저장 → 업무 화면

수동 폼 또는 메모리 Excel Import → 서비스의 Actor·권한·검증 → Workflow/Rule Engine → PostgreSQL → 역할별 Dashboard. 모든 입력은 합성 데이터로 개발한다. 임상 판단은 원장 입력이며 Engine은 상태·기한만 평가한다. 문자·알림톡·이메일·외부 API를 호출하지 않는다.

| 경계 | 책임 | 금지 |
|---|---|---|
| app/kernel | UUID 엔티티, Clock, Calendar, 인증, RBAC, Audit/AccessLog, WorkflowEngine, RuleEngine, Importer 계약, 보유·백업 | modules import, PATH 상태·규칙 이름 하드코딩 |
| app/modules/endoscopy_pathology | 모델, guard, 전이·Rule·대상·F/U kind 등록, 서비스, 라우트·템플릿 | Lab/검진/Recall·FHIR 변환·임상 자동 분류 |
| app/main.py | 조립 지점에서 kernel에 모듈 레지스트리 주입 | 커널의 모듈 탐색·동적 import |
| routes | 폼 파싱, 인증 Actor 취득, 서비스 호출, 응답 | Session·SQLAlchemy query·repository 직접 사용 |
| services | 대상 권한, 트랜잭션, 조회·출력 AccessLog, 변경 Audit, 반환 DTO 최소화 | 로그 없이 조회 반환, 모델 객체를 템플릿에 직접 노출 |

## Actor·권한 제안

Actor는 `STAFF(staff UUID, effective roles, client_ip, correlation_id)` 또는 `SYSTEM(component, correlation_id)`이다. AGENT는 예약 enum이며 인증·서비스 진입을 거부한다. SYSTEM은 Rule 실행·자동 해소 등 허용된 기계 작업만 수행하며 원장 확인·환자 안내 성공을 만들 수 없다.

| 권한 | NURSE | ADMIN | DOCTOR | PRIVACY_OFFICER |
|---|---|---|---|---|
| 환자·의뢰 업무 조회, 마스킹 인쇄 | 허용 | 허용 | 허용 | 별도 임상 역할 필요 |
| 시행·검체 등록, 발송 | 허용 | 허용 | 허용 | 별도 임상 역할 필요 |
| 결과 접수·안내·F/U 입력 | 업무범위 내 제안 | 허용 | 허용 | 별도 임상 역할 필요 |
| 원장 확인 대리 입력 | 금지 제안 | active DOCTOR 지시·ordered_by 필수 | 본인 또는 명시 지시 | 별도 임상 역할 필요 |
| 원장 판단·F/U 기한 승인 | 금지 | 금지 | 허용 | 별도 DOCTOR 필요 |
| 일반 취소·정정·안내 생략 | 사유·원장 권한 검사 | 사유·원장 권한 검사 | 허용 | 별도 DOCTOR 필요 |
| 로그 점검·파기 승인 | 금지 | 금지 | 별도 책임자 역할 필요 | 허용 |
| 계정·권한 관리 | 금지 | 일반 직원에 한정 제안 | 별도 책임자 역할 필요 | 책임자/원장 부여 포함 제안 |

위 표는 Q01·Q04 승인 전 초안이다. 복수 역할은 집합 합산하되 대상 접근과 개별 action guard는 항상 검사한다. 계정 비활성·권한 변경 즉시 서버 세션을 폐기한다. 초기 계정 생성도 PermissionHistory·Audit를 남긴다. 자기 승격·마지막 책임자 말소는 차단한다. 직원 퇴사 시 비활성화하고 로그 보유기간 동안 식별 UUID와 최소 계정 정보를 유지하는 기간은 Q06에서 확정한다.

## polymorphic 참조 무결성

`subject_type + subject_id`가 여러 모듈 대상을 가리키도록 하되 단순 문자열 검증만으로 끝내지 않는다.

1. `SubjectReference(id, subject_type, patient_id)`를 커널에 둔다. `id`는 실제 대상 UUID와 같은 공유 PK다. v0.1 대상은 PATH.Request / CORE.FollowUpPlan뿐이다.
2. Task·Notification·Plan.source·WorkCycle은 `(subject_type, subject_id)`에서 SubjectReference의 `(subject_type, id)`로 복합 FK를 가진다. subject와 cycle, source와 patient도 서비스·제약에서 일치시킨다.
3. 대상 모델은 공유 PK FK를 가진다. 모듈 마이그레이션이 deferred constraint trigger를 추가해 SubjectReference와 실제 대상의 존재·타입·환자 일치를 커밋 시 확인한다. 커널은 모듈 테이블을 import하지 않는다. 부모만 남은 행도 커밋에 실패해야 한다.
4. 서비스가 대상·의뢰를 잠그고 같은 트랜잭션에 부모·자식·회차를 생성한다. 잘못된 타입, 다른 환자, 존재하지 않는 대상, 참조 중 대상 단독 삭제는 실패시킨다.
5. 파기는 모듈이 등록한 의존 순서로 자식·대상·registry를 삭제한다. Audit/AccessLog의 장기 참조는 별도 논리 UUID이며 cascade하지 않는다. 그 보유 적정성은 Q06 미확정이다.

트리거는 DB에서 실행하는 작은 무결성 검사다. deferred 검사는 트랜잭션 중간의 생성 순서는 허용하면서 커밋 직전에 최종 상태가 맞는지 검사한다. 일반 FK로 표현 가능한 관계에는 별도 트리거를 만들지 않는다.

## 변경·상태 전이·Rule 트랜잭션

- 서비스는 의뢰 행 잠금과 `version_no`로 동시 입력·중복 제출을 검사한다. 상태·관련 기록·AuditEvent·변경 AccessLog를 원자적으로 커밋한다. 실패 시 일부만 남기지 않는다.
- WorkflowEngine만 상태 쓰기 capability를 가진다. ORM의 직접 status 할당을 거부하고 DB app 계정에는 status 컬럼 직접 UPDATE를 주지 않는 방식과 통제된 전이 함수를 Phase 2에서 구현한다. raw SQL·bulk UPDATE도 차단 테스트한다.
- DB 전이 함수는 from/to/action/actor·사유와 등록된 전이를 검사하고 Audit를 보장한다. `SECURITY DEFINER` 사용 시 고정 search_path, 최소 소유자, PUBLIC EXECUTE 회수, 직접 테이블 쓰기 차단을 검사한다. 함수만 호출하면 임의 상태로 갈 수 있는 구조는 금지한다.
- module guard는 결과 coverage, 현재 review, F/U 근거를 검사한다. DB 함수의 최소 무결성 검사와 서비스 guard의 역할을 분리하되 앱 경로에서 guard 우회가 불가능해야 한다. 우회 위험을 줄일 구체 SQL은 Phase 2 테스트 먼저 작성한다.
- 성공 전이 직후의 Rule 실행은 같은 서비스 작업 안에서 최신 상태에 대해 실행한다. evaluate는 읽기만 하고 Engine이 upsert·Audit를 저장한다. 스케줄·지금 점검은 별도 SYSTEM 트랜잭션이며 RuleRun을 기록한다. 외부 큐·outbox는 추가하지 않는다.
- Rule 평가 실패 시 해당 Rule의 OPEN Task를 자동 해소하지 않는다. 조건이 없는 것과 평가 실패를 구분한다. 오류 코드만 로그에 남기고 원본 값은 남기지 않는다.
- SYSTEM의 Rule 조회도 서비스의 읽기 gateway를 통과한다. 조회한 환자 UUID는 트랜잭션 내 수집기에 모으고 Engine이 AccessLog VIEW를 저장한다. evaluate 자체에는 INSERT/UPDATE를 허용하지 않는다. 후보가 되지 않은 조회 대상도 기록하며 RuleRun만으로 조회 기록을 대체하지 않는다.
- APScheduler는 단일 프로세스 인스턴스에서 실행하고 DB advisory lock + UNIQUE로 수동 실행과 중복 실행을 직렬화한다. 재시작 시 누락 구간은 now 기준 재평가한다.

## Audit·AccessLog

감사기록은 무엇을 바꿨는지, 접속기록은 누가 어느 환자 업무를 했는지 보여준다. 비밀번호·세션 토큰·원본 폼 전체를 저장하지 않는다. Audit before/after는 허용 필드 목록으로 만든다. 환자 인적사항 정정은 UUID·변경 필드명만 남기며 변경 전 이름을 복제하지 않는다.

목록 조회도 화면에 실제 반환된 환자 UUID마다 VIEW 행을 남긴다. 인쇄는 별도 보호된 print route로 PRINT를 먼저 기록한다. 브라우저 임의 캡처·Ctrl+P 자체를 기술적으로 모두 차단할 수는 없으므로 운영 통제가 필요하다. 권한 거부·IP 거부·로그인 실패는 식별 가능한 actor가 없어도 SYSTEM/anonymous 값과 정규화한 출처·업무를 기록한다. 사용자 입력 username 원문을 실패 로그에 무제한 저장하지 않는다.

해시 체인은 각 행의 정규화된 내용과 직전 hash로 다음 hash를 만든다. 중간 변경·순서 변경·행 삭제를 검증기로 찾으며, DB 소유자가 전체 체인을 재작성하는 공격은 독립 보관한 체크포인트가 있어야 탐지한다. 암호화나 권한 통제를 대신하지 않는다.

- UTC·UTF-8·정렬 JSON·명시적 null·고정 필드 순서로 canonical payload를 정의한다. hash 알고리즘은 SHA-256이다.
- 전용 advisory lock 아래 sequence 증가·직전 hash 읽기·INSERT를 같은 트랜잭션으로 처리한다. 잠금 실패 시 개인정보 응답을 내보내지 않는다.
- 월별 segment를 사용하되 이전 segment의 마지막 hash를 이어받고 최초·최종 sequence/hash/count를 격리된 로컬 매체에 체크포인트로 보관한다. 마지막 행 잘라내기 탐지도 테스트한다.
- app은 로그 INSERT·SELECT만 가능하고 UPDATE/DELETE/TRUNCATE·DDL·권한 변경을 할 수 없다. backup은 읽기만, migrator는 배포 시만 사용한다. 만료 segment 파기는 app이 실행하지 못한다.
- 로그 점검 화면 자체 조회도 AccessLog를 남긴다. 점검 시점의 마지막 sequence/hash를 Review에 고정하므로 점검으로 추가된 행과 섞이지 않는다.
- 개인정보 URL·쿼리·요청 본문·SQL 파라미터·예외 원문을 uvicorn/Caddy 로그에 출력하지 않는다. 응답은 Cache-Control: no-store, referrer 제한을 적용한다.

## Import 계약·최소 처리

`parse → validate → preview → commit`의 Importer 인터페이스를 커널에 두고 조직 장부 어댑터만 등록한다. YAML columns 허용목록을 먼저 결정하고 ignore·unknown 값은 정규화·해시·예외·preview DTO에 넣지 않는다. openpyxl이 ZIP/XML을 메모리에서 읽는 것과 애플리케이션이 무시 셀 값을 선택해 읽는 것을 구분한다. ignore 컬럼을 선택·저장하지 않았다는 시험과 최소 허용 샘플 운영 절차를 함께 둔다.

**Q16 승인 전 이 해석을 확정하지 않는다.** [openpyxl 공식 reader 소스](https://openpyxl.readthedocs.io/en/stable/_modules/openpyxl/reader/excel.html)는 sharedStrings를 먼저 로딩하므로 파서 내부에서도 ignore 값 읽기 0건이라는 더 엄격한 요구에는 기본 경로가 맞지 않는다. 엄격한 경우 허용 필드만 포함된 입력 파일 정책 등을 먼저 승인받아야 한다.

일반 UploadFile은 크기에 따라 임시 디스크로 spool될 수 있으므로 기본 동작을 그대로 사용하지 않는다. 업로드 총량·ZIP 확장 크기·행수·동시 세션 상한을 정하고 순수 메모리 버퍼만 허용한다. 매크로·수식·외부 링크·암호화 XLSX는 거부하며 수식 결과를 실행하지 않는다. reverse proxy 임시 파일·컨테이너 swap·core dump도 점검한다.

preview는 프로세스 메모리의 직원 세션별 TTL 버퍼에 **허용 필드만** 보관한다. 재시작 시 다시 업로드한다. 토큰은 actor·mapping version·허용 필드 digest에 결합하고 1회 사용한다. commit 시 중복·권한·대상 버전을 다시 검사하며 요청 전체를 원자적으로 처리한다. 같은 파일·행 재업로드는 정규화 key로 중복 표시, 인적사항 충돌은 자동 덮어쓰지 않고 오류 처리한다. import는 DRAFT 생성만 하며 결과·원장 확인 이력을 추측해 만들지 않는다.

## 네트워크·시간·장애 복구

업무 PC → Caddy 80/443 → app → postgres 5432만 허용한다. app/postgres는 호스트 port mapping이 없다. 외부 egress는 Docker 내부 네트워크와 호스트 방화벽으로 이중 제한하고 프록시만 신뢰한다. 클라이언트 임의 X-Forwarded-For를 허용하지 않는다.

모든 업무 시간은 Clock을 주입하고 UTC 저장·KST 계산을 적용한다. 공휴일은 holidays의 사전 포함 KR 데이터만 사용하며 런타임 다운로드하지 않는다. 서버 시간 오류·Rule 스케줄 정지·백업 실패는 화면의 마지막 성공 시각과 관리자 수동 점검으로 복구한다. DB 장애·로그 쓰기 실패 시 개인정보 응답·변경은 실패 처리하고 원본 대장 수동 업무 절차로 전환한다.
