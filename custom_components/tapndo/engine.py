"""The tapNdo state machine. Pure Python: no Home Assistant imports.

A reminder always has one current occurrence (`due_at` .. `window_end_at`):

    waiting --due time--> due --done--> waiting (next occurrence)
                           |--snooze--> snoozed --time--> due
                           |--window ended--> missed --> waiting (next occurrence)

`waiting` shows as `upcoming` until a first result exists, then as `done` or `missed` until the next occurrence is due.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Any

from . import schedule as sch

PHASE_WAITING = "waiting"
PHASE_DUE = "due"
PHASE_SNOOZED = "snoozed"

STATE_UPCOMING = "upcoming"
STATE_DUE = "due"
STATE_SNOOZED = "snoozed"
STATE_DONE = "done"
STATE_MISSED = "missed"

HISTORY_LIMIT = 50


@dataclass
class ReminderConfig:
    """Everything the engine needs to know about one reminder."""

    id: str
    name: str
    schedule: sch.ScheduleConfig = field(default_factory=sch.ScheduleConfig)
    early_completion: bool = True
    nag_interval_min: int = 0  # 0 = notify once
    nag_max: int = 0  # repeat notifications after the first one
    escalate_after: int = 0  # 0 = never; else escalation targets join from this notification on
    quiet_start: time | None = None
    quiet_end: time | None = None
    snooze_minutes: int = 60


@dataclass
class Runtime:
    """What changes while a reminder runs. Serialised to storage."""

    due_at: datetime
    window_end_at: datetime
    phase: str = PHASE_WAITING
    last_result: str | None = None
    last_done: datetime | None = None
    snooze_until: datetime | None = None
    streak: int = 0
    notified: int = 0
    next_notify_at: datetime | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "due_at": self.due_at.isoformat(),
            "window_end_at": self.window_end_at.isoformat(),
            "phase": self.phase,
            "last_result": self.last_result,
            "last_done": self.last_done.isoformat() if self.last_done else None,
            "snooze_until": self.snooze_until.isoformat() if self.snooze_until else None,
            "streak": self.streak,
            "notified": self.notified,
            "next_notify_at": self.next_notify_at.isoformat() if self.next_notify_at else None,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Runtime:
        def dt(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return cls(
            due_at=datetime.fromisoformat(data["due_at"]),
            window_end_at=datetime.fromisoformat(data["window_end_at"]),
            phase=data.get("phase", PHASE_WAITING),
            last_result=data.get("last_result"),
            last_done=dt(data.get("last_done")),
            snooze_until=dt(data.get("snooze_until")),
            streak=data.get("streak", 0),
            notified=data.get("notified", 0),
            next_notify_at=dt(data.get("next_notify_at")),
            history=list(data.get("history", [])),
        )


@dataclass
class Event:
    """Something that happened. The manager turns these into notifications and bus events."""

    kind: str  # due | notify | done | missed | snoozed | unsnoozed | skipped
    index: int = 0  # notify: 0 for the first notification, 1.. for nags
    escalate: bool = False  # notify: escalation targets are included
    via: str | None = None  # done: tag | button | service | todo | phone
    count: int = 1  # missed: occurrences skipped in one go
    early: bool = False  # done: completed before it was due


def _utc(moment: datetime) -> datetime:
    """Work in UTC: aware datetimes that share a tzinfo are compared by wall clock, which breaks across DST changes."""
    return moment.astimezone(timezone.utc)


def state_of(rt: Runtime) -> str:
    if rt.phase == PHASE_DUE:
        return STATE_DUE
    if rt.phase == PHASE_SNOOZED:
        return STATE_SNOOZED
    return rt.last_result or STATE_UPCOMING


def _set_next(cfg: ReminderConfig, rt: Runtime, due: datetime, tz: tzinfo) -> None:
    rt.due_at = due
    rt.window_end_at = sch.window_end(cfg.schedule, due, tz)
    rt.phase = PHASE_WAITING
    rt.snooze_until = None
    rt.notified = 0
    rt.next_notify_at = None


def init_runtime(cfg: ReminderConfig, now: datetime, tz: tzinfo) -> Runtime:
    now = _utc(now)
    due = sch.first_due(cfg.schedule, now, tz)
    return Runtime(due_at=due, window_end_at=sch.window_end(cfg.schedule, due, tz))


def _after_quiet(cfg: ReminderConfig, moment: datetime, tz: tzinfo) -> datetime:
    if sch.in_quiet(moment, cfg.quiet_start, cfg.quiet_end, tz):
        return sch.quiet_end(moment, cfg.quiet_start, cfg.quiet_end, tz)
    return moment


def _append_history(rt: Runtime, entry: dict[str, Any]) -> None:
    rt.history.append(entry)
    del rt.history[:-HISTORY_LIMIT]


def _miss(cfg: ReminderConfig, rt: Runtime, now: datetime, tz: tzinfo) -> Event:
    """The window ended without a completion. Move to the next occurrence that is not already over."""
    missed_at = rt.window_end_at
    _append_history(rt, {"t": missed_at.isoformat(), "result": "missed"})
    rt.streak = 0
    rt.last_result = STATE_MISSED
    count = 1
    if cfg.schedule.kind == sch.KIND_AFTER_DONE:
        # A chore you owe is not forgiven: ask again at the same time tomorrow, not after another interval.
        nxt = sch.next_time_of_day(cfg.schedule.at, missed_at, tz)
    else:
        nxt = sch.next_fixed(cfg.schedule, rt.due_at, tz)
    while sch.window_end(cfg.schedule, nxt, tz) <= now:
        count += 1
        if cfg.schedule.kind == sch.KIND_AFTER_DONE:
            nxt = sch.next_time_of_day(cfg.schedule.at, sch.window_end(cfg.schedule, nxt, tz), tz)
        else:
            nxt = sch.next_fixed(cfg.schedule, nxt, tz)
    _set_next(cfg, rt, nxt, tz)
    return Event("missed", count=count)


def tick(cfg: ReminderConfig, rt: Runtime, now: datetime, tz: tzinfo) -> list[Event]:
    """Advance the reminder to `now`. Returns what happened, oldest first."""
    now = _utc(now)
    events: list[Event] = []
    for _ in range(100):
        if rt.phase == PHASE_WAITING:
            if now < rt.due_at:
                break
            if now >= rt.window_end_at:
                events.append(_miss(cfg, rt, now, tz))
                continue
            rt.phase = PHASE_DUE
            rt.notified = 0
            rt.next_notify_at = _after_quiet(cfg, now, tz)
            events.append(Event("due"))
            continue
        if rt.phase == PHASE_SNOOZED:
            if now >= rt.window_end_at:
                events.append(_miss(cfg, rt, now, tz))
                continue
            if rt.snooze_until is not None and now >= rt.snooze_until:
                rt.phase = PHASE_DUE
                rt.snooze_until = None
                rt.notified = 0
                rt.next_notify_at = _after_quiet(cfg, now, tz)
                events.append(Event("unsnoozed"))
                continue
            break
        # due
        if now >= rt.window_end_at:
            events.append(_miss(cfg, rt, now, tz))
            continue
        if rt.next_notify_at is not None and now >= rt.next_notify_at:
            index = rt.notified
            rt.notified += 1
            escalate = cfg.escalate_after > 0 and index >= cfg.escalate_after
            events.append(Event("notify", index=index, escalate=escalate))
            if cfg.nag_interval_min > 0 and index < cfg.nag_max:
                rt.next_notify_at = _after_quiet(cfg, now + timedelta(minutes=cfg.nag_interval_min), tz)
            else:
                rt.next_notify_at = None
        break
    return events


def complete(
    cfg: ReminderConfig,
    rt: Runtime,
    now: datetime,
    tz: tzinfo,
    via: str,
    by: str | None = None,
    where: str | None = None,
) -> Event | None:
    """Mark the current occurrence done. Returns None when the tap is ignored (too early, early disabled)."""
    now = _utc(now)
    early = False
    if rt.phase == PHASE_WAITING and now < rt.due_at:
        if not cfg.early_completion:
            return None
        lead = sch.early_lead(cfg.schedule, rt.due_at, tz)
        if now < rt.due_at - lead:
            return None
        if rt.last_done is not None and rt.last_done >= rt.due_at - lead:
            return None
        early = True
    rt.last_done = now
    rt.last_result = STATE_DONE
    rt.streak += 1
    _append_history(
        rt, {"t": now.isoformat(), "result": "done", "via": via, "by": by, "where": where, "early": early}
    )
    if cfg.schedule.kind == sch.KIND_AFTER_DONE:
        nxt = sch.next_after_done(cfg.schedule, now, tz)
    else:
        nxt = sch.next_fixed(cfg.schedule, rt.due_at, tz)
        while nxt <= now and sch.window_end(cfg.schedule, nxt, tz) <= now:
            nxt = sch.next_fixed(cfg.schedule, nxt, tz)
    _set_next(cfg, rt, nxt, tz)
    return Event("done", via=via, early=early)


def snooze(cfg: ReminderConfig, rt: Runtime, now: datetime, minutes: int | None = None) -> Event | None:
    now = _utc(now)
    if rt.phase not in (PHASE_DUE, PHASE_SNOOZED):
        return None
    rt.phase = PHASE_SNOOZED
    rt.snooze_until = now + timedelta(minutes=minutes or cfg.snooze_minutes)
    rt.next_notify_at = None
    return Event("snoozed")


def skip(cfg: ReminderConfig, rt: Runtime, now: datetime, tz: tzinfo) -> Event:
    """Skip the current occurrence without a result and without touching the streak."""
    now = _utc(now)
    _append_history(rt, {"t": now.isoformat(), "result": "skipped"})
    if cfg.schedule.kind == sch.KIND_AFTER_DONE:
        nxt = sch.next_after_done(cfg.schedule, now, tz)
    else:
        nxt = sch.next_fixed(cfg.schedule, max(rt.due_at, now), tz)
    _set_next(cfg, rt, nxt, tz)
    return Event("skipped")


def reset(cfg: ReminderConfig, rt: Runtime, now: datetime, tz: tzinfo) -> None:
    """Forget the history and start the schedule again from `now`."""
    fresh = init_runtime(cfg, now, tz)
    rt.__dict__.update(fresh.__dict__)


def resume(cfg: ReminderConfig, rt: Runtime, now: datetime, tz: tzinfo, paused_for: timedelta) -> None:
    """Called when vacation mode ends. Nothing is counted as missed for the time away."""
    now = _utc(now)
    if rt.phase == PHASE_WAITING:
        if cfg.schedule.kind == sch.KIND_AFTER_DONE:
            rt.due_at += paused_for
            rt.window_end_at += paused_for
        elif rt.due_at <= now:
            _set_next(cfg, rt, sch.next_fixed(cfg.schedule, now, tz), tz)
    elif rt.phase == PHASE_DUE:
        rt.window_end_at = max(rt.window_end_at, now + timedelta(hours=1))
        rt.notified = 0
        rt.next_notify_at = _after_quiet(cfg, now, tz)
    else:
        rt.window_end_at = max(rt.window_end_at, now + timedelta(hours=1))
