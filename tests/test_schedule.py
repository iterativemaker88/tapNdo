"""Schedule maths: pure Python, no Home Assistant."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from custom_components.tapndo import schedule as sch

TZ = ZoneInfo("Europe/Berlin")


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_daily_next_same_day_or_tomorrow():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0))
    assert sch.next_fixed(cfg, at(2026, 11, 9, 8), TZ) == at(2026, 11, 9, 11)
    assert sch.next_fixed(cfg, at(2026, 11, 9, 11), TZ) == at(2026, 11, 10, 11)  # strictly after
    assert sch.next_fixed(cfg, at(2026, 11, 9, 12), TZ) == at(2026, 11, 10, 11)


def test_weekly_days():
    # 2026-11-09 is a Monday
    cfg = sch.ScheduleConfig(freq=sch.FREQ_WEEKLY, at=time(10, 0), weekdays=(6,))  # Sunday
    assert sch.next_fixed(cfg, at(2026, 11, 9, 12), TZ) == at(2026, 11, 15, 10)
    cfg2 = sch.ScheduleConfig(freq=sch.FREQ_WEEKLY, at=time(10, 0), weekdays=(0, 3))  # Mon, Thu
    assert sch.next_fixed(cfg2, at(2026, 11, 9, 12), TZ) == at(2026, 11, 12, 10)
    assert sch.next_fixed(cfg2, at(2026, 11, 12, 10), TZ) == at(2026, 11, 16, 10)


def test_every_n_days_uses_anchor():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_EVERY_N_DAYS, interval=3, at=time(8, 0), anchor=date(2026, 11, 1))
    assert sch.next_fixed(cfg, at(2026, 11, 1, 9), TZ) == at(2026, 11, 4, 8)
    assert sch.next_fixed(cfg, at(2026, 11, 5, 9), TZ) == at(2026, 11, 7, 8)


def test_monthly_clips_to_month_length():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_MONTHLY, month_day=31, at=time(9, 0))
    assert sch.next_fixed(cfg, at(2026, 1, 31, 10), TZ) == at(2026, 2, 28, 9)
    assert sch.next_fixed(cfg, at(2026, 2, 28, 10), TZ) == at(2026, 3, 31, 9)
    assert sch.next_fixed(cfg, at(2028, 1, 31, 10), TZ) == at(2028, 2, 29, 9)  # leap year


def test_daily_keeps_wall_clock_across_dst():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0))
    # Berlin switches to winter time on 2026-10-25
    before = sch.next_fixed(cfg, at(2026, 10, 24, 8), TZ)
    after = sch.next_fixed(cfg, before, TZ)
    assert before.astimezone(TZ).utcoffset() != after.astimezone(TZ).utcoffset()
    assert before.astimezone(TZ).hour == 11 and after.astimezone(TZ).hour == 11
    assert after.astimezone(timezone.utc) - before.astimezone(timezone.utc) == timedelta(hours=25)


def test_time_in_dst_gap_resolves_to_real_instant():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(2, 30))
    # 2026-03-29, 02:30 does not exist in Berlin
    result = sch.next_fixed(cfg, at(2026, 3, 28, 12), TZ)
    assert result.astimezone(TZ).date() == date(2026, 3, 29)
    assert result.astimezone(TZ).utcoffset() == timedelta(hours=2)


def test_after_done():
    cfg = sch.ScheduleConfig(kind=sch.KIND_AFTER_DONE, interval=1, unit=sch.UNIT_WEEKS, at=time(10, 0))
    assert sch.next_after_done(cfg, at(2026, 11, 9, 15), TZ) == at(2026, 11, 16, 10)
    cfg2 = sch.ScheduleConfig(kind=sch.KIND_AFTER_DONE, interval=3, unit=sch.UNIT_DAYS, at=time(10, 0))
    assert sch.next_after_done(cfg2, at(2026, 11, 9, 23), TZ) == at(2026, 11, 12, 10)


def test_first_due_after_done_is_next_time_of_day():
    cfg = sch.ScheduleConfig(kind=sch.KIND_AFTER_DONE, interval=7, at=time(10, 0))
    assert sch.first_due(cfg, at(2026, 11, 9, 8), TZ) == at(2026, 11, 9, 10)
    assert sch.first_due(cfg, at(2026, 11, 9, 12), TZ) == at(2026, 11, 10, 10)


def test_window_end():
    daily = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0), window_hours=0)
    assert sch.window_end(daily, at(2026, 11, 9, 11), TZ) == at(2026, 11, 10, 0)
    hours = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0), window_hours=3)
    assert sch.window_end(hours, at(2026, 11, 9, 11), TZ) == at(2026, 11, 9, 14)
    huge = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0), window_hours=100)
    assert sch.window_end(huge, at(2026, 11, 9, 11), TZ) == at(2026, 11, 10, 11)  # never past the next occurrence


def test_early_lead_is_quarter_of_gap():
    daily = sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0))
    assert sch.early_lead(daily, at(2026, 11, 9, 11), TZ) == timedelta(hours=6)
    weekly = sch.ScheduleConfig(freq=sch.FREQ_WEEKLY, at=time(10, 0), weekdays=(6,))
    assert sch.early_lead(weekly, at(2026, 11, 15, 10), TZ) == timedelta(days=7) / 4


def test_occurrences_between():
    cfg = sch.ScheduleConfig(freq=sch.FREQ_WEEKLY, at=time(10, 0), weekdays=(0, 3))
    occ = sch.occurrences_between(cfg, at(2026, 11, 9), at(2026, 11, 23), TZ)
    assert occ == [at(2026, 11, 9, 10), at(2026, 11, 12, 10), at(2026, 11, 16, 10), at(2026, 11, 19, 10)]
    after = sch.ScheduleConfig(kind=sch.KIND_AFTER_DONE)
    assert sch.occurrences_between(after, at(2026, 11, 9), at(2026, 11, 23), TZ) == []


def test_quiet_hours_wrap_midnight():
    start, end = time(22, 0), time(7, 0)
    assert sch.in_quiet(at(2026, 11, 9, 23), start, end, TZ)
    assert sch.in_quiet(at(2026, 11, 9, 6, 59), start, end, TZ)
    assert not sch.in_quiet(at(2026, 11, 9, 7), start, end, TZ)
    assert not sch.in_quiet(at(2026, 11, 9, 12), start, end, TZ)
    assert sch.quiet_end(at(2026, 11, 9, 23), start, end, TZ) == at(2026, 11, 10, 7)
    assert sch.quiet_end(at(2026, 11, 9, 3), start, end, TZ) == at(2026, 11, 9, 7)
    assert not sch.in_quiet(at(2026, 11, 9, 3), None, None, TZ)
