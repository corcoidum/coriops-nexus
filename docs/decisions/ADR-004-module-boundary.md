# ADR-004: 커널·모듈과 등록 기반 확장

상태: 확장 계약 C1~C8에 따른 설계, 추가 엔티티·권한 정책은 Phase 0 검토 대상.

kernel은 업무 공통 타입과 Engine만 제공하고 PATH 이름·모델·Rule을 모른다. app/main 조립 지점이 endoscopy_pathology의 workflow, guards, Rule, subject resolver, purge 순서, kind, importer를 등록한다. 사용하지 않는 미래 모듈 빈 패키지도 만들지 않는다.

워크플로는 ontology YAML의 전이 표를 읽어 등록하고 guard는 명명된 모듈 함수로 제공한다. Rule은 evaluate 계약, Importer는 4단계 계약을 따른다. 라우트는 서비스만 호출한다. 범용 Notification/Plan/Task는 SubjectReference로 대상 FK 무결성을 보완한다.

StaffRole·WorkCycle·보고서 coverage/버전 연결은 v0.1의 복수 역할·정정·실제 검체 누락 방지에 필요한 보완이다. full Workflow Builder, 이벤트 브로커, Agent SDK, graph DB는 추가하지 않는다.

영속화 관계를 커널에서 동적으로 import하여 해결하지 않는다. DB의 모듈별 deferred trigger는 모듈 마이그레이션이 등록하고 ORM과 YAML 비교에 포함한다. 코드 경계와 DB 참조 경계를 모두 검사한다.

서비스의 단일 통로는 로깅·권한·수동 override 사유가 빠지지 않게 하기 위함이다. 검증은 P1의 구조 검사, P2의 SQL/ORM 우회·조회 기록, P3의 가짜 모듈 등록 테스트로 단계별 실행한다.
