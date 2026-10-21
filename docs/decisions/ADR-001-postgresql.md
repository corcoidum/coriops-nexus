# ADR-001: PostgreSQL 16과 DB 역할 분리

상태: 요구사항에서 지정된 선택을 기록. 구현·마이그레이션 미실행.

## 문제와 결정

결과 상태·범용 관계·JSONB 감사기록과 DB 권한 통제를 한 저장소에 유지한다. 지정 스택 PostgreSQL 16 + SQLAlchemy 2.0 + psycopg 3 + Alembic을 그대로 사용한다. 개발·테스트도 실제 PostgreSQL이며 SQLite로 대체하지 않는다.

DB 계정은 migrator(DDL 소유자), app(업무 DML, access_logs INSERT/SELECT만), backup(덤프용 읽기)으로 분리한다. runtime 컨테이너에 migrator 자격증명을 주지 않는다. PUBLIC의 schema CREATE·불필요한 함수 실행 권한을 회수하고 신규 테이블 default privileges도 검사한다. app의 로그 UPDATE·DELETE·TRUNCATE·테이블 소유·SET ROLE을 허용하지 않는다. 로그 만료 정리는 오프라인 유지보수 승인 작업이다.

DB 계정 분리는 앱 오류가 발생해도 권한 밖 SQL을 DB가 거절하도록 하는 경계다. 계정 이름만 나누고 app을 테이블 소유자로 두면 효과가 없으므로 실제 권한 오류를 테스트한다. [PostgreSQL 16 GRANT](https://www.postgresql.org/docs/16/sql-grant.html)

## 결과·검증

- UUID PK·JSONB·timestamptz·FK·CHECK·unique를 실제 DB에서 검증한다. 로그용 BIGINT 순번은 속성이며 PK는 UUID다.
- 시험 DB는 production과 별도 DB/볼륨으로 구성하고 호스트 포트를 노출하지 않는다. compose 안에서 pytest가 DB에 연결한다.
- Phase 1에서 up/down/up·3계정 권한을 검증한다. Phase 2에서 상태 직접 UPDATE·로그 변경 우회를 검증한다.
- 보유기간 만료 로그의 관리용 삭제와 app append-only는 별개다. 계정 추가가 필요하면 별도 ADR·승인 전에 제안한다.

새 production 패키지는 이번 Phase에서 설치하지 않았다. YAML 런타임 파서 PyYAML은 향후 설정 읽기에 필요한 작은 추가 의존성으로 제안하며 Phase 1에서 명시적으로 고정·검토한다.
