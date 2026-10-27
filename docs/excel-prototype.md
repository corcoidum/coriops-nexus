# 17열 Excel 프로토타입

이 문서는 Excel 프로토타입을 만든 당시의 기록이다. 이후 첫 화면은 [수동 대시보드](manual-dashboard.md)로 추가했으며 씨젠 자동화·약어 변환은 보류했다. 아래 40개는 당시 시험 결과이고, 현재 전체 prototype 시험은 267개다.

2026-10-22 사용자가 약어 사전은 나중에 제공하고 다음 단계로 진행하도록 지시했다. 이에 따라 **씨젠 접속 없이 합성 자료를 17열 양식으로 옮기는 범위**를 먼저 구현한다. 정식 Phase 1 전체 완료·원내 배포·실데이터 전환 승인을 뜻하지 않는다.

## 확인된 형식과 처리

열 순서는 `app/modules/endoscopy_pathology/ledger_mapping.yaml`에 사용자 제공 그대로 정의한다. 한 시트만 만들며 숨김 열·추가 환자정보·재검 날짜 열을 임의로 추가하지 않는다. 다음 내시경 시점은 원장 지시를 별도로 기록할 이후 기능이다.

| 분류 | 열 | 프로토타입 처리 |
|---|---|---|
| 자동 전사 후보 | 접수번호·차트번호·수진자명·성별 | 합성 fixture 값을 옮김. 번호는 앞자리 0을 유지하는 문자열 |
| 출처·의미 확인 필요 | 검사일·나이·위탁일·검사종류·검체수량·결과보고일 | 합성 fixture에 명시된 값만 옮김. 날짜·나이·검체 단위를 추론하지 않음 |
| 약어 사전 대기 | 검사위치·조직검사결과 | `검토 필요` 표시, ABBREVIATION_PENDING 검토 항목 생성. 원문을 셀에 대신 넣지 않음 |
| 직원 입력 보존 제안 | 접수인·인계인·인수인·특이소견·비고란 | 신규 행은 빈칸, 기존 행은 변경하지 않음. 실제 소유권은 원내 업무 확인 필요 |

## 입력·갱신·저장 계약

- 시연 입력은 이름이 `테스트`로 시작하는 합성 자료만 제공한다. CLI에는 실파일 입력·계정·URL 접속 옵션이 없다.
- 합성 중복 키는 `(접수번호, 차트번호)`다. 원내 접수번호 의미·한 행의 단위가 아직 확정되지 않아 실운영 매칭으로 사용하지 않는다.
- 같은 배치 또는 전달받은 메모리 fingerprint에서 같은 키·내용이면 새 행을 만들지 않는다. 같은 키의 내용이 바뀌면 SOURCE_CHANGED로 남기고 기존 행을 보존한다.
- 기존 workbook에 대응하는 fingerprint가 없으면 EXISTING_ROW_REVIEW로 남긴다. 원본 정정인지 직원 편집인지 알 수 없는 행을 자동 덮어쓰지 않는다. fingerprint는 이 프로토타입에서 메모리에만 존재하며 저장·재시작 후 자동 정정 비교는 아직 구현하지 않는다.
- 헤더 불일치·기존 중복 키·키 누락을 거부한다. 오류 메시지·검토 항목은 코드·행·열만 갖고 환자값·원문을 포함하지 않는다.
- 문자열이 `=` 등으로 시작해도 수식으로 저장하지 않는다. 날짜·정수는 실제 Excel 타입으로 쓴다. 나이는 제공된 표기를 보존하며 생년월일로 역산하지 않는다.
- 원문은 변환 입력의 메모리에서만 다루고 workbook·출력 로그에 넣지 않는다. fingerprint는 익명화 증거가 아니며 실데이터 보유 정책을 대신하지 않는다.
- 산출물은 **새 파일**로만 저장한다. 동일 경로가 이미 있으면 FileExistsError로 중단하고 원본을 유지한다. 파일 잠금·동시 편집·실제 양식 수식 보존을 포함한 원본 갱신기는 이후 범위다.

## 정확한 실행 명령 — Windows PowerShell

Docker Desktop 실행 후 저장소 루트에서:

```powershell
# 합성 PostgreSQL 테스트 DB용 임시 비밀번호. 저장소·명령 출력에 기록하지 않는다.
$env:CORIOPS_TEST_DB_PASSWORD = [guid]::NewGuid().ToString("N")
docker compose -f docker-compose.prototype.yml --profile test run --build --rm test

# 네트워크가 없는 컨테이너에서 합성 Excel 생성
docker compose -f docker-compose.prototype.yml --profile demo run --build --rm demo
```

파일: `outputs/01a15ebd-ee2d-7793-a059-7cf7132919ed/ledger-demo.xlsx`. 이미 있으면 원본을 보존하고 다른 새 출력 경로를 지정한다.

```powershell
docker compose -f docker-compose.prototype.yml --profile demo run --rm demo python -m app.modules.endoscopy_pathology.ledger_demo --output /outputs/01a15ebd-ee2d-7793-a059-7cf7132919ed/ledger-demo-new.xlsx
```

시험 DB는 호스트 포트 없이 내부 Docker network·tmpfs만 사용한다. SQLite를 사용하지 않는다. PostgreSQL 16 연결 확인과 Excel 로직의 순수 단위 시험을 구분한다. 앱의 DB 모델·마이그레이션·인증·감사기록·전체 coverage는 아직 구현 범위 밖이다.

