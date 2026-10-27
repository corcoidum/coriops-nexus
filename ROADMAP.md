# CoriOps Nexus Roadmap

> **Clinic Operations Knowledge & Workflow Engine**
> 의원에 흩어진 데이터와 업무 규칙을 하나의 의미 체계로 연결하고,
> 놓치면 안 되는 후속 업무를 찾아내고 추적하는 내부망 기반 Clinic Operations System.

이 문서는 사용자가 작성한 로드맵 초안(2026-10-25)을 **현재 저장소 상태에 맞춰** 정리한 것이다. 비전·원칙은 초안을 따르고, 단계 순서·상태·세부 결정은 실제 구현과 업무 확인 결과(A01~A13)를 반영했다. 작업 규칙은 [AGENTS.md](AGENTS.md), 결정 기록은 [docs/open-questions.md](docs/open-questions.md)에 있다.

---

## 1. Vision

```text
분산 데이터 → 공통 데이터 모델 → Clinic Ontology → Rule / Workflow Engine → Task → Dashboard → AI Copilot / Agent
```

> **사람의 기억에 의존하던 의원 업무를 데이터·관계·상태·규칙·Task로 표현한다.**

문제는 데이터가 없는 것이 아니라 **데이터 사이의 관계와 다음 행동(Action)이 시스템에 정의되어 있지 않다는 것**이다. 의사랑 EMR, 내시경 예약표, 조직검체 대장, 씨젠 결과, 검진 결과, 골다공증·예방접종 Recall, 엑셀·수기 대장이 서로 따로 있다.

## 2. Core Principles

| 원칙 | 내용 | 현재 저장소에서 지키는 방법 |
|---|---|---|
| EMR 대체가 아니다 | 의사랑은 Source of Record, Nexus는 Operational Workflow Layer | 결과 설명·환자 안내는 EMR에서 관리(A12). 연락처·주민번호를 저장하지 않음 |
| AI보다 데이터 구조가 먼저 | Data → Relationship → State → Rule → Task → Dashboard → AI | LLM 없이 동작. AGENT 사용자 유형은 예약만 하고 비활성 |
| Fact와 Action 분리 | 검사값(사실)과 검토 필요·Task(행동)를 섞지 않는다 | 결과는 등록 코드만 저장(A11), 중요도(tier)는 Rule·F/U 판단에 쓰지 않음 |
| Human-in-the-Loop | 진단·처방·재검 주기·의료적 의미는 사람이 최종 확인 | 재검 날짜는 원장이 정한 값을 그대로 입력. 시스템은 기한·누락·경과일만 계산 |
| 작게 만들고 검증한다 | Analyze → Design → Build → Test → Review → Document, PR 하나에 목적 하나 | 실제 PostgreSQL 시험, GitHub Actions CI, 브라우저로 직접 확인 |

## 3. 현재 상태 한눈에 보기 (2026-10-25)

| 초안 Phase | 내용 | 상태 | 근거 |
|---|---|---|---|
| 0 Foundation | README·개인정보 원칙·Python·pytest·CI·AGENTS.md | ✅ | `pyproject.toml`, `tests/` 299개, `.github/workflows/ci.yml`, `AGENTS.md` |
| 1 Ontology | Entity·관계·상태·FHIR | ✅ v0.2 | `ontology/coriops.yaml` v0.2 21클래스(구현 18·예정 3)·`scripts/gen_docs.py`·YAML=코드=DB 일치 시험 |
| 2 PostgreSQL ERD | 테이블·FK·제약·마이그레이션·감사 필드 | ✅ | Alembic 0001~0003. `patients`·`exams`·`specimens`·`exam_results`·`doctor_reviews`·`followups` |
| 3 Endoscopy + Specimen MVP | 접수 → 인계 → 결과 → 원장 지시 → 재검 | ✅ | DB 저장 장부, 3자 인계·병 수 대조, 엑셀 가져오기·대조·출력, 종이 대장 ①·② 대조·같은 양식 출력(A15) |
| 4 Rule Engine | 규칙이 누락을 찾아냄 | ✅ | L01~L05(`config/rules.yaml` v0.3), 실행 기록, 중복 방지·자동 해소(B-1) |
| 5 Task Engine | 담당·상태·출처가 있는 Task | 🟡 | `tasks` 저장·닫기(B-1). "오늘 할 일" 화면은 B-2 |
| 6 Lab Integration | 씨젠 결과 → Observation | ⚪ | — |
| 7 Screening F/U | 검진 결과 후속관리 | ⚪ | — |
| 8 Recall Engine | 정기 재검·주사·백신 | 🟡 | 내시경 재검만: 재검 도래·기간 필터·대상자 출력 |
| 9 Dashboard v1.0 | 오늘 놓치면 안 되는 일 | 🟡 | 조직검체·CLO·Stool만 |
| 10~12 Ontology v1.0·FHIR·KG | RDF/OWL/SHACL, FHIR 변환, 그래프 | ⚪ | FHIR 개념 대응 문서만 |
| 13~14 AI Copilot·Agent Harness | 도구 계층·사람 승인 | ⚪ | 서비스 단일 통로·권한표·접속기록은 준비됨 |
| 9장 Privacy & Security | 개인 계정·접속기록 | ✅ 2단계 | argon2id 로그인, 권한표, 추가 전용 해시 체인 접속기록 |

