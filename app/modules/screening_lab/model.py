"""혈액 접수와 직원 처리 사실. 임상 판정 규칙은 포함하지 않는다."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .ledger import LabRecord


@dataclass(frozen=True, repr=False)
class LabCase:
    id: UUID
    record: LabRecord
    critical_marked_at: datetime | None = None
    critical_marked_by: str = ""
    critical_reported_at: datetime | None = None
    critical_reported_by: str = ""
    result_entered_at: datetime | None = None
    result_entered_by: str = ""
    checked_at: datetime | None = None
    checked_by: str = ""
    registered_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0

    @property
    def critical(self) -> bool:
        return any(item.critical for item in self.record.items)

    @property
    def abnormal(self) -> bool:
        return any(item.flag for item in self.record.items)

    @property
    def stage(self) -> str:
        if not self.record.received:
            return "RESULT_PENDING"
        if self.critical and self.critical_reported_at is None:
            return "CRITICAL_PENDING"
        return "CHECK_PENDING" if self.checked_at is None else "DONE"

    @property
    def display_name(self) -> str:
        return f"가림 · {self.record.chart_no[-2:]}"
