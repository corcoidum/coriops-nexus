"""진료일·씨젠 수령 시각 계산. config/clinic.yaml이 원천이다."""

from datetime import date, time

import pytest

from app.kernel.calendar import ClinicCalendar


@pytest.fixture(scope="module")
def calendar():
    return ClinicCalendar.load()


@pytest.mark.parametrize(("day", "expected"), [
    (date(2026, 11, 5), True),    # 목요일
    (date(2026, 11, 7), True),    # 토요일 반일
    (date(2026, 11, 8), False),   # 일요일
    (date(2026, 10, 5), False),   # 개천절 대체공휴일
    (date(2026, 10, 9), False),   # 한글날
    (date(2026, 11, 25), False),  # 합성 임시 휴진일
])
def test_clinic_days_exclude_sunday_holidays_and_closures(calendar, day, expected):
    assert calendar.is_clinic_day(day) is expected


@pytest.mark.parametrize(("day", "expected"), [
    (date(2026, 11, 2), time(15, 0)),   # 월
    (date(2026, 11, 4), time(11, 0)),   # 수
    (date(2026, 11, 7), time(11, 0)),   # 토
    (date(2026, 11, 8), None),          # 일
    (date(2026, 10, 9), None),          # 공휴일
])
def test_pickup_times_follow_the_confirmed_schedule(calendar, day, expected):
    assert calendar.pickup_time(day) == expected


def test_business_days_skip_the_anchor_day_and_closed_days(calendar):
    # 10/08(목) 위탁 → 10/09 한글날, 10/10(토) 진료 → 1진료일
    assert calendar.business_days_between(date(2026, 10, 8), date(2026, 10, 10)) == 1
    # 10/02(금) → 10/03 토 공휴일, 10/04 일, 10/05 대체공휴일, 10/06·10/07 → 2진료일
    assert calendar.business_days_between(date(2026, 10, 2), date(2026, 10, 7)) == 2
    assert calendar.business_days_between(date(2026, 11, 5), date(2026, 11, 5)) == 0


def test_subtract_business_days_is_the_inverse_on_clinic_days(calendar):
    end = date(2026, 11, 5)
    for days in range(1, 8):
        start = calendar.subtract_business_days(end, days)
        assert calendar.is_clinic_day(start)
        assert calendar.business_days_between(start, end) == days
