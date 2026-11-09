"""Schedule maths for tapNdo. Pure Python: no Home Assistant imports, so it can be unit tested alone.

All datetimes are timezone aware. Occurrences are built from the local wall clock, so a reminder at 11:00
stays at 11:00 across daylight saving changes.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo

KIND_FIXED = "fixed"
KIND_AFTER_DONE = "after_done"

FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_EVERY_N_DAYS = "every_n_days"
FREQ_MONTHLY = "monthly"

UNIT_DAYS = "days"
UNIT_WEEKS = "weeks"

# Longest gap between two occurrences we will scan for (a monthly reminder on the 31st is at most ~62 days apart).
_SCAN_DAYS = 800


@dataclass
class ScheduleConfig:
    """The part of a reminder that decides when it is due."""

    kind: str = KIND_FIXED
    freq: str = FREQ_DAILY
    at: time = field(default_factory=lambda: time(9, 0))
    weekdays: tuple[int, ...] = ()  # 0 = Monday ... 6 = Sunday, for weekly
    interval: int = 1  # every_n_days: N; after_done: how many units
    unit: str = UNIT_DAYS  # after_done only
    month_day: int = 1  # monthly; clipped to the month length
    anchor: date | None = None  # every_n_days counts from this date
    window_hours: int = 0  # 0 = until the end of the day


def local_dt(d: date, t: time, tz: tzinfo) -> datetime:
    """A wall-clock moment on date d as a UTC instant. Gaps in daylight saving time resolve to a real instant.

    Everything is kept in UTC: Python compares and subtracts two datetimes that share one tzinfo by their wall
    clock, which is wrong around a daylight saving change."""
    naive = datetime.combine(d, t.replace(tzinfo=None))
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def _occurs_on(cfg: ScheduleConfig, d: date) -> bool:
    if cfg.freq == FREQ_DAILY:
        return True
    if cfg.freq == FREQ_WEEKLY:
        days = cfg.weekdays or (0,)
        return d.weekday() in days
    if cfg.freq == FREQ_EVERY_N_DAYS:
        n = max(1, cfg.interval)
        anchor = cfg.anchor or date(2000, 1, 3)
        return (d - anchor).days % n == 0
    if cfg.freq == FREQ_MONTHLY:
        last = calendar.monthrange(d.year, d.month)[1]
        return d.day == min(max(1, cfg.month_day), last)
    raise ValueError(f"unknown frequency {cfg.freq}")


def next_fixed(cfg: ScheduleConfig, after: datetime, tz: tzinfo) -> datetime:
    """The first fixed occurrence strictly after `after`."""
    start = after.astimezone(tz).date()
    for offset in range(_SCAN_DAYS):
        d = start + timedelta(days=offset)
        if not _occurs_on(cfg, d):
            continue
        candidate = local_dt(d, cfg.at, tz)
        if candidate > after:
            return candidate
    raise ValueError("schedule never occurs")


def next_after_done(cfg: ScheduleConfig, done_at: datetime, tz: tzinfo) -> datetime:
    """After-last-done: the configured time of day, `interval` units after the day the reminder was done."""
    days = max(1, cfg.interval) * (7 if cfg.unit == UNIT_WEEKS else 1)
    d = done_at.astimezone(tz).date() + timedelta(days=days)
    return local_dt(d, cfg.at, tz)


def next_time_of_day(at: time, after: datetime, tz: tzinfo) -> datetime:
    """The next moment the wall clock shows `at`, strictly after `after`."""
    start = after.astimezone(tz).date()
    for offset in range(3):
        candidate = local_dt(start + timedelta(days=offset), at, tz)
        if candidate > after:
            return candidate
    raise ValueError("unreachable")


def first_due(cfg: ScheduleConfig, created: datetime, tz: tzinfo) -> datetime:
    """The first due time of a reminder that starts existing at `created`."""
    if cfg.kind == KIND_AFTER_DONE:
        return next_time_of_day(cfg.at, created, tz)
    return next_fixed(cfg, created, tz)


def following(cfg: ScheduleConfig, due: datetime, tz: tzinfo) -> datetime:
    """The occurrence after `due` when nothing else is known (used for gaps and windows)."""
    if cfg.kind == KIND_AFTER_DONE:
        return next_after_done(cfg, due, tz)
    return next_fixed(cfg, due, tz)


def window_end(cfg: ScheduleConfig, due: datetime, tz: tzinfo) -> datetime:
    """When a Due reminder becomes Missed. Never later than the next occurrence."""
    nxt = following(cfg, due, tz)
    if cfg.window_hours > 0:
        end = due + timedelta(hours=cfg.window_hours)
    else:
        end = local_dt(due.astimezone(tz).date() + timedelta(days=1), time(0, 0), tz)
    return min(end, nxt)


def early_lead(cfg: ScheduleConfig, due: datetime, tz: tzinfo) -> timedelta:
    """How early before `due` a tap still counts as completing it: a quarter of the gap to the next occurrence.

    A daily reminder accepts taps from 6 hours early, a weekly one from about 42 hours early. A tap on the thing you
    already did a few hours ago is therefore ignored instead of counting for the next occurrence."""
    return (following(cfg, due, tz) - due) / 4


def occurrences_between(cfg: ScheduleConfig, start: datetime, end: datetime, tz: tzinfo, limit: int = 400) -> list[datetime]:
    """Fixed occurrences with start <= t < end, for the calendar entity."""
    if cfg.kind != KIND_FIXED:
        return []
    out: list[datetime] = []
    cursor = start - timedelta(seconds=1)
    while len(out) < limit:
        try:
            nxt = next_fixed(cfg, cursor, tz)
        except ValueError:
            break
        if nxt >= end:
            break
        out.append(nxt)
        cursor = nxt
    return out


def in_quiet(now: datetime, start: time | None, end: time | None, tz: tzinfo) -> bool:
    """True when the local time of `now` is inside the quiet range (the range may wrap past midnight)."""
    if start is None or end is None or start == end:
        return False
    t = now.astimezone(tz).time().replace(tzinfo=None)
    if start < end:
        return start <= t < end
    return t >= start or t < end


def quiet_end(now: datetime, start: time | None, end: time | None, tz: tzinfo) -> datetime:
    """The moment the quiet range that contains `now` ends."""
    assert end is not None
    return next_time_of_day(end, now, tz)