✅ 완료 · 🟡 일부 · 🔴 미구현 · ⚪ 예정

## 4. 초안에서 바꾼 점

| 초안 | 변경 | 이유 |
|---|---|---|
| 상태 `PATIENT_NOTIFIED`, Rule 003 "환자 결과 안내" | 이 시스템에서는 다루지 않음 | 결과 설명은 약 1주 뒤 내원 시 EMR에 기록(A12) |
| Rule 001 "발송 후 7일 → 결과 확인" | **위탁 후 2진료일 초과**를 지연으로(설정값) | 실제 대장에서 결과는 대부분 다음 진료일 보고. 실측 후 조정 |
| `src/coriops_nexus/` 구조 | `app/kernel` + `app/modules/<업무>` 유지 | Lab·검진·Recall을 모듈로 더하기 쉬운 경계(ADR-004). 이동 비용 대비 이득이 없음 |
| Streamlit 대시보드 | FastAPI + Jinja 유지 | 로그인·접속기록·권한이 이미 붙어 있다. 화면 기술을 둘로 나누면 보안 경계도 둘이 된다 |
| "첫 작업은 코드 없이 문서만" | 문서와 코드를 같은 PR에서 맞춘다 | 이미 동작하는 코드가 있으므로 문서가 코드를 따라가야 한다 |
| AI: OpenAI API | 원내 모델 또는 식별정보를 뺀 도구 결과만 | Red 등급(이름·검사결과)은 외부 AI 금지 |
| 단일 상태 체인 | 인계 대기 → 결과 대기 → 원장 지시 대기 → 재검 예정 → 종결 | 접수·인계 3자·병 수 대조가 실제 누락 위험 지점(A12) |

## 5. 다음 단계

초안 Phase를 현재 상태에서 이어지는 순서로 묶었다. 각 단계는 별도 PR이며, 끝나면 3장 표를 고친다.

### Stage 0 — Foundation 마무리 ✅

- `ROADMAP.md`(이 문서), `AGENTS.md`·`CLAUDE.md`, GitHub Actions CI(pyflakes + Compose 구성 + PostgreSQL 16 pytest)
- DB 장부 Compose를 `docker-compose.ledger.yml`로 분리: 메모리 시연·시험 파일이 `.env` 없이 다시 실행된다(DB 장부의 필수 비밀값 때문에 파일 전체가 실패하던 문제)
- **완료 조건:** PR에서 CI가 초록색이다.

### Stage A — 공통 모델 통일 (초안 Phase 1·2) ✅

정식 모델(`ontology/coriops.yaml`)과 운영 테이블(`ledger_entries` 한 줄에 환자·검사·결과·지시·재검이 모두 있음)이 갈라져 있던 것을 Lab·검진·Recall을 붙이기 전에 합쳤다.

- **A-1 ✅** `ontology/coriops.yaml` v0.2: 실제 운영 흐름(A04~A13)에 맞게 줄였다(이전 검토안은 `docs/archive/`, D11). 문서 생성기 `scripts/gen_docs.py`, 시험 `test_ontology.py`로 YAML·코드 테이블·문서 일치를 검사한다
- **A-2 ✅** 테이블: `patients`, `exams`, `specimens`, `exam_results`, `doctor_reviews`, `followups`(재검 계획), 기존 `ledger_entries`에서 Alembic 데이터 이전(A14: Stool은 내시경이 아니고 CLO·Stool 결과는 병리 판독이 아니므로 `endoscopies`·`pathology_reports` 대신 이 이름을 쓴다)
- 환자는 차트번호로 한 번만 저장하고, 이름 변경·충돌은 덮어쓰지 않고 거부한다(A14). 원장 지시·재검 완료의 기록자를 새로 남긴다
- 남은 일: 이전 시점 사본 `ledger_entries_legacy`는 Stage B 첫 리비전에서 지운다
- **완료 조건:** 기존 화면·시험이 그대로 통과하고, 이전 전후 건수·결과·재검 일정이 일치하며, upgrade·downgrade·upgrade가 된다

