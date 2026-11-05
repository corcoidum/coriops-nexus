"""업무별 원본의 사람이 정한 일정을 공통 조회한다. 일정·임상 주기를 계산하거나 복제하지 않는다."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml

from app.kernel.clock import Clock
from app.kernel.web import UserError


@dataclass(frozen=True)
class RecallItem:
    kind: str
    source_id: UUID
    due_on: date
    done_on: date | None
    done_by: str | None
    source_url: str


class RecallRegistry:
    buckets = {"due": "도래·경과", "upcoming": "이후 예정", "done": "완료", "open": "미완료 전체", "all": "전체"}

    def __init__(self, clock: Clock):
        self._clock = clock
        self._labels = yaml.safe_load((Path(__file__).resolve().parents[2] / "config/recall.yaml").read_text(encoding="utf-8"))["kinds"]
        self._readers: dict[str, Callable[[], list[RecallItem]]] = {}

    def register(self, kind: str, reader: Callable[[], list[RecallItem]]) -> None:
        if kind not in self._labels or kind in self._readers:
            raise ValueError("RECALL_KIND_NOT_APPROVED_OR_DUPLICATE")
        self._readers[kind] = reader

    def snapshot(self, kind: str = "ALL", bucket: str = "due", start: date | None = None,
                 end: date | None = None) -> dict:
        if (kind != "ALL" and kind not in self._readers) or bucket not in self.buckets:
            raise UserError("재검 조회 조건을 확인해 주세요.", 422)
        if start and end and start > end:
            raise UserError("종료일은 시작일 이후로 선택해 주세요.", 422)
        today = self._clock.now().astimezone(ZoneInfo("Asia/Seoul")).date()
        items = []
        for key, reader in self._readers.items():
            if kind != "ALL" and key != kind:
                continue
            for item in reader():
                if item.kind != key or not item.source_url.startswith("/") or item.source_url.startswith("//"):
                    raise ValueError("INVALID_RECALL_PROVIDER")
                if (not start or item.due_on >= start) and (not end or item.due_on <= end):
                    items.append(item)
        groups = {"due": [], "upcoming": [], "done": []}
        for item in items:
            groups["done" if item.done_on else "due" if item.due_on <= today else "upcoming"].append(item)
        groups["open"] = groups["due"] + groups["upcoming"]
        groups["all"] = items
        return {"rows": sorted(groups[bucket], key=lambda r: (r.due_on, str(r.source_id))), "today": today,
                "kind": kind, "bucket": bucket, "buckets": self.buckets, "start": start, "end": end,
                "kinds": {k: self._labels[k] for k in self._readers}, "counts": {k: len(v) for k, v in groups.items()}}
