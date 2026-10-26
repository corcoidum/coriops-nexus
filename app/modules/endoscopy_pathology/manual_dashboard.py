"""조직검체·CLO·Stool 장부 업무 서비스. 라우트는 이 서비스만 호출한다.

흐름: 접수 → 인계 대기 → 결과 대기 → 원장 지시 대기 → 재검 예정 → 종결.
결과 설명·환자 안내는 EMR에서 관리하므로 기록하지 않는다(A12).
저장소: 시연은 MemoryStore(합성 seed), 실사용은 PostgresStore(Alembic 스키마).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
from threading import RLock
from uuid import UUID, uuid4

import yaml

from app.kernel.calendar import ClinicCalendar
from app.kernel.clock import Clock, SystemClock
from app.kernel.tasks import MemoryTaskStore, RuleBook, TaskEngine, TaskStore
from app.kernel.web import UserError

from .excel_io import (
    PAPER_FORMS, Issue, LedgerAppConfig, LedgerReader, ParsedWorkbook, RowDraft, WorkbookError,
    build_followup_workbook, build_paper_workbook, build_workbook, format_sex_age,
)
from .ledger import save_new_workbook
from .ledger_db import ConcurrentUpdate, LedgerStore, MemoryStore, replace_entry
from .ledger_model import (
    KINDS, KST, PROCEDURE_LABELS, STAGE_ACTIONS, STAGE_LABELS, ExportRecord, Handoff, ImportBatch, LedgerEntry,
)
from .result_notation import NotationError, ResultCodeBook
from .rules import ledger_candidates


CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
STAGE_ORDER = {key: index for index, key in enumerate(STAGE_LABELS)}
REPORT_REF = re.compile(r"^[0-9A-Za-z-]{4,20}$")
CHART_NO = re.compile(r"^[0-9A-Za-z-]{1,20}$")
SEARCH_MAX = 30
PAGE_SIZE = 50
BULK_MAX = 200
PREVIEW_LIST_MAX = 200
# 재검 대상 기간 필터. 'due'는 재검일이 오늘이거나 지난 사람(도래)이다.
DUE_FILTERS = {"": "전체", "due": "재검 도래", "week": "이번 주", "month": "이번 달", "30d": "30일 이내",
               "range": "기간 지정"}
DUE_RANGE_MAX_DAYS = 732
# 종이 대장의 성별/나이 칸 표기(A15): M/65, F/56. 한쪽만 적어도 받는다.
SEX_AGE = re.compile(r"^\s*([MFmf남여])?\s*/?\s*(\d{1,3})?\s*$")



class DashboardError(UserError):
    """장부 업무 오류. 화면 처리는 커널 UserError와 같다."""


@dataclass(frozen=True)
class DashboardPolicy:
    result_delay_business_days: int
    followup_window_days: int
    handoff_defaults: dict[str, str]
    staff_name_max_length: int
    rut_result_delay_business_days: int = 1

    @classmethod
    def load(cls, path: Path | None = None) -> DashboardPolicy:
        with open(path or CONFIG_DIR / "manual_dashboard.yaml", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        return cls(int(raw["result_delay_business_days"]), int(raw["followup_window_days"]),
                   dict(raw["handoff_defaults"]), int(raw["staff_name_max_length"]),
                   int(raw["rut_result_delay_business_days"]))


@dataclass(frozen=True)
class SecurityPolicy:
    """config/security.yaml에서 이 화면이 쓰는 값만 읽는다. 보관기간 값은 바꾸지 않고 표시만 한다."""

    retention_years: int
    retention_status: str
    max_upload_bytes: int
    preview_ttl_minutes: int
    forbidden_path_components: tuple[str, ...]

    @classmethod
    def load(cls, path: Path | None = None) -> SecurityPolicy:
        with open(path or CONFIG_DIR / "security.yaml", encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        return cls(int(raw["retention"]["closed_business_years"]), raw["retention"]["approval_status"],
                   int(raw["import_limits"]["maximum_upload_bytes"]),
                   int(raw["import_limits"]["preview_ttl_minutes"]),
                   tuple(raw["backup"]["forbidden_path_components"]))


@dataclass(frozen=True)
class Alert:
    text: str
    level: str  # normal / warn / danger


@dataclass
class _Preview:
    token: str
    created_at: datetime
    parsed: ParsedWorkbook
    summary: dict
    new_rows: list[RowDraft]


def _years_after(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2월 29일
        return day.replace(year=day.year + years, day=28)


class ManualDashboardService:
    def __init__(self, clock: Clock | None = None, calendar: ClinicCalendar | None = None,
                 policy: DashboardPolicy | None = None, codebook: ResultCodeBook | None = None,
                 store: LedgerStore | None = None, config: LedgerAppConfig | None = None,
                 security: SecurityPolicy | None = None, export_dir: str | Path | None = None,
                 task_store: TaskStore | None = None, rulebook: RuleBook | None = None):
        self._clock = clock or SystemClock()
        self._calendar = calendar or ClinicCalendar.load()
        self._policy = policy or DashboardPolicy.load()
        self._codebook = codebook or ResultCodeBook.load()
        self._config = config or LedgerAppConfig.load()
        self._security = security or SecurityPolicy.load()
        self._reader = LedgerReader(self._config, self._codebook)
        self._export_dir = export_dir if export_dir is not None else os.environ.get(
            self._config.export["directory_env"], "")
        self._handoff_kinds = self._config.handoff_kinds
        self._lock = RLock()
        self._preview: _Preview | None = None
        self._store = store if store is not None else MemoryStore()
        # 규칙·할 일(Stage B). 저장은 커널 실행기가, 후보 계산은 이 모듈의 rules.py가 맡는다.
        self._tasks = TaskEngine(task_store or MemoryTaskStore(), rulebook or RuleBook.load(),
                                 self._task_candidates, self._clock)
        if store is None:
            self.reset()

    @property
    def persistent(self) -> bool:
        return getattr(self._store, "persistent", False)

    @property
    def max_upload_bytes(self) -> int:
        return self._security.max_upload_bytes

    @property
    def tasks(self) -> TaskEngine:
        return self._tasks

    def _task_candidates(self, now: datetime) -> list:
        entries = self._store.entries()
        stages = {e.id: self._stage(e) for e in entries}
        return ledger_candidates(entries, stages, now, self._tasks.book.specs, self._calendar, self._handoff_kinds)

    @property
    def engine(self):
        """DB 저장소의 연결. 로그인·접속기록이 같은 DB를 쓴다."""
        return self._store._engine

    # ---------- 접속기록용 정보주체(차트번호) 조회

    def subject_of(self, entry_id: UUID) -> str:
        return self._get(entry_id).chart_no

    def subjects_of(self, entry_ids: list[UUID]) -> list[str]:
        wanted = set(entry_ids)
        return [e.chart_no for e in self._store.entries() if e.id in wanted]

    def pending_handoff_subjects(self) -> list[str]:
        return [e.chart_no for e in self._store.entries() if self._stage(e) == "HANDOFF_PENDING"]

    def import_subjects(self, token: str) -> list[str]:
        with self._lock:
            return [d.chart_no for d in self._current_preview(token).new_rows]

    # ---------- 공통

    def _today(self) -> date:
        return self._clock.now().astimezone(KST).date()

    def _stage(self, entry: LedgerEntry) -> str:
        return entry.stage_for(self._handoff_kinds)

    def _get(self, entry_id: UUID) -> LedgerEntry:
        for entry in self._store.entries():
            if entry.id == entry_id:
                return entry
        raise DashboardError("장부 항목을 찾을 수 없습니다.", 404)

    def _write(self, **changes) -> None:
        try:
            self._store.write(**changes)
        except ConcurrentUpdate:
            raise DashboardError("다른 화면에서 먼저 바뀌었거나 이미 있는 번호입니다. 새로 고친 뒤 다시 입력해 주세요.", 409) from None
        # 바뀐 검사의 할 일만 바로 열고 닫는다. 출력 기록처럼 검사가 바뀌지 않으면 돌리지 않는다.
        subjects = {e.id for e in (*changes.get("inserted", ()), *changes.get("updated", ()))}
        if subjects:
            self._tasks.run(subjects)

    @staticmethod
    def _text(value: str, label: str, maximum: int, required: bool = True) -> str:
        clean = value.strip()
        if (required and not clean) or len(clean) > maximum:
            raise DashboardError(f"{label}을(를) {'1' if required else '0'}~{maximum}자로 입력해 주세요.", 422)
        return clean

    def _check_kind(self, kind: str) -> str:
        if kind not in KINDS:
            raise DashboardError("검사 종류를 선택해 주세요.", 422)
        return kind

    # ---------- 조회

    def _alert(self, entry: LedgerEntry, stage: str, today: date, pickup: dict) -> Alert:
        if stage == "HANDOFF_PENDING":
            if entry.exam_date < today:
                return Alert("이전 검사일 · 인계 누락", "danger")
            return Alert(pickup["text"], pickup["level"])
        if stage == "RESULT_PENDING":
            days = self._calendar.business_days_between(entry.waiting_since, today)
            limit = (self._policy.rut_result_delay_business_days if entry.kind == "CLO"
                     else self._policy.result_delay_business_days)
            delayed = days > limit
            label = "위탁 후" if entry.entrusted_on else "검사 후"
            return Alert(f"{label} {days}진료일" + (" · 지연" if delayed else ""), "danger" if delayed else "normal")
        if stage == "DOCTOR_PENDING":
            if entry.needs_review:
                return Alert(" · ".join(entry.review_labels), "warn")
            return Alert("과거 장부에서 가져옴" if entry.source == "IMPORT" else "결과 입력됨", "normal")
        if stage == "FOLLOWUP":
            left = (entry.followup_due - today).days
            if left < 0:
                return Alert(f"재검 기한 {-left}일 경과", "danger")
            if left == 0:
                return Alert("재검일 오늘", "danger")
            return Alert(f"재검 D-{left}", "warn" if left <= self._policy.followup_window_days else "normal")
        return Alert("재검 완료" if entry.followup_done_on else "재검 불필요", "normal")

    def _pickup(self, today: date, now: datetime, pending: list[LedgerEntry]) -> dict:
        """오늘 수탁기관 수령 시각과 인계 상태. 시각은 config/clinic.yaml이 원천이다."""
        pickup = self._calendar.pickup_time(today)
        handed_today = [h for h in self._store.handoffs() if h.handed_at.astimezone(KST).date() == today]
        info = {"time": pickup, "pending_cases": len(pending),
                "pending_specimens": sum(e.specimen_count or 1 for e in pending), "handed_today": handed_today}
        if not pending:
            info.update(status="DONE" if handed_today else "NONE", level="normal",
                        text="오늘 인계 완료" if handed_today else "인계할 검체 없음")
        elif pickup is None:
            info.update(status="NO_PICKUP", level="warn", text="오늘 수령 없음 · 보관 확인")
        else:
            minutes = int((datetime.combine(today, pickup, KST) - now.astimezone(KST)).total_seconds() // 60)
            if minutes < 0:
                info.update(status="OVERDUE", level="danger", text=f"수령 {pickup:%H:%M} 지남 · 인계 확인")
            else:
                info.update(status="DUE", level="warn", text=f"수령 {pickup:%H:%M}까지 {minutes // 60}시간 {minutes % 60}분")
        return info

    @staticmethod
    def _matches(entry: LedgerEntry, query: str) -> bool:
        if not query:
            return True
        upper = query.upper()
        return (query in entry.chart_no or (entry.report_ref and query in entry.report_ref)
                or query in entry.patient_name
                or any(f.code.upper() == upper for f in entry.findings) or entry.result_code.upper() == upper)

    def _sort_key(self, entry: LedgerEntry, stage: str, today: date):
        if stage == "RESULT_PENDING":
            within = -self._calendar.business_days_between(entry.waiting_since, today)
        elif stage == "FOLLOWUP":
            within = (entry.followup_due - today).days
        elif stage == "DOCTOR_PENDING":
            within = 0 if entry.needs_review else 1
        elif stage == "CLOSED":
            within = -(entry.closed_on or entry.exam_date).toordinal()
        else:
            within = 0
        return (STAGE_ORDER[stage], within, entry.exam_date, entry.chart_no)

    def _retention(self, entries: list[LedgerEntry], today: date) -> dict:
        years = self._security.retention_years
        expired = [e for e in entries if e.closed_on and _years_after(e.closed_on, years) < today]
        return {"years": years, "status": self._security.retention_status, "expired": len(expired)}

    @staticmethod
    def due_window(due: str, today: date, due_from: date | None = None,
                   due_to: date | None = None) -> tuple[date | None, date | None]:
        """재검일 필터의 시작·끝(둘 다 포함). None은 제한 없음."""
        if due not in DUE_FILTERS:
            raise DashboardError("알 수 없는 재검 기간입니다.", 422)
        if due == "due":
            return None, today
        if due == "week":
            monday = today - timedelta(days=today.weekday())
            return monday, monday + timedelta(days=6)
        if due == "month":
            first = today.replace(day=1)
            following = (first + timedelta(days=32)).replace(day=1)
            return first, following - timedelta(days=1)
        if due == "30d":
            return today, today + timedelta(days=30)
        if due == "range":
            if due_from is None or due_to is None or due_to < due_from:
                raise DashboardError("기간의 시작일과 종료일을 확인해 주세요.", 422)
            if (due_to - due_from).days > DUE_RANGE_MAX_DAYS:
                raise DashboardError("기간은 2년 이내로 지정해 주세요.", 422)
            return due_from, due_to
        return None, None

    def _followups(self, stored: list[LedgerEntry], kind: str, query: str, window) -> list[LedgerEntry]:
        """조건에 맞는 재검 예정 행을 재검일·차트번호 순서로."""
        start, end = window
        rows = [e for e in stored if self._stage(e) == "FOLLOWUP" and (kind == "ALL" or e.kind == kind)
                and (start is None or e.followup_due >= start) and (end is None or e.followup_due <= end)
                and self._matches(e, query)]
        return sorted(rows, key=lambda e: (e.followup_due, e.chart_no))

    def snapshot(self, stage: str = "ALL", selected_id: UUID | None = None, query: str = "",
                 kind: str = "ALL", page: int = 1, due: str = "", due_from: date | None = None,
                 due_to: date | None = None) -> dict:
        with self._lock:
            self._tasks.run_if_stale()
            if due:
                stage = "FOLLOWUP"  # 기간 필터는 재검 대상에만 적용한다
            if stage != "ALL" and stage not in STAGE_LABELS:
                raise DashboardError("알 수 없는 업무 분류입니다.", 422)
            if kind != "ALL" and kind not in KINDS:
                raise DashboardError("알 수 없는 검사 종류입니다.", 422)
            query = query.strip()
            if len(query) > SEARCH_MAX:
                raise DashboardError(f"검색어는 {SEARCH_MAX}자까지 입력할 수 있습니다.", 422)
            now = self._clock.now()
            today = now.astimezone(KST).date()
            stored = self._store.entries()
            stages = {e.id: self._stage(e) for e in stored}
            ordered = sorted(stored, key=lambda e: self._sort_key(e, stages[e.id], today))
            pending = [e for e in ordered if stages[e.id] == "HANDOFF_PENDING"]
            pickup = self._pickup(today, now, pending)
            alerts = {e.id: self._alert(e, stages[e.id], today, pickup) for e in ordered}
            scoped = [e for e in ordered if kind == "ALL" or e.kind == kind]
            counts = {key: sum(stages[e.id] == key for e in scoped) for key in STAGE_LABELS}

            def count(stage_key: str, test) -> int:
                return sum(stages[e.id] == stage_key and test(e) for e in scoped)

            flags = {
                "result_delayed": count("RESULT_PENDING", lambda e: alerts[e.id].level == "danger"),
                "code_review": count("DOCTOR_PENDING", lambda e: e.needs_review),
                "imported_pending": count("DOCTOR_PENDING", lambda e: e.source == "IMPORT"),
                "followup_due": count("FOLLOWUP", lambda e: e.followup_due <= today),
                "followup_overdue": count("FOLLOWUP", lambda e: e.followup_due < today),
                "followup_soon": count("FOLLOWUP", lambda e: alerts[e.id].level == "warn"),
            }
            window = self.due_window(due, today, due_from, due_to)
            if due:
                matched = self._followups(stored, kind, query, window)
            else:
                matched = [e for e in scoped if (stage == "ALL" or stages[e.id] == stage) and self._matches(e, query)]
            pages = max(1, -(-len(matched) // PAGE_SIZE))
            page = min(max(page, 1), pages)
            cases = matched[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
            selected = None
            if selected_id:
                selected = next((e for e in stored if e.id == selected_id), None)
                if selected is None:
                    raise DashboardError("장부 항목을 찾을 수 없습니다.", 404)
            elif cases:
                selected = cases[0]
            return {
                "cases": cases, "matched": len(matched), "page": page, "pages": pages,
                "counts": counts, "flags": flags, "alerts": alerts, "stages": stages,
                "selected": selected, "today": today, "stage": stage, "query": query, "kind": kind,
                "stage_labels": STAGE_LABELS, "stage_actions": STAGE_ACTIONS,
                "kind_labels": {k: self._config.kinds[k]["label"] for k in KINDS},
                "procedure_labels": PROCEDURE_LABELS, "handoff_kinds": self._handoff_kinds,
                "total": len(stored), "pickup": pickup, "handoff_defaults": self._policy.handoff_defaults,
                "sydney_text": self._codebook.format_sydney(dict(selected.sydney)) if selected else "",
                "delay_days": self._policy.result_delay_business_days,
                "window_days": self._policy.followup_window_days,
                "retention": self._retention(stored, today), "persistent": self.persistent,
                "export_ready": bool(self._export_dir), "exports": self._store.exports()[-3:][::-1],
                "due": due, "due_from": due_from, "due_to": due_to, "due_window": window, "due_labels": DUE_FILTERS,
                # 화면 링크가 현재 조건을 이어받는 데 쓴다(템플릿 매크로 기본값은 화면 변수를 못 읽는다).
                "current": {"stage": stage, "kind": kind, "query": query, "due": due,
                            "due_from": due_from.isoformat() if due_from else "",
                            "due_to": due_to.isoformat() if due_to else ""},
            }

    # ---------- 접수·인계·결과·지시

    def _new_entry(self, kind: str, chart_no: str, patient_name: str, exam_date: date | None, sex: str,
                   age: str, procedure_type: str, specimen_count: str, site: str, now: datetime,
                   stored: list[LedgerEntry]) -> LedgerEntry:
        """접수 1건의 입력을 검사해 장부 한 줄을 만든다. 저장은 호출한 쪽이 한 번에 한다."""
        kind = self._check_kind(kind)
        chart_no = chart_no.strip()
        if not CHART_NO.match(chart_no):
            raise DashboardError("차트번호는 영문·숫자 1~20자로 입력해 주세요.", 422)
        name = self._text(patient_name, "성명", 30)
        if exam_date is None or exam_date > self._today():
            raise DashboardError("시행날짜(오늘 이전)를 입력해 주세요.", 422)
        if sex not in ("", "M", "F"):
            raise DashboardError("성별을 선택해 주세요.", 422)
        if age and not (age.isdigit() and int(age) <= 130):
            raise DashboardError("나이는 0~130 숫자로 입력해 주세요.", 422)
        if kind == "CLO":
            procedure_type = "stomach"
        if procedure_type not in ("", *PROCEDURE_LABELS):
            raise DashboardError("검사명(stomach·colon)을 선택해 주세요.", 422)
        if kind == "BIOPSY" and not procedure_type:
            raise DashboardError("조직검사는 검사명(stomach·colon)을 선택해 주세요.", 422)
        if specimen_count and not (specimen_count.isdigit() and 1 <= int(specimen_count) <= 99):
            raise DashboardError("개수(병)는 1~99로 입력해 주세요.", 422)
        if kind == "BIOPSY" and not specimen_count:
            raise DashboardError("조직검사는 개수(병)를 입력해 주세요.", 422)
        if any(e.chart_no == chart_no and e.patient_name != name for e in stored):
            raise DashboardError("같은 차트번호에 다른 이름이 등록돼 있습니다. 차트번호를 확인해 주세요.", 422)
        return LedgerEntry(
            id=uuid4(), kind=kind, chart_no=chart_no, patient_name=name, exam_date=exam_date,
            created_at=now, updated_at=now, sex=sex or None, age=int(age) if age else None,
            procedure_type=procedure_type or None, specimen_count=int(specimen_count) if specimen_count else None,
            site=self._text(site, "부위", 80, required=False),
        )

    def register(self, kind: str, chart_no: str, patient_name: str, exam_date: date | None, sex: str = "",
                 age: str = "", procedure_type: str = "", specimen_count: str = "", site: str = "") -> UUID:
        """새 검사 1건 접수. 같은 차트번호에 다른 이름이면 덮어쓰지 않고 거부한다."""
        with self._lock:
            entry = self._new_entry(kind, chart_no, patient_name, exam_date, sex, age, procedure_type,
                                    specimen_count, site, self._clock.now(), self._store.entries())
            self._write(inserted=[entry])
            return entry.id

    def register_endoscopy(self, chart_no: str, patient_name: str, exam_date: date | None, sex_age: str,
                           procedure_type: str, biopsy: bool, site: str, specimen_count: str,
                           rut: bool) -> list[UUID]:
        """종이 검체 관리 장부(①) 한 줄 = 내시경 1회. 조직검사·RUT(CLO) 건을 함께 만들고 한 번에 저장한다."""
        with self._lock:
            sex, age = parse_sex_age(sex_age)
            if procedure_type not in PROCEDURE_LABELS:
                raise DashboardError("검사명(stomach·colon)을 선택해 주세요.", 422)
            if not biopsy and not rut:
                raise DashboardError("조직검사나 RUT 중 하나 이상을 선택해 주세요. 둘 다 없으면 장부에 올리지 않습니다.", 422)
            if rut and procedure_type != "stomach":
                raise DashboardError("RUT는 stomach 검사에서만 기록합니다.", 422)
            now, stored = self._clock.now(), self._store.entries()
            entries = []
            if biopsy:
                entries.append(self._new_entry("BIOPSY", chart_no, patient_name, exam_date, sex, age,
                                               procedure_type, specimen_count, site, now, stored))
            if rut:
                entries.append(self._new_entry("CLO", chart_no, patient_name, exam_date, sex, age,
                                               procedure_type, "", "", now, stored))
            self._write(inserted=entries)
            return [e.id for e in entries]

    def handoff(self, registered_by: str, handed_by: str, receiver_name: str, confirmed_count: int) -> None:
        """인계 대기 검체 전체를 한 번에 넘긴다. 확인 병 수가 장부와 다르면 기록하지 않는다."""
        with self._lock:
            pending = [e for e in self._store.entries() if self._stage(e) == "HANDOFF_PENDING"]
            if not pending:
                raise DashboardError("인계할 검체가 없습니다.")
            limit = self._policy.staff_name_max_length
            names = (self._text(registered_by, "접수인", limit), self._text(handed_by, "인계인", limit),
                     self._text(receiver_name, "수령인", limit))
            expected = sum(e.specimen_count or 1 for e in pending)
            if confirmed_count != expected:
                raise DashboardError(
                    f"병 수가 맞지 않습니다. 장부 {expected}병 / 확인 {confirmed_count}병. 다시 세어 주세요.", 422)
            now = self._clock.now()
            record = Handoff(uuid4(), now, *names, specimen_count=expected, case_count=len(pending))
            today = now.astimezone(KST).date()
            self._write(handoff=record, updated=[
                replace_entry(e, now, handoff_id=record.id, entrusted_on=today, registered_by=names[0],
                              handed_by=names[1], received_by=names[2]) for e in pending])

    def receive(self, entry_id: UUID, report_ref: str, result_notation: str, site_summary: str,
                sydney_notation: str = "") -> None:
        with self._lock:
            entry = self._get(entry_id)
            if self._stage(entry) != "RESULT_PENDING":
                raise DashboardError("결과 대기 항목에서 입력해 주세요.")
            ref = report_ref.strip()
            if (ref or entry.kind == "BIOPSY") and not REPORT_REF.match(ref):
                raise DashboardError("접수번호는 영문·숫자 4~20자로 입력해 주세요.", 422)
            if ref and any(o.kind == entry.kind and o.report_ref == ref and o.id != entry.id
                           for o in self._store.entries()):
                raise DashboardError("다른 검체에 이미 입력된 접수번호입니다.", 422)
            findings, result_code = (), ""
            try:
                if self._config.kinds[entry.kind]["result_format"] == "codes":
                    findings = self._codebook.parse_findings(result_notation)
                else:
                    result_code = result_notation.strip()
                    if not self._config.short_result_pattern.match(result_code):
                        raise DashboardError("결과는 +, -, 양성, 음성처럼 20자 이내 판정으로 입력해 주세요.", 422)
                sydney = self._codebook.parse_sydney(sydney_notation) if sydney_notation.strip() else {}
            except NotationError as error:
                raise DashboardError(str(error), 422) from None
            if sydney and entry.procedure_type != "stomach":
                raise DashboardError("Sydney 등급은 위 검체에만 입력합니다.", 422)
            site = self._text(site_summary, "부위", 80, required=entry.kind == "BIOPSY")
            now = self._clock.now()
            self._write(updated=[replace_entry(
                entry, now, report_ref=ref, reported_on=now.astimezone(KST).date(), findings=findings,
                result_code=result_code, sydney=tuple(sydney.items()), site=site or entry.site, review_codes=())])

    def _decision(self, entry: LedgerEntry, mode: str, due_date: date | None, reason: str, now: datetime,
                  actor: str | None):
        if self._stage(entry) != "DOCTOR_PENDING":
            raise DashboardError("결과 입력 후 원장 지시를 기록해 주세요.")
        if mode == "required":
            if due_date is None:
                raise DashboardError("원장이 정한 재검 날짜를 입력해 주세요.", 422)
            clean_reason = ""
        elif mode == "not_required":
            clean_reason = self._text(reason, "재검 불필요 사유", 120)
            due_date = None
        else:
            raise DashboardError("재검 여부를 선택해 주세요.", 422)
        # 재검 간격을 추천하거나 계산하지 않고 입력 날짜만 보관한다.
        return replace_entry(entry, now, decided_at=now, decided_by=actor, followup_due=due_date,
                             no_followup_reason=clean_reason)

    def decide(self, entry_id: UUID, mode: str, due_date: date | None = None, reason: str = "",
               actor: str | None = None) -> None:
        """actor는 기록한 계정 이름이다(원장 본인 또는 대리 입력자)."""
        with self._lock:
            self._write(updated=[self._decision(self._get(entry_id), mode, due_date, reason, self._clock.now(),
                                                actor)])

    def bulk_not_required(self, entry_ids: list[UUID], reason: str, actor: str | None = None) -> int:
        """원장이 고른 여러 건에 같은 '재검 불필요' 지시를 한 번에 기록한다. 하나라도 안 되면 전부 취소."""
        with self._lock:
            unique = list(dict.fromkeys(entry_ids))
            if not unique or len(unique) > BULK_MAX:
                raise DashboardError(f"1~{BULK_MAX}건을 선택해 주세요.", 422)
            stored = {e.id: e for e in self._store.entries()}
            if any(i not in stored for i in unique):
                raise DashboardError("장부 항목을 찾을 수 없습니다.", 404)
            now = self._clock.now()
            changes = [self._decision(stored[i], "not_required", None, reason, now, actor) for i in unique]
            self._write(updated=changes)
            return len(changes)

    def complete_followup(self, entry_id: UUID, done_on: date | None, actor: str | None = None) -> None:
        with self._lock:
            entry = self._get(entry_id)
            if self._stage(entry) != "FOLLOWUP":
                raise DashboardError("재검 예정 항목에서 기록해 주세요.")
            if done_on is None or done_on > self._today():
                raise DashboardError("재검을 시행한 날짜(오늘 이전)를 입력해 주세요.", 422)
            self._write(updated=[replace_entry(entry, self._clock.now(), followup_done_on=done_on,
                                               followup_done_by=actor)])

    # ---------- 엑셀 가져오기·대조

    @staticmethod
    def _diff(draft: RowDraft, entry: LedgerEntry) -> list[str]:
        pairs = [
            ("접수번호", draft.report_ref, entry.report_ref),
            ("결과보고일", draft.reported_on, entry.reported_on),
            ("결과", draft.result_notation, entry.result_notation),
            ("검체수량", draft.specimen_count, entry.specimen_count),
            ("특이소견", draft.sydney, dict(entry.sydney)),
            ("검사위치", draft.site, entry.site),
            ("위탁일", draft.entrusted_on, entry.entrusted_on),
        ]
        return [label for label, left, right in pairs if (left or right) and left != right]

    def _classify(self, parsed: ParsedWorkbook, existing: list[LedgerEntry]) -> tuple[dict, list[RowDraft]]:
        by_ref = {(e.kind, e.report_ref): e for e in existing if e.report_ref}
        by_natural: dict[tuple, list[LedgerEntry]] = defaultdict(list)
        for entry in existing:
            by_natural[(entry.kind, entry.chart_no, entry.exam_date)].append(entry)
        names = {e.chart_no: e.patient_name for e in existing}
        sheets, differences, missing, new_rows = [], [], [], []
        issues = list(parsed.issues)
        for sheet in parsed.sheets:
            counts = {"new": 0, "same": 0, "different": 0, "invalid": 0, "missing": 0}
            matched: set[UUID] = set()
            for draft in sheet.rows:
                if draft.chart_no in names and names[draft.chart_no] != draft.patient_name:
                    issues.append(Issue(sheet.sheet, draft.row, "NAME_MISMATCH", "수진자명"))
                    counts["invalid"] += 1
                    continue
                match = by_ref.get((draft.kind, draft.report_ref)) if draft.report_ref else None
                if match is None:
                    match = next((e for e in by_natural[(draft.kind, draft.chart_no, draft.exam_date)]
                                  if e.id not in matched and (not draft.procedure_type or not e.procedure_type
                                                              or e.procedure_type == draft.procedure_type)
                                  and (not e.report_ref or not draft.report_ref)), None)
                if match is None:
                    counts["new"] += 1
                    new_rows.append(draft)
                    continue
                matched.add(match.id)
                fields = self._diff(draft, match)
                if fields:
                    counts["different"] += 1
                    differences.append({"sheet": sheet.sheet, "row": draft.row, "entry": match, "fields": fields})
                else:
                    counts["same"] += 1
            counts["invalid"] += sum(1 for i in parsed.issues if i.sheet == sheet.sheet and i.row and i.code in
                                     ("REQUIRED_MISSING", "INVALID_REQUIRED", "NAME_MISMATCH"))
            if sheet.rows:
                first, last = min(d.exam_date for d in sheet.rows), max(d.exam_date for d in sheet.rows)
                for entry in existing:
                    if entry.kind == sheet.kind and entry.id not in matched and first <= entry.exam_date <= last:
                        counts["missing"] += 1
                        missing.append({"sheet": sheet.sheet, "entry": entry})
            sheets.append({"kind": sheet.kind, "sheet": sheet.sheet, "counts": counts, "skipped": sheet.skipped,
                           "ignored_headers": sheet.ignored_headers, "unknown_headers": sheet.unknown_headers,
                           "review": sum(1 for d in sheet.rows if d.review_codes)})
        summary = {
            "sheets": sheets, "other_sheets": parsed.other_sheets,
            "issues": sorted(issues, key=lambda i: (i.sheet, i.row))[:PREVIEW_LIST_MAX], "issue_total": len(issues),
            "differences": differences[:PREVIEW_LIST_MAX], "difference_total": len(differences),
            "missing": missing[:PREVIEW_LIST_MAX], "missing_total": len(missing), "new_total": len(new_rows),
        }
        return summary, new_rows

    def preview_import(self, data: bytes) -> str:
        """업로드 엑셀을 메모리에서 읽어 DB와 대조한다. 아무것도 저장하지 않는다."""
        with self._lock:
            if not data:
                raise DashboardError("엑셀 파일을 선택해 주세요.", 422)
            if len(data) > self._security.max_upload_bytes:
                raise DashboardError("파일이 너무 큽니다. 5MB 이하로 올려 주세요.", 413)
            try:
                parsed = self._reader.read(data, self._today())
            except WorkbookError as error:
                raise DashboardError(str(error), 422) from None
            summary, new_rows = self._classify(parsed, self._store.entries())
            token = secrets.token_urlsafe(24)
            # 미리보기는 1개만 메모리에 둔다. 새로 올리면 이전 것은 버린다.
            self._preview = _Preview(token, self._clock.now(), parsed, summary, new_rows)
            return token

    def _current_preview(self, token: str) -> _Preview:
        preview = self._preview
        if (preview is None or not secrets.compare_digest(preview.token.encode(), token.encode())
                or self._clock.now() - preview.created_at > timedelta(minutes=self._security.preview_ttl_minutes)):
            raise DashboardError("미리보기가 만료됐습니다. 파일을 다시 올려 주세요.", 410)
        return preview

    def preview(self, token: str) -> dict:
        with self._lock:
            return self._current_preview(token).summary

    def commit_import(self, token: str) -> int:
        """미리보기의 '신규' 행만 저장한다. 차이 행은 덮어쓰지 않는다. 미리보기는 1회만 쓴다."""
        with self._lock:
            preview = self._current_preview(token)
            self._preview = None
            if not preview.new_rows:
                raise DashboardError("새로 저장할 행이 없습니다.", 422)
            digest = sha256(json.dumps(sorted(d.normalized() for d in preview.new_rows), default=str,
                                       ensure_ascii=False).encode()).hexdigest()
            now = self._clock.now()
            batch = ImportBatch(uuid4(), now, digest, accepted=len(preview.new_rows),
                                skipped=preview.summary["issue_total"],
                                sheet_counts={s["sheet"]: s["counts"]["new"] for s in preview.summary["sheets"]})
            rows = [LedgerEntry(
                id=uuid4(), kind=d.kind, chart_no=d.chart_no, patient_name=d.patient_name, exam_date=d.exam_date,
                created_at=now, updated_at=now, source="IMPORT", sex=d.sex, age=d.age,
                procedure_type=d.procedure_type, specimen_count=d.specimen_count, site=d.site,
                report_ref=d.report_ref, registered_by=d.registered_by, handed_by=d.handed_by,
                received_by=d.received_by, entrusted_on=d.entrusted_on, reported_on=d.reported_on,
                findings=tuple(d.findings), sydney=tuple(d.sydney.items()), result_code=d.result_code,
                review_codes=tuple(d.review_codes), import_batch_id=batch.id,
            ) for d in preview.new_rows]
            self._write(inserted=rows, import_batch=batch)
            return len(rows)

    # ---------- 엑셀 출력

    def _export_folder(self) -> Path:
        """지정 원내 폴더만 허용한다. 링크·클라우드 동기화 경로·없는 폴더는 거부한다."""
        if not self._export_dir:
            raise DashboardError("출력 폴더가 지정되지 않았습니다. 관리자에게 원내 저장 폴더 설정을 요청해 주세요.", 409)
        folder = Path(self._export_dir)
        if not folder.is_absolute():
            raise DashboardError("출력 폴더 설정이 올바르지 않습니다.", 409)
        try:
            resolved = folder.resolve(strict=True)
        except OSError:
            raise DashboardError("지정 출력 폴더가 없습니다. 폴더를 확인해 주세요.", 409) from None
        if not resolved.is_dir() or resolved != Path(os.path.abspath(folder)):
            raise DashboardError("지정 출력 폴더가 링크이거나 폴더가 아닙니다.", 409)
        compact = [part.casefold().replace(" ", "") for part in resolved.parts]
        if any(name.casefold().replace(" ", "") in part for part in compact
               for name in self._security.forbidden_path_components):
            raise DashboardError("클라우드 동기화 폴더에는 저장하지 않습니다.", 409)
        return resolved

    def export(self) -> ExportRecord:
        with self._lock:
            folder = self._export_folder()
            stored = self._store.entries()
            if not stored:
                raise DashboardError("출력할 장부가 없습니다.", 422)
            workbook = build_workbook([(e, self._stage(e)) for e in stored], self._config, self._codebook)
            now = self._clock.now()
            name = f"{self._config.export['file_prefix']}_{now.astimezone(KST):%Y%m%d_%H%M%S}.xlsx"
            try:
                save_new_workbook(workbook, folder / name)  # 같은 이름이 있으면 덮어쓰지 않고 실패
            except FileExistsError:
                raise DashboardError("같은 이름의 파일이 있습니다. 잠시 뒤 다시 출력해 주세요.", 409) from None
            record = ExportRecord(uuid4(), now, name, len(stored))
            self._write(export=record)
            return record

    def export_followups(self, kind: str = "ALL", query: str = "", due: str = "", due_from: date | None = None,
                         due_to: date | None = None) -> tuple[ExportRecord, list[str]]:
        """화면의 재검 대상 조건 그대로 대상자 목록만 지정 폴더에 저장한다. (기록, 차트번호들)"""
        with self._lock:
            if kind != "ALL" and kind not in KINDS:
                raise DashboardError("알 수 없는 검사 종류입니다.", 422)
            query = query.strip()[:SEARCH_MAX]
            folder = self._export_folder()
            now = self._clock.now()
            today = now.astimezone(KST).date()
            window = self.due_window(due, today, due_from, due_to)
            rows = self._followups(self._store.entries(), kind, query, window)
            if not rows:
                raise DashboardError("조건에 맞는 재검 대상자가 없습니다.", 422)
            pickup = {"text": "", "level": "normal"}
            labels = {k: self._config.kinds[k]["label"] for k in KINDS}
            start, end = window
            period = "전체 기간" if start is None and end is None else \
                f"{start.isoformat() if start else '처음'} ~ {end.isoformat() if end else '끝'}"
            title = (f"재검 대상자 · {DUE_FILTERS[due]} · {period} · {labels.get(kind, '전체 장부')}"
                     f" · {len(rows)}명 · 출력 {now.astimezone(KST):%Y-%m-%d %H:%M}")
            workbook = build_followup_workbook(
                [(e, self._alert(e, "FOLLOWUP", today, pickup).text) for e in rows], title, labels)
            name = f"재검대상_{now.astimezone(KST):%Y%m%d_%H%M%S}.xlsx"
            try:
                save_new_workbook(workbook, folder / name)
            except FileExistsError:
                raise DashboardError("같은 이름의 파일이 있습니다. 잠시 뒤 다시 출력해 주세요.", 409) from None
            record = ExportRecord(uuid4(), now, name, len(rows))
            self._write(export=record)
            return record, [e.chart_no for e in rows]

    # ---------- 종이 대장 대조 (A15)

    def _paper_window(self, start: date | None, end: date | None) -> tuple[date, date]:
        today = self._today()
        start, end = start or today, end or start or today
        if end < start:
            raise DashboardError("기간의 끝 날짜가 시작 날짜보다 앞입니다.", 422)
        if (end - start).days > DUE_RANGE_MAX_DAYS:
            raise DashboardError("기간은 2년 이내로 지정해 주세요.", 422)
        return start, end

    def paper_rows(self, form: str, start: date | None = None, end: date | None = None) -> dict:
        """종이 대장과 같은 열 순서의 행. ①은 내시경 1회(조직검사+RUT)를 한 줄로 묶는다. 날짜는 시행날짜 기준."""
        if form not in PAPER_FORMS:
            raise DashboardError("알 수 없는 대장입니다.", 422)
        start, end = self._paper_window(start, end)
        entries = sorted((e for e in self._store.entries() if start <= e.exam_date <= end),
                         key=lambda e: (e.exam_date, e.created_at, e.chart_no))
        if form == "specimen":
            grouped: dict[tuple, dict] = {}
            for e in entries:
                if e.kind not in ("BIOPSY", "CLO"):
                    continue
                row = grouped.setdefault((e.exam_date, e.chart_no, e.procedure_type or "stomach"), {
                    "exam_date": e.exam_date, "chart_no": e.chart_no, "name": e.patient_name,
                    "display_name": e.display_name, "procedure": e.procedure_type or "stomach",
                    "biopsy": None, "rut": None})
                row["biopsy" if e.kind == "BIOPSY" else "rut"] = e
            rows = []
            for row in grouped.values():
                b, r = row["biopsy"], row["rut"]
                row["biopsy_text"] = "N" if b is None else " · ".join(
                    part for part in ("Y", b.site, f"{b.specimen_count}병" if b.specimen_count else "") if part)
                row["rut_done"] = "Y" if r else "N"
                row["rut_result"] = (r.result_code or "판정 전") if r else ""
                rows.append(row)
        else:
            rows = []
            for e in entries:
                if e.kind != "BIOPSY":
                    continue
                sydney = self._codebook.format_sydney(dict(e.sydney)) if e.sydney else ""
                rows.append({
                    "exam_date": e.exam_date, "report_ref": e.report_ref, "chart_no": e.chart_no,
                    "name": e.patient_name, "display_name": e.display_name,
                    "sex_age": format_sex_age(e.sex, e.age), "site": e.site, "registered_by": e.registered_by,
                    "entrusted_on": e.entrusted_on, "handed_by": e.handed_by, "received_by": e.received_by,
                    "reported_on": e.reported_on,
                    "result": " ".join(part for part in (e.result_notation, sydney) if part)})
        return {"form": form, "title": PAPER_FORMS[form]["title"], "headers": PAPER_FORMS[form]["headers"],
                "rows": rows, "start": start, "end": end}

    def export_paper(self, form: str, start: date | None = None, end: date | None = None) -> tuple[ExportRecord, list[str]]:
        """종이 대장과 같은 양식으로 지정 폴더에 저장한다. (기록, 차트번호들)"""
        with self._lock:
            folder = self._export_folder()
            data = self.paper_rows(form, start, end)
            if not data["rows"]:
                raise DashboardError("이 기간에 대조할 기록이 없습니다.", 422)
            now = self._clock.now()
            workbook = build_paper_workbook(form, data["rows"], data["start"], data["end"], now.astimezone(KST))
            name = (f"{PAPER_FORMS[form]['file_prefix']}_{data['start']:%Y%m%d}-{data['end']:%Y%m%d}"
                    f"_{now.astimezone(KST):%H%M%S}.xlsx")
            try:
                save_new_workbook(workbook, folder / name)
            except FileExistsError:
                raise DashboardError("같은 이름의 파일이 있습니다. 잠시 뒤 다시 출력해 주세요.", 409) from None
            record = ExportRecord(uuid4(), now, name, len(data["rows"]))
            self._write(export=record)
            return record, [row["chart_no"] for row in data["rows"]]

    # ---------- 시연 초기화

    def reset(self) -> None:
        """메모리 시연에서만 고정 합성 14건으로 되돌린다. DB 저장소에서는 거부한다."""
        with self._lock:
            if self.persistent:
                raise DashboardError("DB 저장 모드에서는 초기화할 수 없습니다.", 403)
            now = self._clock.now()
            today = now.astimezone(KST).date()
            back = self._calendar.subtract_business_days
            book = self._codebook
            plans = [
                # (종류, 검사종류, 병 수, 검사일, 단계별 추가 값)
                ("BIOPSY", "stomach", 1, today, {}),
                ("BIOPSY", "colon", 3, today, {}),
                ("BIOPSY", "stomach", 1, back(today, 1), {"handed": True}),
                ("BIOPSY", "colon", 2, back(today, 2), {"handed": True}),
                ("BIOPSY", "stomach", 2, back(today, 4), {"handed": True}),
                ("BIOPSY", "colon", 2, back(today, 2), {"result": "TA#2(L), H#1"}),
                ("BIOPSY", "stomach", 1, back(today, 3), {"result": "CAG#1(im)", "sydney": "HP-/Neu+/Mon++/Atr+/IM+"}),
                ("BIOPSY", "stomach", 1, back(today, 3), {"result": "TEST#1"}),
                ("BIOPSY", "colon", 3, today - timedelta(days=200), {"result": "TA#3(L)", "due": today + timedelta(days=20)}),
                ("BIOPSY", "stomach", 1, today - timedelta(days=380), {"result": "CAG#1(im)", "due": today - timedelta(days=10)}),
                ("BIOPSY", "colon", 1, today - timedelta(days=30), {"result": "SS#1", "due": today + timedelta(days=300)}),
                ("BIOPSY", "stomach", 1, today - timedelta(days=14), {"result": "CG#1", "reason": "합성 원장 지시"}),
                ("CLO", "stomach", None, today, {}),
                ("STOOL", None, 1, today - timedelta(days=7), {"short": "-", "reason": "합성 원장 지시"}),
            ]
            seed = []
            for number, (kind, procedure, count, day, extra) in enumerate(plans, start=1):
                created = datetime.combine(day, datetime.min.time(), KST)
                entry = LedgerEntry(
                    id=UUID(int=number), kind=kind, chart_no=f"T-{number:04}", patient_name=f"테스트환자{number}",
                    exam_date=day, created_at=created, updated_at=created, source="SEED", sex="F" if number % 2 else "M",
                    age=40 + number, procedure_type=procedure, specimen_count=count,
                )
                if extra:
                    entry = LedgerEntry(**{**entry.__dict__, "entrusted_on": day, "registered_by": "테스트 접수자",
                                           "handed_by": "테스트 인계자", "received_by": "테스트 수령인"})
                if "result" in extra or "short" in extra:
                    entry = LedgerEntry(**{
                        **entry.__dict__, "report_ref": f"T97{number:05}", "reported_on": day + timedelta(days=1),
                        "findings": book.parse_findings(extra["result"]) if "result" in extra else (),
                        "result_code": extra.get("short", ""), "site": "합성 위치" if "result" in extra else "",
                        "sydney": tuple(book.parse_sydney(extra["sydney"]).items()) if "sydney" in extra else (),
                    })
                if "due" in extra or "reason" in extra:
                    # 합성 지시 예시일 뿐 환자별 주기를 산출하지 않는다.
                    entry = LedgerEntry(**{**entry.__dict__, "decided_at": created + timedelta(days=2),
                                           "followup_due": extra.get("due"),
                                           "no_followup_reason": extra.get("reason", "")})
                seed.append(entry)
            self._store.replace_all(seed)
            self._preview = None
            if isinstance(self._tasks.store, MemoryTaskStore):
                self._tasks.store.clear()
            self._tasks.run()


def parse_sex_age(value: str) -> tuple[str, str]:
    """'M/65' → ('M', '65'). 빈 값은 ('', ''). 형식이 다르면 추측하지 않고 거부한다."""
    match = SEX_AGE.match(value or "")
    if not match:
        raise DashboardError("성별/나이는 M/65, F/56처럼 입력해 주세요.", 422)
    sex = {"m": "M", "f": "F", "남": "M", "여": "F"}.get((match.group(1) or "").lower(), "")
    return sex, match.group(2) or ""


def form_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise DashboardError("날짜 형식을 확인해 주세요.", 422) from None

