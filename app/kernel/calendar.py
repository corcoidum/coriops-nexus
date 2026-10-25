"""진료일 계산. 휴진 요일·KR 공휴일·임시 휴진일을 제외하며 모듈을 알지 못한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

import holidays
import yaml


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "clinic.yaml"


def _times(raw: dict) -> dict[int, time | None]:
    return {
        index: time.fromisoformat(raw[name]) if raw.get(name) else None
        for index, name in enumerate(WEEKDAYS)
    }


@dataclass(frozen=True)
class ClinicCalendar:
    closing_times: dict[int, time | None]
    pickup_times: dict[int, time | None]
    temporary_closures: frozenset[date]
    country: str = "KR"

    @classmethod
    def load(cls, path: Path | None = None) -> ClinicCalendar:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)
        return cls(
            closing_times=_times(raw["closing_times"]),
            pickup_times=_times(raw.get("lab_pickup_times", {})),
            temporary_closures=frozenset(date.fromisoformat(str(d)) for d in raw.get("temporary_closures", [])),
            country=raw.get("country", "KR"),
        )

    def is_clinic_day(self, day: date) -> bool:
        # 공휴일 데이터는 패키지에 포함된 값만 사용하고 실행 중 내려받지 않는다.
        return (
            self.closing_times[day.weekday()] is not None
            and day not in holidays.country_holidays(self.country, years=day.year)
            and day not in self.temporary_closures
        )

    def pickup_time(self, day: date) -> time | None:
        """그날 수탁기관 수령 시각. 휴진일이면 None."""
        return self.pickup_times[day.weekday()] if self.is_clinic_day(day) else None

    def business_days_between(self, start: date, end: date) -> int:
        """start 다음날부터 end까지 진료일 수. 기준일(start)은 세지 않는다."""
        count, day = 0, start
        while day < end:
            day += timedelta(days=1)
            count += self.is_clinic_day(day)
        return count

    def subtract_business_days(self, end: date, days: int) -> date:
        """end에서 진료일 days개를 거슬러 간 진료일. 시연 seed에서 사용한다."""
        day, remaining = end, days
        while remaining:
            day -= timedelta(days=1)
            remaining -= self.is_clinic_day(day)
        return day
