"""The tapNdo manager: owns every reminder of a config entry, drives the engine and talks to Home Assistant."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, Context, Event as HAEvent, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import engine as eng
from . import notifier
from . import schedule as sch
from .const import (
    ACTION_DONE_PREFIX,
    ACTION_SNOOZE_PREFIX,
    CONF_ANCHOR,
    CONF_EARLY,
    CONF_ESCALATE_AFTER,
    CONF_ESCALATE_ENTITIES,
    CONF_ESCALATE_SERVICES,
    CONF_FREQ,
    CONF_INTERVAL,
    CONF_KIND,
    CONF_MONTH_DAY,
    CONF_NAG_INTERVAL,
    CONF_NAG_MAX,
    CONF_NAME,
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_SERVICES,
    CONF_ON_DONE,
    CONF_ON_DUE,
    CONF_ON_MISSED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REQUIRE_HOME,
    CONF_SNOOZE_MINUTES,
    CONF_TAGS,
    CONF_TIME,
    CONF_UNIT,
    CONF_WEEKDAYS,
    CONF_WINDOW_HOURS,
    DOMAIN,
    EVENT_DONE,
    EVENT_DUE,
    EVENT_MISSED,
    EVENT_MOBILE_ACTION,
    EVENT_TAG_SCANNED,
    STORE_VERSION,
    TICK_SECONDS,
    VIA_PHONE,
    VIA_TAG,
)

_LOGGER = logging.getLogger(__name__)

_SCHEDULE_KEYS = (
    CONF_KIND,
    CONF_FREQ,
    CONF_TIME,
    CONF_WEEKDAYS,
    CONF_INTERVAL,
    CONF_UNIT,
    CONF_MONTH_DAY,
    CONF_ANCHOR,
    CONF_WINDOW_HOURS,
)


def signal_update(entry_id: str) -> str:
    return f"{DOMAIN}_update_{entry_id}"


def parse_time(value: str | None) -> time | None:
    if not value:
        return None
    return time.fromisoformat(value)


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def schedule_from_data(data: dict[str, Any]) -> sch.ScheduleConfig:
    return sch.ScheduleConfig(
        kind=data.get(CONF_KIND, sch.KIND_FIXED),
        freq=data.get(CONF_FREQ, sch.FREQ_DAILY),
        at=parse_time(data.get(CONF_TIME)) or time(9, 0),
        weekdays=tuple(int(d) for d in _as_list(data.get(CONF_WEEKDAYS))),
        interval=int(data.get(CONF_INTERVAL, 1)),
        unit=data.get(CONF_UNIT, sch.UNIT_DAYS),
        month_day=int(data.get(CONF_MONTH_DAY, 1)),
        anchor=date.fromisoformat(data[CONF_ANCHOR]) if data.get(CONF_ANCHOR) else None,
        window_hours=int(data.get(CONF_WINDOW_HOURS, 0)),
    )


@dataclass
class Reminder:
    """One reminder: its settings, its engine state and its targets."""

    id: str
    name: str
    data: dict[str, Any]
    cfg: eng.ReminderConfig
    rt: eng.Runtime
    tags: list[str] = field(default_factory=list)
    targets: notifier.Targets = field(default_factory=notifier.Targets)
    escalation: notifier.Targets = field(default_factory=notifier.Targets)
    require_home: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)

    @property
    def state(self) -> str:
        return eng.state_of(self.rt)

    @property
    def last_done_entry(self) -> dict[str, Any] | None:
        for entry in reversed(self.rt.history):
            if entry.get("result") == "done":
                return entry
        return None


def fingerprint(data: dict[str, Any]) -> str:
    return json.dumps({k: data.get(k) for k in _SCHEDULE_KEYS}, sort_keys=True, default=str)


def build_config(subentry_id: str, data: dict[str, Any]) -> eng.ReminderConfig:
    return eng.ReminderConfig(
        id=subentry_id,
        name=data[CONF_NAME],
        schedule=schedule_from_data(data),
        early_completion=bool(data.get(CONF_EARLY, True)),
        nag_interval_min=int(data.get(CONF_NAG_INTERVAL, 0)),
        nag_max=int(data.get(CONF_NAG_MAX, 0)),
        escalate_after=int(data.get(CONF_ESCALATE_AFTER, 0)),
        quiet_start=parse_time(data.get(CONF_QUIET_START)),
        quiet_end=parse_time(data.get(CONF_QUIET_END)),
        snooze_minutes=int(data.get(CONF_SNOOZE_MINUTES, 60)),
    )


class TapndoManager:
    """Runs all reminders of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.reminders: dict[str, Reminder] = {}
        self.vacation = False
        self._paused_at: datetime | None = None
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []

    # ---------------------------------------------------------------- lifecycle

    @property
    def tz(self):
        return dt_util.get_default_time_zone()

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        saved = stored.get("reminders", {})
        self.vacation = bool(stored.get("vacation", False))
        if stored.get("paused_at"):
            self._paused_at = datetime.fromisoformat(stored["paused_at"])
        now = dt_util.utcnow()
        for sub_id, sub in self.entry.subentries.items():
            if sub.subentry_type != "reminder":
                continue
            self.reminders[sub_id] = self._build(sub, saved.get(sub_id), now)

    def _build(self, sub: ConfigSubentry, saved: dict[str, Any] | None, now: datetime) -> Reminder:
        data = dict(sub.data)
        cfg = build_config(sub.subentry_id, data)
        rt: eng.Runtime | None = None
        if saved and saved.get("fp") == fingerprint(data):
            try:
                rt = eng.Runtime.from_dict(saved["rt"])
            except (KeyError, ValueError):
                rt = None
        if rt is None:
            rt = eng.init_runtime(cfg, now, self.tz)
            if saved and saved.get("rt"):  # schedule changed: keep the history and streak
                try:
                    old = eng.Runtime.from_dict(saved["rt"])
                    rt.history, rt.streak, rt.last_done, rt.last_result = old.history, old.streak, old.last_done, old.last_result
                except (KeyError, ValueError):
                    pass
        return Reminder(
            id=sub.subentry_id,
            name=data[CONF_NAME],
            data=data,
            cfg=cfg,
            rt=rt,
            tags=_as_list(data.get(CONF_TAGS)),
            targets=notifier.Targets(
                services=[notifier.normalise_service(s) for s in _as_list(data.get(CONF_NOTIFY_SERVICES))],
                entities=_as_list(data.get(CONF_NOTIFY_ENTITIES)),
            ),
            escalation=notifier.Targets(
                services=[notifier.normalise_service(s) for s in _as_list(data.get(CONF_ESCALATE_SERVICES))],
                entities=_as_list(data.get(CONF_ESCALATE_ENTITIES)),
            ),
            require_home=_as_list(data.get(CONF_REQUIRE_HOME)),
            scripts={
                "due": data.get(CONF_ON_DUE) or "",
                "done": data.get(CONF_ON_DONE) or "",
                "missed": data.get(CONF_ON_MISSED) or "",
            },
        )

    async def async_start(self) -> None:
        self._unsubs.append(self.hass.bus.async_listen(EVENT_TAG_SCANNED, self._on_tag_scanned))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_MOBILE_ACTION, self._on_phone_action))
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_interval, timedelta(seconds=TICK_SECONDS))
        )
        await self.async_tick()

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._snapshot())

    # ---------------------------------------------------------------- storage

    def _snapshot(self) -> dict[str, Any]:
        return {
            "vacation": self.vacation,
            "paused_at": self._paused_at.isoformat() if self._paused_at else None,
            "reminders": {
                r.id: {"fp": fingerprint(r.data), "rt": r.rt.to_dict()} for r in self.reminders.values()
            },
        }

    def _save(self) -> None:
        self._store.async_delay_save(self._snapshot, 5)

    @callback
    def _changed(self) -> None:
        self._save()
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    # ---------------------------------------------------------------- ticking

    async def _on_interval(self, _now: datetime) -> None:
        await self.async_tick()

    async def async_tick(self) -> None:
        if self.vacation:
            return
        now = dt_util.utcnow()
        changed = False
        for reminder in list(self.reminders.values()):
            events = eng.tick(reminder.cfg, reminder.rt, now, self.tz)
            if events:
                changed = True
                await self._handle(reminder, events)
        if changed:
            self._changed()

    # ---------------------------------------------------------------- events

    async def _handle(self, reminder: Reminder, events: list[eng.Event]) -> None:
        for event in events:
            payload = {
                "reminder_id": reminder.id,
                "name": reminder.name,
                "state": reminder.state,
            }
            if event.kind == "due":
                self.hass.bus.async_fire(EVENT_DUE, payload)
                self._run_script(reminder, "due", payload)
            elif event.kind == "notify":
                await self._notify(reminder, event)
            elif event.kind == "done":
                last = reminder.last_done_entry or {}
                payload |= {"via": event.via, "by": last.get("by"), "where": last.get("where"), "early": event.early}
                self.hass.bus.async_fire(EVENT_DONE, payload)
                self._run_script(reminder, "done", payload)
                await notifier.async_clear(self.hass, reminder.id, reminder.targets)
                await notifier.async_clear(self.hass, reminder.id, reminder.escalation)
            elif event.kind == "missed":
                payload["count"] = event.count
                self.hass.bus.async_fire(EVENT_MISSED, payload)
                self._run_script(reminder, "missed", payload)
                await notifier.async_clear(self.hass, reminder.id, reminder.targets)
                await notifier.async_clear(self.hass, reminder.id, reminder.escalation)

    async def _notify(self, reminder: Reminder, event: eng.Event) -> None:
        if reminder.require_home and not any(self.hass.states.is_state(p, "home") for p in reminder.require_home):
            return
        targets = notifier.Targets(list(reminder.targets.services), list(reminder.targets.entities))
        if event.escalate:
            targets.services += [s for s in reminder.escalation.services if s not in targets.services]
            targets.entities += [e for e in reminder.escalation.entities if e not in targets.entities]
        if not targets:
            return
        title, message = notifier.compose(reminder.name, reminder.rt.due_at, event.index, bool(reminder.tags))
        await notifier.async_send(self.hass, self.entry.entry_id, reminder.id, targets, title, message)

    def _run_script(self, reminder: Reminder, kind: str, variables: dict[str, Any]) -> None:
        script = reminder.scripts.get(kind)
        if not script:
            return
        self.hass.async_create_task(
            self.hass.services.async_call("script", "turn_on", {"entity_id": script, "variables": variables})
        )

    # ---------------------------------------------------------------- actions

    async def async_complete(
        self, reminder_id: str, via: str, by: str | None = None, where: str | None = None
    ) -> bool:
        reminder = self.reminders.get(reminder_id)
        if reminder is None:
            return False
        now = dt_util.utcnow()
        if not self.vacation:
            await self._handle(reminder, eng.tick(reminder.cfg, reminder.rt, now, self.tz))
        event = eng.complete(reminder.cfg, reminder.rt, now, self.tz, via=via, by=by, where=where)
        if event is None:
            return False
        await self._handle(reminder, [event])
        self._changed()
        return True

    async def async_snooze(self, reminder_id: str, minutes: int | None = None) -> bool:
        reminder = self.reminders.get(reminder_id)
        if reminder is None:
            return False
        event = eng.snooze(reminder.cfg, reminder.rt, dt_util.utcnow(), minutes)
        if event is None:
            return False
        await notifier.async_clear(self.hass, reminder.id, reminder.targets)
        self._changed()
        return True

    async def async_skip(self, reminder_id: str) -> None:
        reminder = self.reminders[reminder_id]
        eng.skip(reminder.cfg, reminder.rt, dt_util.utcnow(), self.tz)
        await notifier.async_clear(self.hass, reminder.id, reminder.targets)
        self._changed()

    async def async_reset(self, reminder_id: str) -> None:
        reminder = self.reminders[reminder_id]
        eng.reset(reminder.cfg, reminder.rt, dt_util.utcnow(), self.tz)
        await notifier.async_clear(self.hass, reminder.id, reminder.targets)
        self._changed()

    async def async_set_vacation(self, on: bool) -> None:
        now = dt_util.utcnow()
        if on and not self.vacation:
            self.vacation = True
            self._paused_at = now
        elif not on and self.vacation:
            away = now - (self._paused_at or now)
            self.vacation = False
            self._paused_at = None
            for reminder in self.reminders.values():
                eng.resume(reminder.cfg, reminder.rt, now, self.tz, away)
            self._changed()
            await self.async_tick()
            return
        self._changed()

    # ---------------------------------------------------------------- incoming

    async def _resolve_user(self, context: Context | None) -> str | None:
        if context is None or not context.user_id:
            return None
        user = await self.hass.auth.async_get_user(context.user_id)
        return user.name if user else None

    def _resolve_place(self, device_id: str | None) -> str | None:
        if not device_id:
            return None
        device = dr.async_get(self.hass).async_get(device_id)
        if device is None:
            return None
        if device.area_id:
            area = ar.async_get(self.hass).async_get_area(device.area_id)
            if area:
                return area.name
        return device.name_by_user or device.name

    async def _on_tag_scanned(self, event: HAEvent) -> None:
        tag_id = event.data.get("tag_id")
        if not tag_id:
            return
        matches = [r for r in self.reminders.values() if tag_id in r.tags]
        if not matches:
            return
        by = await self._resolve_user(event.context)
        where = self._resolve_place(event.data.get("device_id"))
        for reminder in matches:
            await self.async_complete(reminder.id, VIA_TAG, by=by, where=where)

    async def _on_phone_action(self, event: HAEvent) -> None:
        action = str(event.data.get("action", ""))
        by = await self._resolve_user(event.context)
        if action.startswith(ACTION_DONE_PREFIX):
            await self.async_complete(action[len(ACTION_DONE_PREFIX):], VIA_PHONE, by=by)
        elif action.startswith(ACTION_SNOOZE_PREFIX):
            await self.async_snooze(action[len(ACTION_SNOOZE_PREFIX):])

    # ---------------------------------------------------------------- repairs

    @callback
    def check_tags(self) -> None:
        """Raise a repair for tags that no longer exist in the tag registry."""
        known = {
            state.attributes.get("tag_id") for state in self.hass.states.async_all("tag")
        }
        for reminder in self.reminders.values():
            for tag in reminder.tags:
                issue_id = f"missing_tag_{reminder.id}_{tag}"
                if tag in known:
                    ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                else:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        issue_id,
                        is_fixable=False,
                        severity=ir.IssueSeverity.WARNING,
                        translation_key="missing_tag",
                        translation_placeholders={"reminder": reminder.name, "tag": tag},
                    )

    # ---------------------------------------------------------------- summaries

    def due_items(self) -> list[dict[str, Any]]:
        items = []
        for r in sorted(self.reminders.values(), key=lambda x: x.rt.due_at):
            if r.rt.phase in (eng.PHASE_DUE, eng.PHASE_SNOOZED):
                items.append(
                    {
                        "id": r.id,
                        "name": r.name,
                        "due_since": r.rt.due_at.isoformat(),
                        "snoozed": r.rt.phase == eng.PHASE_SNOOZED,
                    }
                )
        return items

    def next_up(self) -> Reminder | None:
        waiting = [r for r in self.reminders.values() if r.rt.phase == eng.PHASE_WAITING]
        return min(waiting, key=lambda r: r.rt.due_at, default=None)
