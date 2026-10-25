"""접속기록. 누가·언제·어디서·어떤 정보주체에 대해·무엇을 했는지 추가만 한다.

각 행은 직전 행의 해시를 이어받는 SHA-256 체인이다. 중간 행 변경·삭제·순서 변경을 검증기로 찾는다.
DB 트리거가 UPDATE·DELETE·TRUNCATE를 거부한다(마이그레이션 0002). 비밀번호·검색어 원문·셀 값은 남기지 않는다.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, text
from sqlalchemy.engine import Engine
import yaml

from app.kernel.clock import Clock, SystemClock
from app.kernel.security_db import access_log_reviews, access_logs


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "security.yaml"
GENESIS = "0" * 64
LOCK_KEY = 7_340_011  # 접속기록 전용 advisory lock 번호
PAGE_SIZE = 100
ACTION_LABELS = {
    "LOGIN": "로그인", "LOGOUT": "로그아웃", "LOGIN_FAIL": "로그인 실패", "DENIED": "권한 거부",
    "LIST": "목록 조회", "VIEW": "상세 조회", "CREATE": "등록", "UPDATE": "변경", "IMPORT": "엑셀 가져오기",
    "EXPORT": "엑셀 출력", "ACCOUNT": "계정 관리", "LOG_VIEW": "접속기록 조회", "LOG_REVIEW": "접속기록 점검",
}
BULK_ACTIONS = ("VIEW", "CREATE", "UPDATE")


@dataclass(frozen=True)
class LogRow:
    sequence_no: int
    at: datetime
    actor_id: UUID | None
    actor_label: str
    client_ip: str
    action: str
    subject_ref: str | None
    target_type: str
    detail_count: int | None
    outcome: str
    prev_hash: str
    hash: str

    @property
    def action_label(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)


def row_hash(row: dict) -> str:
    """UTC·정렬 JSON·명시적 null로 정규화한 내용과 직전 해시로 다음 해시를 만든다."""
    payload = {
        "sequence_no": row["sequence_no"], "at": row["at"].astimezone(timezone.utc).isoformat(), "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
        "actor_label": row["actor_label"], "client_ip": row["client_ip"], "action": row["action"],
        "subject_ref": row["subject_ref"], "target_type": row["target_type"], "detail_count": row["detail_count"],
        "outcome": row["outcome"], "prev_hash": row["prev_hash"],
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class ReviewPolicy:
    bulk_threshold: int
    bulk_window_minutes: int

    @classmethod
    def load(cls, path: Path | None = None) -> ReviewPolicy:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)["access_review"]
        return cls(int(raw["bulk_distinct_patients_threshold"]), int(raw["bulk_window_minutes"]))


class AccessLogger:
    def __init__(self, engine: Engine, clock: Clock | None = None, policy: ReviewPolicy | None = None):
        self._engine = engine
        self._clock = clock or SystemClock()
        self.policy = policy or ReviewPolicy.load()

    def record(self, *, actor_id: UUID | None, actor_label: str, client_ip: str, action: str, target_type: str,
               subjects: list[str] | None = None, detail_count: int | None = None, outcome: str = "OK") -> None:
        """정보주체마다 한 행. 기록에 실패하면 예외가 올라가 화면도 응답하지 않는다."""
        now = self._clock.now()
        refs = list(dict.fromkeys(s for s in (subjects or []) if s)) or [None]
        with self._engine.begin() as connection:
            # 순번·직전 해시 읽기·추가를 직렬화한다.
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
            last = connection.execute(select(access_logs.c.sequence_no, access_logs.c.hash)
                                      .order_by(access_logs.c.sequence_no.desc()).limit(1)).first()
            sequence, prev = (last.sequence_no, last.hash) if last else (0, GENESIS)
            for ref in refs:
                sequence += 1
                row = {"sequence_no": sequence, "at": now, "actor_id": actor_id, "actor_label": actor_label[:40],
                       "client_ip": client_ip[:45], "action": action, "subject_ref": ref, "target_type": target_type,
                       "detail_count": detail_count, "outcome": outcome, "prev_hash": prev}
                row["hash"] = prev = row_hash(row)
                connection.execute(insert(access_logs).values(id=uuid4(), created_at=now, updated_at=now, **row))

    def _rows(self, connection, query) -> list[LogRow]:
        columns = [access_logs.c[name] for name in LogRow.__dataclass_fields__]
        return [LogRow(*row) for row in connection.execute(query.with_only_columns(*columns))]

    def verify(self) -> dict:
        """처음부터 끝까지 다시 계산한다. 끊긴 곳이 있으면 그 순번을 알려준다."""
        prev, expected_seq, count, last = GENESIS, 1, 0, None
        with self._engine.connect() as connection:
            for row in self._rows(connection, select(access_logs).order_by(access_logs.c.sequence_no)):
                data = row.__dict__
                if row.sequence_no != expected_seq or row.prev_hash != prev or row_hash(data) != row.hash:
                    return {"ok": False, "broken_at": row.sequence_no, "count": count, "last": last}
                prev, expected_seq, count, last = row.hash, expected_seq + 1, count + 1, row
        return {"ok": True, "broken_at": None, "count": count, "last": last}

    def search(self, start: datetime, end: datetime, actor: str = "", subject: str = "", action: str = "",
               page: int = 1) -> tuple[list[LogRow], int]:
        conditions = [access_logs.c.at >= start, access_logs.c.at < end]
        if actor:
            conditions.append(access_logs.c.actor_label == actor)
        if subject:
            conditions.append(access_logs.c.subject_ref == subject)
        if action:
            conditions.append(access_logs.c.action == action)
        with self._engine.connect() as connection:
            total = connection.execute(select(func.count()).select_from(access_logs).where(*conditions)).scalar_one()
            rows = self._rows(connection, select(access_logs).where(*conditions)
                              .order_by(access_logs.c.sequence_no.desc())
                              .limit(PAGE_SIZE).offset((max(page, 1) - 1) * PAGE_SIZE))
        return rows, total

    def bulk_alerts(self, start: datetime, end: datetime) -> list[dict]:
        """설정한 시간 창 안에 서로 다른 정보주체를 기준보다 많이 상세 조회·변경한 사람."""
        window = timedelta(minutes=self.policy.bulk_window_minutes)
        with self._engine.connect() as connection:
            rows = self._rows(connection, select(access_logs).where(
                access_logs.c.at >= start, access_logs.c.at < end, access_logs.c.action.in_(BULK_ACTIONS),
                access_logs.c.subject_ref.is_not(None)).order_by(access_logs.c.at))
        by_actor: dict[str, list[LogRow]] = defaultdict(list)
        for row in rows:
            by_actor[row.actor_label].append(row)
        alerts = []
        for label, items in by_actor.items():
            recent: deque[LogRow] = deque()
            peak, peak_at = 0, None
            for row in items:
                recent.append(row)
                while recent and row.at - recent[0].at > window:
                    recent.popleft()
                distinct = len({r.subject_ref for r in recent})
                if distinct > peak:
                    peak, peak_at = distinct, recent[0].at
            if peak > self.policy.bulk_threshold:
                alerts.append({"actor_label": label, "distinct": peak, "from": peak_at})
        return alerts

    def add_review(self, reviewer_id: UUID, start: datetime, end: datetime, note: str) -> None:
        """점검 시점의 마지막 순번·해시를 고정한다. 점검으로 추가되는 기록과 섞이지 않는다."""
        check = self.verify()
        alerts = self.bulk_alerts(start, end)
        now = self._clock.now()
        last = check["last"]
        with self._engine.begin() as connection:
            connection.execute(insert(access_log_reviews).values(
                id=uuid4(), reviewer_id=reviewer_id, reviewed_at=now, period_start=start, period_end=end,
                last_sequence=last.sequence_no if last else 0, last_hash=last.hash if last else GENESIS,
                chain_ok=check["ok"], bulk_alerts=len(alerts), note=note[:200], created_at=now, updated_at=now))

    def reviews(self, limit: int = 5) -> list[dict]:
        with self._engine.connect() as connection:
            rows = connection.execute(select(access_log_reviews).order_by(access_log_reviews.c.reviewed_at.desc())
                                      .limit(limit)).all()
        return [dict(r._mapping) for r in rows]
