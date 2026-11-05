"""환자정보를 복제하지 않고 담당별 할 일 조회·처리를 제공한다."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app.kernel.auth import Actor, ROLE_LABELS
from app.kernel.tasks import Task, TaskClosed, TaskEngine
from app.kernel.web import UserError


KST = ZoneInfo("Asia/Seoul")
BUCKETS = {"overdue": "기한 지남", "today": "오늘", "pending": "이후 대기", "done": "처리됨"}
STATUS_LABELS = {"OPEN": "대기", "DONE": "확인 완료", "DISMISSED": "해당 없음", "AUTO_RESOLVED": "자동 해소"}


class TaskDashboardService:
    def __init__(self, engine: TaskEngine, source: Callable[[Task], str | None], transaction: Callable):
        self.engine, self.source, self.transaction = engine, source, transaction

    @staticmethod
    def validate(bucket: str, scope: str) -> None:
        if bucket not in {"open", *BUCKETS} or scope not in {"mine", "all"}:
            raise UserError("할 일 조회 조건을 확인해 주세요.", 422)

    def _get(self, task_id: UUID) -> Task:
        found = next((t for t in self.engine.store.tasks() if t.id == task_id), None)
        if found is None:
            raise UserError("할 일을 찾을 수 없습니다.", 404)
        return found

    def snapshot(self, actor: Actor, bucket: str = "open", scope: str = "mine") -> dict:
        self.validate(bucket, scope)
        self.engine.run_if_stale()
        now = self.engine.now()
        today = now.astimezone(KST).date()
        groups = {key: [] for key in BUCKETS}
        for task in self.engine.store.tasks():
            if scope == "mine" and task.assignee_role not in actor.roles:
                continue
            if task.status != "OPEN":
                if task.resolved_at and task.resolved_at >= now - timedelta(days=self.engine.book.done_window_days):
                    groups["done"].append(task)
            elif task.overdue(now):
                groups["overdue"].append(task)
            elif task.due_at.astimezone(KST).date() == today:
                groups["today"].append(task)
            else:
                groups["pending"].append(task)
        selected = groups[bucket] if bucket != "open" else sum((groups[k] for k in ("overdue", "today", "pending")), [])
        selected.sort(key=lambda t: (t.due_at, str(t.id)))
        rows = [{"task": t, "source": self.source(t), "can_close": t.status == "OPEN" and t.assignee_role in actor.roles}
                for t in selected]
        return {"rows": rows, "counts": {k: len(v) for k, v in groups.items()}, "bucket": bucket,
                "scope": scope, "buckets": BUCKETS, "status_labels": STATUS_LABELS,
                "role_labels": ROLE_LABELS, "kst": KST, "today": today,
                "done_days": self.engine.book.done_window_days}

    def assert_can_close(self, actor: Actor, task_id: UUID) -> None:
        if self._get(task_id).assignee_role not in actor.roles:
            raise UserError("담당 역할의 할 일만 처리할 수 있습니다.", 403)

    def close(self, actor: Actor, task_id: UUID, status: str, note: str) -> None:
        self.assert_can_close(actor, task_id)
        try:
            self.engine.close(task_id, status, actor.label, note)
        except TaskClosed:
            raise UserError("이미 처리된 할 일입니다. 목록을 새로 확인해 주세요.", 409) from None
        except ValueError:
            raise UserError("처리 상태와 사유(해당 없음은 1~120자)를 확인해 주세요.", 422) from None
