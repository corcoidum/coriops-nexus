# PATH.R01~R08 — 생성·기한·해소

임계값·역할·제목은 `config/rules.yaml`, 진료시간은 `config/clinic.yaml`이 원천이다. 이 문서의 숫자는 설계 설명이며 구현 코드에 임계값을 넣지 않는다. 생성 시점 분리는 사용자 승인(A01), NEXT_VISIT 확대는 Q04 승인 전 제안이다.

**2026-10-22 업무 확인 반영:** 씨젠의 일반 경로는 환자별 전체 결과 공개 후 접수(A04)다. 사무장과 지정 직원 1명이 먼저 확인하며 전건 원장 보고는 아니다(A05). 아래 R03과 원장 확인을 선행하는 R04·R06·종결 근거는 이전 설계안으로, Q17 답변 후 재설계한다. '선행 단계 직후 생성'이라는 A01의 원칙과 '누가 어떤 확인을 맡는가'는 별도 결정이다. 기존 config를 그대로 구현하거나 R03을 임의로 삭제·전건 직원 확인으로 변경하지 않는다.

| Rule | 생성 조건·시점 | due_at | 조건 해소·자동 해소 | 대상·회차 |
|---|---|---|---|---|
| R01 | DRAFT, 채취일 마감 도달 | 해당 마감 | 발송 또는 유효한 취소 | 의뢰·현재 회차 |
| R02 | SHIPPED + 발송 후 7 달력일 도달 + 전체 coverage 미완료 | shipped_at + 7일 | 전체 결과 수신, 유효한 취소·분실 | 의뢰·현재 회차 |
| R03 | 전체 결과 수신 직후, 유효한 현재 원장 확인 없음 | 수신 기준일 제외 1번째 진료일 마감 | 최신 버전 집합 원장 확인 | 의뢰·현재 회차 |
| R04 | REVIEWED + CALL 직후. NEXT_VISIT도 포함 제안 | 확인일 제외 2번째 진료일 마감. URGENT 당일 | 현 회차 REACHED 또는 승인된 NONE 생략 | 의뢰·현재 회차 |
| R05 | 현 회차 실패 결과가 3회 이상이고 아직 REACHED 아님 | 임계 횟수 도달 시각 | 성공 안내·승인 생략·새 회차 | 의뢰·현재 회차 |
| R06 | NOTIFIED 또는 승인 생략 직후 + REQUIRED + 유효 F/U 없음 | 안내·생략일 제외 2번째 진료일 마감 | CURRENT 유효 F/U 등록, 또는 원장 불필요 정정 | 의뢰·현재 회차 |
| R07 | PLANNED + 0≤due_date−오늘≤30일 | due_date의 KST 마지막 시각 | BOOKED·DONE·CANCELLED, 날짜 경과 시 R08로 인계 | F/U 계획·계획 회차 |
| R08 | PLANNED 또는 BOOKED + 오늘>due_date + 미완료 | due_date의 KST 마지막 시각 | DONE 또는 사유 있는 원장 취소·날짜 정정 | F/U 계획·계획 회차 |

`CLOSED` 의뢰에서 유래한 F/U라도 R07·R08 평가를 계속한다. 원장이 재검토 중인 기존 계획도 자동 해소하지 않는다. `CANCELLED/LOST`를 누락 은폐에 쓰지 않도록 원장 승인·사유가 필요하며 재채취는 새 시행·의뢰로 수동 연결할 운영 절차를 확인한다(Q02).

## 진료일·경계

- 진료일 = 일요일 등 휴진 요일 제외 ∩ KR 공휴일/대체공휴일 제외 ∩ 임시 휴진일 제외. 반일도 1일이다.
- 기준일은 제외하고 N번째 진료일의 요일별 마감을 기한으로 사용한다. URGENT는 입력 당일 마감, 이미 마감 뒤면 입력 즉시 기한 도달로 처리한다.
- 기한 도달 자체(`now == due_at`)와 지연(`now > due_at`)은 구분한다. R01/R02는 기한 도달 시 생성한다. date 기준 R08은 기한일 다음날 00:00부터다.
- 연체일 표시는 달력 경과일, 진료일 기한은 별도 표시한다. 30분 스케줄은 업무 생성 지연 상한일 뿐 임상 대응 보장이 아니다.

## Engine 계약

`evaluate(session, now, params) -> list[TaskCandidate]`는 조회 전용이다. Candidate는 rule namespace, subject, cycle, title, priority, role, due_at만 가진다. Engine이 저장·감사를 담당한다. RuleRun에 평가 now·config hash를 기록하여 고정 Clock으로 재현한다.