### Stage B — Rule + Task Engine (초안 Phase 4·5)

- **B-1 ✅** 규칙 L01~L05·실행기·`rules`·`rule_runs`·`tasks`(Alembic 0004), `ledger_entries_legacy` 삭제(A17). Stool 당일 인계(A16)
- **B-2** "오늘 할 일" 화면(오늘·기한 지남·대기·완료, 내 역할), 확인 완료·해당 없음, 대시보드 숫자 연결

- 규칙이 Task를 **DB에 저장**한다. 같은 대상·같은 회차는 한 번만 저장하고(중복 방지), 실행 이력을 남긴다
- 첫 규칙: 인계 누락(수령 시각 경과), 결과 지연(2진료일 초과), 원장 지시 대기, 재검 30일 이내, 재검 도래·경과
- Task: 담당 역할·상태(OPEN·DONE·DISMISSED·AUTO_RESOLVED)·처리자·처리 시각·출처를 둔다. 대시보드는 Today·Overdue·Pending·Done을 Task에서 읽는다
- **완료 조건:** 규칙별 발생·미발생·해소 시험, 연속 실행해도 Task 수가 늘지 않고, 고정 시계로 다시 돌린 결과가 같다

### Stage C — Recall 일반화 (초안 Phase 8)

- 재검 종류를 등록식으로 만든다(내시경 재검, BMD, 골다공증 주사, 예방접종). 원장이 정한 다음 일정과 연락 여부를 기록한다
- 완료 후 다음 Recall은 **원장이 날짜를 지정**해 만든다(자동 주기 계산 없음)
- **완료 조건:** 종류별 도래·기간 목록과 대상자 출력이 되고, 미완료 Recall을 조회할 수 있다

### Stage D — Lab·검진 모듈 (초안 Phase 6·7)

- 씨젠 XLSX → 검사 결과(Observation) → 원장 확인 Task. 지금의 엑셀 가져오기 방식을 재사용한다(메모리 읽기, 무저장 미리보기, 신규만 저장, 셀 값 없는 오류 보고)
- 검진: 완료 → 결과 도착 → 원장 확인 → F/U 필요 Task
- **완료 조건:** 가상 Lab 파일 가져오기, 항목 매핑, 환자 연결, 결과 미확인 Task 생성
- 선행 시연(A25): 혈액검체 원내 서식(12열) 합성 Excel·메모리 대시보드 탭(`/lab`, DB 모드에서는 꺼짐). Stage D 완료로 보지 않는다. [계획](docs/blood-ledger-plan.md)

### Stage E — Clinic Dashboard v1.0 (초안 Phase 9)

- 출근 후 한 화면: 오늘 인계·결과 지연·원장 확인·재검 도래·검진 F/U·7일 이내 Recall
- **완료 조건:** 실제 환자정보 없이 시연할 수 있고, 항목을 누르면 상세 흐름으로 이어진다
- 첫 형태(A26): `/` '오늘 할 일'에 조직검체·혈액검체 건수 카드와 모든 화면 상단 위급치 알림. 검진 F/U·Recall이 빠져 있어 Stage E 완료로 보지 않는다.

### Stage F — AI Copilot (초안 Phase 13·14)

- 읽기 전용 도구부터 시작한다(`get_today_tasks`, `get_due_followups`, `get_pending_pathology`). 사람과 같은 권한표를 적용하고, 모든 호출을 접속기록에 남긴다
- 쓰기 도구는 사람 승인 화면을 거친다. Agent는 DB를 직접 수정하지 않는다
- 원내 모델을 우선한다. 외부 모델이면 Red 등급 정보를 넣지 않는다
- **하지 않는 것:** 진단 확정, 처방 결정, 임상 응급도 자동 확정, 원장 승인 없는 재검 주기 확정

### Stage G — Ontology v1.0·FHIR·Knowledge Graph (초안 Phase 10~12)

