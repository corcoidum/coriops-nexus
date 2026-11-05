"""로컬 PDF를 대조해 세션에 묶인 미리보기로 보관한다. 직원 확정 전에는 업무 자료를 바꾸지 않는다."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import BoundedSemaphore, RLock
from uuid import UUID

import yaml

from app.kernel.auth import Actor
from app.kernel.web import UserError

from .dashboard import LabDashboardService
from .ledger import load_policy
from .model import LabCase


CONFIG = Path(__file__).resolve().parents[3] / "config/lab_pdf.yaml"


@dataclass(frozen=True, repr=False)
class ParsedResult:
    identity: dict[str, str]
    rows: tuple[tuple[str, str, str], ...]
    qualitative: dict[str, str]
    report_date: date | None
    issues: tuple[str, ...]
    unflagged_count: int


def parse_text(content: str) -> ParsedResult:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    policy = load_policy()
    headers = {alias: key for key, aliases in config["headers"].items() for alias in aliases}
    names = {name.casefold(): name for name in (*policy.item_names, *policy.qualitative_names)}
    names.update({code.casefold(): name for code, name in config["insurance_codes"].items()})
    identity: dict[str, str] = {}
    rows, qualitative, issues, seen = [], {}, [], set()
    unflagged_count = 0
    for raw in content.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        key, delimiter, value = line.partition(":")
        if delimiter and key.strip() in headers:
            field = headers[key.strip()]
            value = value.strip()
            if field in identity and identity[field] != value:
                issues.append("서로 다른 식별정보가 함께 있습니다.")
            identity[field] = value
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*)\s*:?\s+(.+)", line)
        if not match:
            if re.search(r"\s[HL]$", line):
                issues.append("배치를 해석할 수 없는 H/L 항목이 있습니다.")
            continue
        key, body = match.groups()
        name = names.get(key.casefold())
        if not name:
            if re.match(r"(?:[<>≤≥]?[+-]?[0-9.]|Neg\b|Pos\b)", body) or re.search(r"\s[HL]$", line) or re.fullmatch(r"D\d+", key):
                issues.append("미등록 또는 해석 불가 항목이 있습니다.")
            continue
        if name in seen:
            issues.append("같은 검사 항목이 중복되어 있습니다.")
            continue
        seen.add(name)
        if name in policy.qualitative_names:
            result = next((v for v in policy.qualitative_values if v.lower() == body.lower()), None)
            if result is None:
                issues.append("정성 결과의 표기를 확인해 주세요.")
            else:
                qualitative[name] = result
            continue
        # 항목·값·선택 단위·선택 H/L이 한 줄인 배치만 받는다. 범위나 다중 열은 추측하지 않는다.
        value = re.fullmatch(r"([<>≤≥]?[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
                             r"(?:\s+(?![HL]$)[A-Za-z%µμ/\^*0-9.]+)?(?:\s+([HL]))?", body)
        if value is None:
            issues.append("항목의 값·단위·판정 배치를 확인해 주세요.")
        elif value[2]:
            rows.append((name, value[1], value[2]))
        else:
            unflagged_count += 1
    for field in config["headers"]:
        if not identity.get(field):
            issues.append("필수 식별정보 또는 날짜를 찾지 못했습니다.")
    report_date = None
    try:
        if identity.get("report_date"):
            report_date = date.fromisoformat(identity["report_date"].replace(".", "-"))
        if identity.get("received_date"):
            date.fromisoformat(identity["received_date"].replace(".", "-"))
    except ValueError:
        issues.append("날짜 표기를 확인해 주세요.")
    if not seen:
        issues.append("읽을 수 있는 검사 항목이 없습니다.")
    return ParsedResult(identity, tuple(rows), qualitative, report_date, tuple(dict.fromkeys(issues)), unflagged_count)


def extract_pdf(data: bytes, limits: dict) -> str:
    if len(data) > limits["maximum_upload_bytes"]:
        raise UserError("PDF 허용 크기를 초과했습니다.", 413)
    if not data.startswith(b"%PDF-"):
        raise UserError("PDF 파일 형식을 확인해 주세요.", 422)
    try:
        result = subprocess.run([sys.executable, "-m", "app.modules.screening_lab.pdf_worker"], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=limits["timeout_seconds"], check=False)
        if result.returncode != 0:
            raise ValueError()
        return json.loads(result.stdout)["text"]
    except (subprocess.TimeoutExpired, ValueError, KeyError, OSError):
        raise UserError("PDF를 안전하게 읽지 못했습니다. 암호·스캔·페이지 수·배치를 확인하거나 직접 입력해 주세요.", 422) from None


@dataclass(frozen=True, repr=False)
class Preview:
    case_id: UUID
    version: int
    owner: str
    expires_at: datetime
    parsed: ParsedResult
    issues: tuple[str, ...]


class PdfAssist:
    def __init__(self, lab: LabDashboardService):
        self.lab = lab
        self.limits = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["limits"]
        self._previews: dict[str, Preview] = {}
        self._lock = RLock()
        self._extract_slot = BoundedSemaphore(self.limits["maximum_parallel_extractions"])

    @staticmethod
    def _owner(actor: Actor) -> str:
        return sha256(f"{actor.staff_id}:{actor.csrf_token}".encode()).hexdigest()

    def _issues(self, case: LabCase, parsed: ParsedResult) -> tuple[str, ...]:
        issues = list(parsed.issues)
        identity = parsed.identity
        record = case.record
        if identity.get("chart_no") != record.chart_no or identity.get("patient_name") != record.patient_name:
            issues.append("선택한 환자와 PDF 식별정보가 일치하지 않습니다.")
        if identity.get("received_date", "").replace(".", "-") != record.received_date.isoformat():
            issues.append("접수일이 일치하지 않습니다.")
        if case.stage != "RESULT_PENDING":
            issues.append("이미 결과가 입력된 접수입니다.")
        if record.report_ref and identity.get("report_ref") != record.report_ref:
            issues.append("접수번호가 일치하지 않습니다.")
        if not set(self.lab.required_qualitative(record.exam_kinds)) <= set(parsed.qualitative):
            issues.append("접수 분류에 해당하는 간염 결과가 빠져 있습니다.")
        return tuple(dict.fromkeys(issues))

    def create(self, actor: Actor, case_id: UUID, data: bytes) -> str:
        case = self.lab.case(case_id)
        if not self._extract_slot.acquire(blocking=False):
            raise UserError("다른 PDF를 처리 중입니다. 잠시 후 다시 시도해 주세요.", 429)
        try:
            parsed = parse_text(extract_pdf(data, self.limits))
        finally:
            self._extract_slot.release()
        issues = self._issues(case, parsed)
        now = self.lab.now()
        with self._lock:
            self._previews = {key: preview for key, preview in self._previews.items() if preview.expires_at > now}
            if len(self._previews) >= self.limits["maximum_previews"]:
                raise UserError("미리보기가 많습니다. 이전 확인을 마치고 다시 시도해 주세요.", 429)
            token = secrets.token_urlsafe(32)
            self._previews[token] = Preview(case_id, case.version, self._owner(actor),
                now + timedelta(minutes=self.limits["preview_minutes"]), parsed, issues)
            return token

    def get(self, token: str, actor: Actor) -> Preview:
        with self._lock:
            preview = self._previews.get(token)
            if preview is None or preview.owner != self._owner(actor):
                raise UserError("이 세션의 미리보기를 찾을 수 없습니다. 다시 올려 주세요.", 404)
            if preview.expires_at <= self.lab.now():
                self._previews.pop(token)
                raise UserError("미리보기 시간이 지났습니다. 다시 올려 주세요.", 410)
            return preview

    @contextmanager
    def confirmed(self, token: str, actor: Actor, confirmed: bool, no_flagged: bool):
        with self._lock:
            preview = self.get(token, actor)
            case = self.lab.case(preview.case_id)
            if preview.issues or self._issues(case, preview.parsed):
                raise UserError("대조 오류를 직접 확인한 후 결과를 수기 입력해 주세요.", 422)
            if case.version != preview.version:
                raise UserError("미리보기 이후 접수가 바뀌었습니다. 다시 올려 주세요.", 409)
            if not confirmed or (not preview.parsed.rows and not no_flagged):
                raise UserError("원본 대조와 H/L 표시 없음 여부를 확인해 주세요.", 422)
            yield preview
            self._previews.pop(token)
