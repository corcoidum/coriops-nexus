# AGENTS.md — AI 코딩 도우미 작업 규칙

이 저장소에서 일하는 모든 AI 도우미(Claude Code, Codex 등)와 사람이 따르는 규칙이다. 목적·단계는 [ROADMAP.md](ROADMAP.md), 결정 기록은 [docs/open-questions.md](docs/open-questions.md)에 있다.

## 1. 절대 규칙 — 어기면 작업을 멈추고 사용자에게 묻는다

1. **실제 환자정보를 저장소·커밋·PR·이슈·채팅·스크린샷·테스트에 넣지 않는다.**
   - 이름, 차트번호, 주민번호, 연락처, 주소, 실제 검사결과는 모두 해당한다.
   - 시험·예시는 합성 자료만 쓴다. 이름은 `테스트…`·`합성…`, 차트번호는 `T-0001`처럼 만든다.
   - `.xlsx`·`.csv`·DB 덤프는 `.gitignore`로 막혀 있다. 이 규칙을 우회하지 않는다.
2. **의료 판단을 코드로 만들지 않는다.**
   - 진단, 결과의 임상 의미, 재검 필요 여부·주기는 원장이 정하고 사람이 입력한다.
   - 시스템은 상태·기한·누락만 계산한다.
   - 결과 코드의 의미·중요도를 임의로 채우지 않는다(Q19).
3. **조직검사 결과는 등록 코드 표기만 저장한다(A11).** 판독문 원문·자유서술을 저장하는 필드를 만들지 않는다.
4. **실행 중 외부 통신을 추가하지 않는다.**
   - 외부 API·CDN·텔레메트리·외부 LLM 호출을 넣지 않는다.
   - DB 외 발신은 `app.demo_server`·`app.ledger_server`가 막고 있으며, 이 차단을 풀지 않는다.
5. **비밀값을 커밋하지 않는다.** 비밀번호·토큰·`.env`가 대상이다. 접속 정보는 환경변수로만 받는다.
6. **접속기록·권한 이력·점검 기록은 추가만 한다.** UPDATE·DELETE 경로를 만들지 않는다(DB 트리거가 거부한다).

## 2. 구조

| 위치 | 역할 |
|---|---|
| `app/kernel/` | 공통 기능: 시계, 진료일 달력, 로그인·세션·권한(`auth.py`), 접속기록(`access_log.py`), 화면 공통(`web.py`). **업무 모듈을 import하지 않는다** |
| `app/modules/endoscopy_pathology/` | 조직검체·CLO·Stool 장부 업무. 라우트는 서비스(`manual_dashboard.py`)만 호출한다 |
| `app/main.py` | 조립 지점. DB 모드면 로그인·접속기록을 항상 켠다 |
| `migrations/` | Alembic. 스키마 변경은 반드시 새 리비전으로, downgrade도 작성한다 |
| `config/*.yaml` | 진료시간·수령시각·권한표·보관기간·엑셀 매핑. 숫자를 코드에 하드코딩하지 않는다 |
| `ontology/coriops.yaml` | 정식 도메인 모델의 원천. `docs/ontology.md`·`erd.md`·`state-machine.md`·`fhir-mapping.md`는 여기서 생성한 사본이며 직접 고치지 않는다 |
| `tests/prototype/` | pytest. 시계는 고정(`FixedClock`)하고, 화면은 실제 링크를 따라가 본다 |

새 업무 영역(Lab·검진·Recall)은 `app/modules/<이름>/`에 모듈로 추가한다. kernel에 업무 이름을 넣지 않는다.

## 3. 로컬 검사 — PR 전에 반드시 통과

```sh
python -m pip install '.[test]'
python -m pyflakes app tests migrations
# PostgreSQL 16이 필요하다(docker compose --profile test 또는 로컬 설치).
PGHOST=127.0.0.1 PGPORT=5432 PGUSER=coriops_test PGDATABASE=coriops_test python -m pytest -q
```

GitHub Actions(`.github/workflows/ci.yml`)가 PR마다 같은 검사를 실행한다. 빨간 CI는 병합하지 않는다. 시험을 건너뛰거나 지워서 통과시키지 않는다.

## 4. 작업 방식

- **PR 하나에 목적 하나.** 문서·설정·코드가 함께 바뀌면 같은 PR에서 맞춘다.
- **결정은 기록한다.** 사용자 결정은 `docs/open-questions.md`의 A번호, 미결 질문은 Q번호, 명세 충돌은 `docs/conflict-resolution.md`의 D번호로 적는다. 번호를 다시 쓰지 않는다.
- **검증 범위를 정직하게 적는다.** 실행한 것과 하지 않은 것(예: Docker 미실행)을 구분한다. 자동 시험 통과를 법적 적합성이나 원내 운영 준비 완료로 표현하지 않는다(TECH/OPS/LEGAL 구분).
- **화면을 바꾸면 실제 브라우저로 확인한다.** 링크·버튼을 눌러 보고, 필요하면 링크를 따라가는 시험을 추가한다.
- 코드 주석·문서는 한국어, 식별자는 영어로 쓴다. 기존 코드의 문체와 주석 밀도를 따른다.
- 새 패키지는 버전을 고정하고, 지정 스택 밖이면 PR에 이유를 적는다.

## 5. 개인정보 등급 (ROADMAP 9장)

| 등급 | 예 | 취급 |
|---|---|---|
| Green | 합성 환자, 랜덤 ID, 업무 유형, 익명 통계, 공개 자료 | 저장소·AI 사용 가능 |
| Yellow | 차트번호, 검사일+검사종류 조합, 세부 업무 로그 | 원내 DB에만. 외부로 보내지 않는다 |
| Red | 이름, 주민번호, 전화번호, 주소, 실제 진료기록·검사결과·처방 | 외부 AI·GitHub 금지 |
