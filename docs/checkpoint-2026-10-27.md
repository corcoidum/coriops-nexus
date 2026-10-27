# 2026-10-27 작업 인계

오늘까지 구현한 코드는 `codex/form-input-improvements` 브랜치에 있다. PR 병합 전에는 `main` 대신 이 브랜치를 받아 확인한다.

## 집 PC에서 실행

Docker Desktop을 실행한 뒤 PowerShell에서 새 폴더로 받는다.

```powershell
git clone --branch codex/form-input-improvements --single-branch https://github.com/corcoidum/coriops-nexus.git
cd coriops-nexus
docker compose -f docker-compose.prototype.yml --profile dashboard up -d --build dashboard
```

브라우저에서 <http://127.0.0.1:8765/>를 연다. 이 시연은 `.env` 없이 실행한다. 오늘 작업 PC의 8879번 주소는 별도 확인용이며 집 PC의 기본 주소는 8765번이다.

기존 저장소 폴더를 쓰려면 먼저 `git status --short`로 미커밋 변경을 확인한다. 작업 내용이 없는 경우 다음 명령으로 받는다. 변경이 있으면 먼저 별도 보관하고 진행한다.

```powershell
git fetch origin
git switch codex/form-input-improvements
git pull --ff-only origin codex/form-input-improvements
docker compose -f docker-compose.prototype.yml --profile dashboard up -d --build dashboard
```

합성 시연 입력은 메모리에만 남으며 재시작·재빌드하면 초기화된다. 작업 PC의 시연 입력·DB·업로드 파일은 Git으로 옮기지 않는다. DB 저장 모드는 [장부 앱 사용법](ledger-app.md)의 별도 설정을 따른다. 혈액·위급치 화면은 합성 시연 전용이며 DB 모드에는 아직 조립하지 않는다.

## 구현한 내용

- 혈액 H/L 결과는 빈 1줄로 시작하며 추가·줄별 삭제가 가능하다. 정상 확인 체크박스 정렬을 고치고 Anti-HCV Neg/Pos를 추가했다. 간염의 필수 표시를 없애고 기본 문구를 `결과 선택`으로 통일했다. 접수한 검사 종류에 따른 기존 결과 검증은 유지한다.
- CLO 결과의 부위 입력과 조직검체 접수의 RUT 입력을 없앴다. CLO는 별도 대장에서 관리하며 판정이 없거나 검토가 필요한 기록은 결과 대기에 남는다.
- 테스트 DB 전용 주소·초기화 허용을 검사한다. DB 장부 업무·접속기록·관련 작업 변경이 한 트랜잭션에서 성공하거나 함께 되돌아가도록 보완했다. 같은 접수번호를 다른 환자로 잘못 합치는 경우를 거부한다.
- 분변잠혈 접수에서 병 수를 없앴다. 당일 제출 대상자 접수 → 다음날 결과 입력 → 원장 확인 흐름이다. 별도 인계 조작은 없으며 과거 병 수·인계 원본은 보존한다.
- 메뉴를 병리(조직검체·재검 도래·CLO·종이대장·엑셀), 혈액(혈액검체·종이대장), 미생물(분변잠혈)로 나눴다. 전체 재검 대상은 재검 도래 화면에서 기간을 바꿔 확인한다.
- 위급치 보고는 독립 메뉴(`/critical`)로, 보고 완료 시 다음 대기 건을 보여준다. 혈액 종이대장(`/lab/paper`)은 기존 13열 설정·현재 입력 결과를 공유하는 조회 전용 화면이다. 수기 서명 칸은 공란이다.

사용자 결정은 [A28~A32](open-questions.md)에 기록했다. 위급치 판정·결과 해석·재검 주기를 자동으로 결정하는 기능은 추가하지 않았다.

## 검증 기록

- 격리된 일회용 PostgreSQL 16 + Python 3.12 환경에서 전체 pytest **529건 통과**.
- 마지막 화면 수정 후 혈액 대시보드·장부 관련 pytest **93건 통과**.
- pyflakes, 생성 문서 일치 검사 통과.
- 실제 Chrome에서 세 분류의 전체 메뉴, 현재 메뉴 표시, 혈액 종이대장 기간 필터, 위급치 2 → 1 → 0건 보고 흐름을 확인했다. 390px 화면에서 새 표는 내부 가로 스크롤로 표시된다.
- 실제 환자자료·실운영 전환·집 PC 실행은 검증 범위에 포함하지 않는다. GitHub CI 결과는 PR에서 확인한다.

집에서 우선 볼 항목은 세 분류의 메뉴 배치, 혈액 종이대장 대조, 독립 위급치 보고 흐름이다. 미세한 표시 문구·여백 조정은 확인 후 이어간다.
