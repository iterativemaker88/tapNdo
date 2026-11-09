"""Calendar of upcoming due times."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TapndoConfigEntry
from . import schedule as sch
from .entity import GlobalEntity

PARALLEL_UPDATES = 0
EVENT_LENGTH = timedelta(minutes=30)


async def async_setup_entry(
    hass: HomeAssistant, entry: TapndoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TapndoCalendar(entry.runtime_data)])


class TapndoCalendar(GlobalEntity, CalendarEntity):
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """The next due time, or the first reminder that is due right now."""
        current = [r for r in self.manager.reminders.values() if r.rt.phase != "waiting"]
        pool = current or list(self.manager.reminders.values())
        if not pool:
            return None
        nearest = min(pool, key=lambda r: r.rt.due_at)
        return self._event(nearest.name, nearest.rt.due_at, nearest.id)

    @staticmethod
    def _event(name: str, start: datetime, uid: str) -> CalendarEvent:
        return CalendarEvent(start=start, end=start + EVENT_LENGTH, summary=name, uid=f"{uid}-{start.isoformat()}")

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime) -> list[CalendarEvent]:
        tz = self.manager.tz
        events: list[CalendarEvent] = []
        for reminder in self.manager.reminders.values():
            if reminder.cfg.schedule.kind == sch.KIND_FIXED:
                for moment in sch.occurrences_between(reminder.cfg.schedule, max(start_date, dt_util.utcnow() - EVENT_LENGTH), end_date, tz):
                    events.append(self._event(reminder.name, moment, reminder.id))
            elif start_date <= reminder.rt.due_at < end_date:
                events.append(self._event(reminder.name, reminder.rt.due_at, reminder.id))
        return sorted(events, key=lambda e: e.start)
