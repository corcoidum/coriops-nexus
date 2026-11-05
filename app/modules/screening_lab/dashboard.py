"""혈액검체 결과 확인 흐름을 합성 자료로 확인하는 메모리 서비스. 영구 저장하지 않는다.

결과 해석·위급치 판정은 하지 않는다. 직원은 씨젠 결과지(PDF)에서 H/L로 표시된 항목과
정성 검사 Neg/Pos만 옮겨 적고(B14·B16), 위급치는 관리자가 확인한 뒤 표기한다(B15).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from threading import RLock
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import yaml

from app.kernel.clock import Clock, SystemClock
from app.kernel.web import UserError

from .ledger import NOTE_MAX, LabItem, LabLedgerPolicy, LabRecord, load_policy
from .ledger_demo import synthetic_records
from .model import LabCase
from .store import MemoryLabStore, PostgresLabStore


STAGE_LABELS = {
    "RESULT_PENDING": "결과 미수신",
    "CRITICAL_PENDING": "원장 보고 대기",
    "CHECK_PENDING": "확인 대기",
    "DONE": "확인 완료",
}
STAGE_ACTIONS = {
    "RESULT_PENDING": "결과 입력",
    "CRITICAL_PENDING": "원장 보고 기록",
    "CHECK_PENDING": "확인 기록",
    "DONE": "기록 보기",
}
KST = ZoneInfo("Asia/Seoul")
NAME_MAX = 20
REF_MAX = 30
VALUE_MAX = 20


class LabDashboardService:
    def __init__(self, clock: Clock | None = None, policy: LabLedgerPolicy | None = None,
                 store: MemoryLabStore | PostgresLabStore | None = None):
        self._clock = clock or SystemClock()
        self._policy = policy or load_policy()
        self._lock = RLock()
        self._store = store or MemoryLabStore()
        self._registration = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "lab_workflow.yaml").read_text(encoding="utf-8"))["registration"]
        if not self.persistent:
            self.reset()

    @property
    def persistent(self) -> bool:
        return self._store.persistent

    def transaction(self):
        return self._store.transaction()

    def register(self, *, chart_no: str, patient_name: str, received_date: date | None,
                 exam_kinds: list[str], registered_by: str, sex: str = "", age: str = "",
                 intake_id: UUID | None = None) -> UUID:
        chart_no, patient_name, sex, age = (v.strip() for v in (chart_no, patient_name, sex, age))
        if not chart_no or len(chart_no) > self._registration["chart_max_length"]:
            raise UserError("차트번호 길이를 확인해 주세요.", 422)
        if not patient_name or len(patient_name) > self._registration["patient_name_max_length"]:
            raise UserError("성명을 확인해 주세요.", 422)
        now = self._clock.now()
        if received_date is None or received_date > now.astimezone(KST).date():
            raise UserError("접수일을 오늘 이전 날짜로 선택해 주세요.", 422)
        if not exam_kinds or not set(exam_kinds) <= set(self._policy.exam_kinds):
            raise UserError("검사 분류를 선택해 주세요.", 422)
        if sex and sex not in self._registration["sexes"]:
            raise UserError("성별을 목록에서 선택해 주세요.", 422)
        if age and (not age.isascii() or not age.isdigit() or int(age) > self._registration["maximum_age"]):
            raise UserError("나이를 확인해 주세요.", 422)
        record = LabRecord("", chart_no, patient_name, received_date=received_date, sex=sex or None,
                           age=age or None, exam_kinds=tuple(dict.fromkeys(exam_kinds)))
        case_id = intake_id or uuid4()
        with self._lock:
            existing = next((case for case in self._store.cases() if case.id == case_id), None)
            if existing is not None:
                old = existing.record
                if (old.chart_no, old.patient_name, old.received_date, old.exam_kinds, old.sex, old.age) != (
                        record.chart_no, record.patient_name, record.received_date, record.exam_kinds, record.sex, record.age):
                    raise UserError("이미 사용한 접수 요청입니다. 기존 기록을 확인해 주세요.", 409)
                return case_id
            self._store.write(LabCase(case_id, record, registered_by=self._name(registered_by, "접수 직원")), now)
        return case_id

    def _save(self, previous: LabCase, changed: LabCase) -> None:
        self._store.write(changed, self._clock.now(), previous.version)

    def _get(self, case_id: UUID) -> LabCase:
        case = next((case for case in self._store.cases() if case.id == case_id), None)
        if case is None:
            raise UserError("접수 항목을 찾을 수 없습니다.", 404)
        return case

    def result_text(self, case: LabCase) -> str:
        return self._policy.result_text(case.record) or ""

    def paper_snapshot(self, start: date | None = None, end: date | None = None) -> dict:
        with self._lock:
            today = self._clock.now().astimezone(KST).date()
            end = end or today
            start = start or end.replace(day=1)
            if start > end:
                raise UserError("종료일은 시작일 이후로 선택해 주세요.", 422)
            cases = [case for case in self._store.cases()
                     if case.record.received_date and start <= case.record.received_date <= end]
            cases.sort(key=lambda case: (case.record.received_date, case.record.chart_no, str(case.id)))
            rows = [{"id": case.id, "values": self._policy.row_values(
                replace(case.record, patient_name=case.display_name))} for case in cases]
            return {"today": today, "start": start, "end": end, "rows": rows, "cases": cases,
                    "headers": self._policy.headers, "paper_title": self._policy.title, "lab_persistent": self.persistent}

    def snapshot(self, stage: str = "ALL", selected_id: UUID | None = None) -> dict:
        with self._lock:
            if stage != "ALL" and stage not in STAGE_LABELS:
                raise UserError("알 수 없는 업무 분류입니다.", 422)
            all_cases = self._store.cases()
            counts = {key: sum(case.stage == key for case in all_cases) for key in STAGE_LABELS}
            cases = [case for case in all_cases if stage == "ALL" or case.stage == stage]
            selected = self._get(selected_id) if selected_id else (cases[0] if cases else None)
            return {
                "cases": cases,
                "counts": counts,
                "selected": selected,
                "results": {case.id: self.result_text(case) for case in all_cases},
                "today": self._clock.now().astimezone(KST).date(),
                "stage": stage,
                "stage_labels": STAGE_LABELS,
                "stage_actions": STAGE_ACTIONS,
                "total": len(all_cases),
                "kst": KST,
                "item_names": self._policy.item_names,
                "result_flags": self._policy.result_flags,
                "qualitative_values": self._policy.qualitative_values,
                "qualitative_for": self._policy.qualitative_for,
                "qualitative_items": self._policy.qualitative_for(self._policy.exam_kinds),
                "lab_persistent": self.persistent, "exam_kinds": self._policy.exam_kinds,
                "intake_id": uuid4(), "registration": self._registration,
            }

    def _name(self, value: str, label: str) -> str:
        clean = value.strip()
        maximum = self._registration["staff_identity_max_length"] if self.persistent else NAME_MAX
        if not clean or len(clean) > maximum:
            raise UserError(f"{label}을(를) 1~{maximum}자로 입력해 주세요.", 422)
        return clean

    def enter_result(self, case_id: UUID, *, report_ref: str, report_date: date | None,
                     rows: list[tuple[str, str, str]], qualitative: dict[str, str], no_flagged: bool,
                     entered_by: str) -> None:
        """결과지에서 H/L 항목과 정성 검사만 옮겨 적는다. 값을 판정하거나 계산하지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "RESULT_PENDING":
                raise UserError("결과 입력 대기 항목에서 입력해 주세요.")
            name = self._name(entered_by, "입력한 직원")
            ref = report_ref.strip()
            if not ref or len(ref) > REF_MAX:
                raise UserError(f"씨젠 접수번호를 1~{REF_MAX}자로 입력해 주세요.", 422)
            today = self._clock.now().astimezone(KST).date()
            if report_date is None or report_date > today:
                raise UserError("결과지의 결과보고일(회신날짜)을 오늘 이전 날짜로 입력해 주세요.", 422)
            items: list[LabItem] = []
            for item_name, value, flag in rows:
                item_name, value, flag = item_name.strip(), value.strip(), flag.strip()
                if not (item_name or value or flag):
                    continue
                if item_name not in self._policy.item_names:
                    raise UserError("항목을 목록에서 골라 주세요.", 422)
                if not value or len(value) > VALUE_MAX:
                    raise UserError(f"{item_name} 결과값을 1~{VALUE_MAX}자로 입력해 주세요.", 422)
                if flag not in self._policy.result_flags:
                    raise UserError(f"{item_name}의 판정(H/L)을 골라 주세요.", 422)
                if any(existing.name == item_name for existing in items):
                    raise UserError(f"{item_name}을(를) 두 번 입력했습니다.", 422)
                items.append(LabItem(item_name, value, flag))
            # H/L 항목을 하나도 적지 않은 채 저장되는 실수를 막으려고 '없음'을 직접 확인받는다.
            if items and no_flagged:
                raise UserError("H/L 항목을 입력했다면 'H/L 표시 없음'을 해제해 주세요.", 422)
            if not items and not no_flagged:
                raise UserError("H/L 항목을 입력하거나 'H/L 표시 없음'을 체크해 주세요.", 422)
            required_qualitative = self._policy.qualitative_for(case.record.exam_kinds)
            for qualitative_name in self._policy.qualitative_for(self._policy.exam_kinds):
                value = qualitative.get(qualitative_name, "")
                if not value and qualitative_name not in required_qualitative:
                    continue
                if value not in self._policy.qualitative_values:
                    raise UserError(f"{qualitative_name}의 Neg/Pos를 골라 주세요.", 422)
                items.append(LabItem(qualitative_name, value))
            now = self._clock.now()
            record = replace(case.record, report_ref=ref, report_date=report_date, items=tuple(items),
                             result_received=True)
            self._save(case, replace(case, record=record, result_entered_at=now, result_entered_by=name))

    def mark_critical(self, case_id: UUID, item_names: list[str], marked_by: str) -> None:
        """관리자가 확인한 위급치를 표기한다(B15). 시스템은 수치로 위급치를 고르지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CHECK_PENDING" or case.critical:
                raise UserError("결과 입력 후 확인 대기 상태에서 표기해 주세요.")
            name = self._name(marked_by, "확인한 관리자")
            flagged = {item.name for item in case.record.items if item.flag}
            chosen = set(item_names)
            if not chosen or not chosen <= flagged:
                raise UserError("H/L로 입력된 항목 중에서 위급치를 골라 주세요.", 422)
            items = tuple(replace(item, critical=item.name in chosen) for item in case.record.items)
            self._save(case, replace(case, record=replace(case.record, items=items),
                                    critical_marked_at=self._clock.now(), critical_marked_by=name))

    def report_critical(self, case_id: UUID, reported_by: str) -> None:
        """직원이 위급치를 원장에게 보고했음을 기록한다. 원장 지시 내용은 받지 않는다."""
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CRITICAL_PENDING":
                raise UserError("원장 보고 대기 항목에서 기록해 주세요.")
            name = self._name(reported_by, "보고한 직원")
            self._save(case, replace(case, critical_reported_at=self._clock.now(), critical_reported_by=name))

    def check(self, case_id: UUID, checked_by: str, followup_note: str = "") -> None:
        with self._lock:
            case = self._get(case_id)
            if case.stage != "CHECK_PENDING":
                raise UserError("확인 대기 항목에서 기록해 주세요.")
            name = self._name(checked_by, "확인한 직원")
            note = followup_note.strip()
            if len(note) > NOTE_MAX:
                raise UserError(f"비고란은 {NOTE_MAX}자 이내 메모로 적어 주세요.", 422)
            record = replace(case.record, followup_note=note or None)
            self._save(case, replace(case, record=record, checked_at=self._clock.now(), checked_by=name))

    def critical_pending_count(self) -> int:
        """모든 화면 상단 알림용. 건수만 돌려주고 환자 정보는 담지 않는다."""
        with self._lock:
            return sum(case.stage == "CRITICAL_PENDING" for case in self._store.cases())

    def subject_of(self, case_id: UUID) -> str:
        with self._lock:
            return self._get(case_id).record.chart_no

    def reset(self) -> None:
        """메모리 시연만 초기화한다. DB 저장 자료는 초기화하지 않는다."""
        if self.persistent:
            raise UserError("DB 저장 모드에서는 시연 초기화를 사용할 수 없습니다.", 403)
        with self._lock:
            now = self._clock.now()
            cases = {}
            for number, record in enumerate(synthetic_records(), 1):
                case = LabCase(UUID(int=number), record)
                if any(item.critical for item in record.items):
                    # 시연 자료의 위급치는 관리자가 이미 표기한 상태로 둔다.
                    case = replace(case, critical_marked_at=now, critical_marked_by="테스트관리자")
                cases[case.id] = case
            self._store.reset(cases)