## 의존성과 다음 범위

production 의존성은 지정된 openpyxl 3.1.5와 YAML 파서 PyYAML 6.0.3이다. pytest·psycopg는 시험 extras로 분리한다. Python은 3.12, 시험 DB는 PostgreSQL 16을 유지한다. Python 데모 생성 코드는 지정 스택의 openpyxl을 사용하며 산출물 시각 검토는 별도 artifact 도구로 수행한다.

제공 URL `https://srms.seegenemedical.com/main.do`에 인증정보 없이 접근하면 `/session_out.jsp`로 이동하는 것만 확인했다. 로그인 뒤 DOM·다운로드·MFA·API는 확인하지 않았다. 약어는 사용자 요청대로 보류하고, 실제 수집 경로 확인·검토 화면·원장 지시 기록·영구 갱신 이력을 다음 범위에서 이어간다.

## 구현·검증 보고

### [완료] 파일과 역할

- `app/modules/endoscopy_pathology/ledger.py`: 정책 읽기·입력 사전 검증·신규 행 추가·중복/변경 검토·새 파일 저장.
- `ledger_demo.py`: 실제 파일·계정 입력이 없는 합성 자료 3건 시연.
- `app/modules/endoscopy_pathology/ledger_mapping.yaml`: 사용자 제공 17열의 순서·타입·폭·보류/수동 열 정책.
- `tests/prototype/`: 장부 계약·실제 PostgreSQL16 연결·외부 socket 차단 시험.
- `pyproject.toml`, `Dockerfile.prototype`, `docker-compose.prototype.yml`, `.dockerignore`: Python3.12 실행·내부 DB 시험·네트워크 없는 시연 환경.
- README·확인사항·ADR-005·로드맵·검증계획: 사용자 A08/A09와 실제 구현 범위를 반영.

### [결정·근거]와 [가정]

기존 직원 입력을 보호하기 위해 프로토타입은 기존 행을 변경하지 않고 새 파일에만 쓴다. 임의 약어·원문 전사를 하지 않으며 두 열은 검토 항목으로 남긴다. 키 의미·행 단위·자동 열 소유권·실제 양식의 수식은 미확정이다. PyYAML은 매핑 YAML을 읽는 production 추가 의존성이고, 나머지는 지정된 openpyxl·pytest·psycopg다.

### [검증] 실행 결과 — 2026-10-22

| 실행 | 결과 |
|---|---|
| Docker Compose prototype build | Python3.12 이미지와 고정 의존성 빌드 성공 |
| PostgreSQL16 내부 시험 DB + `python -m pytest -q` | **40 통과 / 0 실패**, 최종 실행 0.27초 |
| 네트워크 없는 demo 실행 | 합성 행 3개, 재실행 중복 추가 0개, 약어 검토 6개 |
| 저장 후 openpyxl 재열람 | 차트번호 앞자리 0·문자열 타입·17열·검토 표시 확인 |
| Artifact 도구 import·recalculate·수식 오류 검사·시각 검토 | 오류 검색 0건, 단일 시트 렌더 확인. 성별 표시 폭 보완 |
| Compose 설정 검증 | host port 노출 0, 테스트 network internal, demo network none |
| `git diff --check` | 공백 오류 없음 |

추가 검토에서 금지 제어문자·Excel 셀 길이 초과가 배치를 부분 수정할 위험을 발견해, 쓰기 전 배치 전체를 검사하고 고정 오류 코드로 거부하도록 보완했다. 10개 경계 사례를 추가한 최종 결과가 40개다. 렌더 엔진은 숫자형 문자열을 숫자로 읽어 표시할 수 있어 미리보기의 8자리 표시를 보정했고, **실제 저장 파일의 문자열·앞자리 0은 별도 재열람 시험**으로 검증했다. 원본 파일의 번호는 변경하지 않았다.

### [개인정보]·[확장 계약]·[리스크]

이번 자료는 전부 합성이며 인증정보·실자료를 수집하지 않았다. 원문은 workbook·로그·검토 항목에 저장하지 않는 시험을 통과했다. 이는 실제 환자용 접근통제·암호화·Audit/AccessLog·파기·백업(P1~P14 전체) 충족 증거가 아니다. DB는 시험 환경 확인에만 사용하며 업무 모델·마이그레이션·원장 결정 저장은 미구현이다. 전체 앱 coverage 90%는 아직 측정·충족하지 않았다.

모듈 경계를 지키고 미래 Lab·AI 기능은 추가하지 않았다. C1~C8의 정식 구현 계약 전체를 검증한 상태는 아니다. 임시 fingerprint는 재시작하면 사라지므로 실제 장부 정정·감사 이력 대조를 대신하지 않는다. 파일 잠금·손상·원자적 교체를 갖춘 실파일 갱신기와 웹 UI도 아직 없다.

### [다음 범위]

1. 합성 결과의 미리보기·검토 대기 화면을 원내 웹 흐름에 연결할 범위를 정한다.
2. 씨젠 로그인 방식·공식 다운로드/허용 연동을 원내에서 확인하고 수집 adapter를 선택한다.
3. 정식 DB 모델·변경 이력·권한·원장 지시·실파일 갱신을 기존 Phase Gate에 맞춰 구현한다. 약어 사전은 준비되는 때 별도 추가한다.