- YAML 온톨로지 → RDF/OWL로 내보내고, SHACL로 검증하는 시험부터 한다
- FHIR 서버를 먼저 만들지 않고, 필요할 때 리소스 변환을 구현한다(Patient, Procedure, Specimen, DiagnosticReport, Observation, Task)
- 그래프 저장소는 실제 관계 탐색 요구가 생길 때 비교한다(ADR-002)

### 보안 단계와 함께 가야 하는 일

[내부 보안 유지 제안](docs/privacy/internal-security-proposal.md)의 3단계는 위 Stage와 별도로 실데이터 운영 전에 끝낸다. 남은 일은 다음과 같다.

- 원내 HTTPS(Caddy)와 업무 PC IP 허용 대역
- 접속기록 외부 체크포인트, DB 계정 분리(app·migrator·backup)
- 암호화 백업과 복원 리허설
- 원장 결재: 엑셀 출력 허용(P12 개정, D10), 보관기간(Q06), 권한표(Q01)

## 6. Privacy & Security 등급

| 등급 | 예 | 취급 |
|---|---|---|
| Green | 가상 환자, 랜덤 ID, 업무 유형, 익명 통계, 공개 자료 | 프로토타입·저장소·AI 사용 가능 |
| Yellow | 차트번호, 검사일+검사종류 조합, 세부 업무 로그 | 원내 DB에만 |
| Red | 이름, 주민번호, 전화번호, 주소, 실제 진료기록·검사결과·처방 | 외부 AI·GitHub 금지 |

## 7. Testing Strategy

| 종류 | 대상 | 현재 |
|---|---|---|
| Unit | Rule, 파서(결과 표기·엑셀), 상태 전이, 진료일 계산 | ✅ 결과 표기·진료일·상태 / 🔴 Rule·Task(Stage B) |
| Integration | PostgreSQL, Alembic up/down/up, 화면·권한·CSRF, 엑셀 가져오기 | ✅ |
| Scenario | 가상 환자: 접수 → 인계 → 결과 → 원장 지시 → 재검 도래 | ✅ 브라우저 확인 / 🟡 자동 시나리오 시험은 Stage B에서 고정 시계 E2E로 |
| CI | PR마다 pyflakes + Compose 구성 + pytest(PostgreSQL 16) | ✅ |

## 8. 오래 남을 질문 — 지금 답할 수 있는가

| 질문 | 현재 |
|---|---|
| 오늘 놓치면 안 되는 업무는? | 🟡 조직검체·CLO·Stool 범위에서 (대시보드) |
| 결과가 아직 오지 않은 조직검체는? | ✅ 결과 대기 + 지연 표시 |
| 결과는 왔는데 원장 확인(지시)이 안 된 건은? | ✅ 원장 지시 대기 |
| 이번 달 재검 예정 환자는? | ✅ 재검 대상 → 이번 달, 대상자 엑셀 출력 |
| 검진 후 F/U가 끝나지 않은 건은? | ⚪ Stage D |
| 누가 언제 어떤 환자 정보를 봤는가? | ✅ 접속기록 점검 |

이 질문의 답은 LLM의 기억이나 추측이 아니라 **Ontology + Database + Rules + Tasks**로 정해져야 한다.

## 9. Success Metrics

- **업무 효과:** 결과 누락 탐지 건수, 미완료 F/U 건수, Overdue 감소, 수기 대장 확인 시간 감소, 병행 기간 엑셀·DB 차이 0건 유지
- **기술 학습:** Python, PostgreSQL, SQLAlchemy, Alembic, FastAPI, pytest, Docker, GitHub Actions, Ontology, FHIR, Rule Engine, Agent Architecture
- **포트폴리오:** README, 아키텍처·ERD·온톨로지 다이어그램, ADR, 합성 자료 데모, 케이스 스터디

> 일반 내과의원의 내시경·조직검체 업무를 분석해 분산된 장부를 공통 모델로 통합하고, 개인 계정·접속기록을 갖춘 내부망 시스템에서 누락 가능한 후속업무(인계·결과 지연·재검 도래)를 찾아내도록 설계·개발했다. 이후 Rule/Task Engine, Lab·검진·Recall 모듈, FHIR 대응과 Agent 도구 계층으로 확장한다.

---

> **From fragmented clinic data to connected operational knowledge.**
> 흩어진 의원 데이터를 연결된 업무 지식으로 바꾼다.
