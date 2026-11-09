"""Sensors: one state sensor per reminder and a summary of what is due."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback, async_get_current_platform

from . import TapndoConfigEntry
from .const import SUBENTRY_REMINDER, VIA_SERVICE
from .engine import (
    STATE_DONE,
    STATE_DUE,
    STATE_MISSED,
    STATE_SNOOZED,
    STATE_UPCOMING,
)
from .entity import GlobalEntity, ReminderEntity

PARALLEL_UPDATES = 0

STATES = [STATE_UPCOMING, STATE_DUE, STATE_SNOOZED, STATE_DONE, STATE_MISSED]


async def async_setup_entry(
    hass: HomeAssistant, entry: TapndoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    manager = entry.runtime_data
    async_add_entities([DueSummarySensor(manager)])
    for sub_id, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_REMINDER and sub_id in manager.reminders:
            async_add_entities([ReminderSensor(manager, sub_id)], config_subentry_id=sub_id)

    platform = async_get_current_platform()
    platform.async_register_entity_service("complete", {}, "async_service_complete")
    platform.async_register_entity_service(
        "snooze", {vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))}, "async_service_snooze"
    )
    platform.async_register_entity_service("skip", {}, "async_service_skip")
    platform.async_register_entity_service("reset", {}, "async_service_reset")


class ReminderSensor(ReminderEntity, SensorEntity):
    """The state of one reminder."""

    _attr_name = None
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATES
    _attr_translation_key = "reminder"
    _unrecorded_attributes = frozenset({"history", "tags"})

    def __init__(self, manager, reminder_id: str) -> None:
        super().__init__(manager, reminder_id)
        self._attr_unique_id = f"{reminder_id}_state"

    @property
    def native_value(self) -> str:
        return self.reminder.state

    @property
    def icon(self) -> str:
        return {
            STATE_DUE: "mdi:bell-ring",
            STATE_SNOOZED: "mdi:bell-sleep",
            STATE_DONE: "mdi:check-circle",
            STATE_MISSED: "mdi:alert-circle",
        }.get(self.reminder.state, "mdi:tag-text")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.reminder
        last = r.last_done_entry or {}
        return {
            "reminder_id": r.id,
            "next_due": r.rt.due_at.isoformat(),
            "window_end": r.rt.window_end_at.isoformat(),
            "last_done": r.rt.last_done.isoformat() if r.rt.last_done else None,
            "streak": r.rt.streak,
            "last_by": last.get("by"),
            "last_where": last.get("where"),
            "snooze_until": r.rt.snooze_until.isoformat() if r.rt.snooze_until else None,
            "tags": r.tags,
            "history": r.rt.history[-10:],
        }

    async def async_service_complete(self) -> None:
        await self.manager.async_complete(self.reminder_id, VIA_SERVICE)

    async def async_service_snooze(self, minutes: int | None = None) -> None:
        await self.manager.async_snooze(self.reminder_id, minutes)

    async def async_service_skip(self) -> None:
        await self.manager.async_skip(self.reminder_id)

    async def async_service_reset(self) -> None:
        await self.manager.async_reset(self.reminder_id)


class DueSummarySensor(GlobalEntity, SensorEntity):
    """How many reminders are due, and which. This is what dashboards and the e-ink display read."""

    _attr_translation_key = "due"
    _attr_icon = "mdi:bell-badge"
    _attr_native_unit_of_measurement = "reminders"
    _unrecorded_attributes = frozenset({"items"})

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_due"

    @property
    def native_value(self) -> int:
        return sum(1 for item in self.manager.due_items() if not item["snoozed"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nxt = self.manager.next_up()
        return {
            "items": self.manager.due_items(),
            "names": [i["name"] for i in self.manager.due_items()],
            "next_name": nxt.name if nxt else None,
            "next_due": nxt.rt.due_at.isoformat() if nxt else None,
            "vacation": self.manager.vacation,
        }