1. `rule_id:subject_type:subject_id:cycle_id` UNIQUE upsert. 연속 실행과 수동/주기 동시 실행에서 Task 수가 늘지 않는다.
2. 조건이 참이면 OPEN 유지·기한/우선순위 변경 Audit. 같은 조건에서 DISMISSED는 재생성하지 않는다. 사유 없는 DISMISSED는 거부한다.
3. 성공한 평가에서 조건이 사라지면 OPEN → AUTO_RESOLVED와 Audit. DISMISSED는 보존하되 condition_cleared_at을 기록한다. 평가 실패·비활성 Rule은 조건 해소로 간주하지 않는다.
4. 같은 회차에서 조건이 다시 참이면 AUTO_RESOLVED 또는 해소를 확인한 DISMISSED 행을 OPEN으로 재개하고 Audit. 계속 참인 DISMISSED는 억제를 유지한다.
5. 실제 재작업은 새 WorkCycle을 만들어 새 Task를 허용한다. 구 회차 OPEN은 사유 `CYCLE_SUPERSEDED`로 자동 해소한다. 구 DISMISSED·완료 이력은 보존한다.
6. 원인 업무가 남아 있는데 DONE만 눌러 숨길 수 없다. 실제 업무 폼 완료로 조건을 해소하거나 사유를 남겨 DISMISSED한다. Task는 임상 판단을 대신하지 않는다.

R07 예약 후 취소하여 PLANNED로 돌아가는 경우는 새 계획 WorkCycle로 처리한다. 날짜 수정도 새 회차다. 이전 Task를 삭제하지 않는다.

## 수정 E2E — Asia/Seoul, 고정 Clock

아래는 원장 보고·지시를 받는 경로의 기존 검토 시나리오다. 모든 결과에 강제하는 일반 경로가 아니며, 원장 미보고 결과의 경로는 Q17 확정 후 추가한다.

| 시각 | 동작 | 기대 결과 |
|---|---|---|
| 2026-11-05 목 10:00 | 테스트 환자, 대장내시경, 용종절제 검체 2병 | DRAFT |
| 11-05 18:01 | 점검 | R01 OPEN, 기한 경과 |
| 11-06 금 10:00 | 발송 | SHIPPED, R01 AUTO_RESOLVED |
| 11-13 금 10:00 | 결과 없음 점검 | R02 OPEN, due=동일 시각 |
| 11-16 월 10:00 | 두 검체 결과 수신 | RESULT_RECEIVED, R02 해소, **R03 즉시 OPEN**, due=11-17 18:00 |
| 11-17 화 10:00 | 원장 BENIGN/ROUTINE/CALL, REQUIRED, PATH.ENDOSCOPY, due 2027-11-17 입력 | REVIEWED, R03 해소, **R04 즉시 OPEN**, due=11-19 18:00 |
| 11-17 11:00·14:00 | NO_ANSWER 2회 | R05 없음, R04 유지 |
| 11-17 16:00 | 3회차 REACHED | NOTIFIED, R04 해소, R05 없음, **R06 즉시 OPEN**, due=11-19 18:00 |
| 11-19 목 18:01 | F/U 계획 아직 미등록 | 기존 R06 기한 경과. 새 Task 생성 아님 |
| 11-20 금 10:00 | 원장 지정 기한의 F/U 계획 등록 | R06 해소, CLOSED. 계획의 독립 회차 생성 |
| 2027-10-18 월 10:00 | 점검 | due까지 30일, R07 OPEN |

추가 경로: 씨젠 일반 결과는 전체 공개 전 SHIPPED를 유지하고 전체 공개 후 접수한다. 이전의 '검체 1병만 먼저 수신' 시나리오는 현재 일반 업무 시나리오에서 제외하며 모델 유지 여부는 Q02 예외 확인 뒤 결정한다. 안내 3회 모두 실패하면 R05 생성, 이후 REACHED면 해소하는 경로는 유지한다. 정정본 접수 시 새 회차·구 F/U 재확인 원칙을 유지하되 직원 확인·원장 보고 Task 배정은 Q17 확정 후 갱신한다.

Dashboard는 Overdue=`OPEN and now>due_at`, Today=오늘 기한인 OPEN 중 지연 제외, Pending=나머지 OPEN, Done=최근 7일 DONE/AUTO_RESOLVED/DISMISSED(상태 표시)로 중복 없이 나눈다. 우선순위→기한→생성시각 순 정렬, 내 역할 필터는 effective roles 집합으로 검사한다.
