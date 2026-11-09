"""Base entities for tapNdo."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import Reminder, TapndoManager, signal_update


class TapndoEntity(Entity):
    """An entity that refreshes whenever the manager changes something."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: TapndoManager) -> None:
        self.manager = manager

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.manager.entry.entry_id), self.async_write_ha_state
            )
        )


class GlobalEntity(TapndoEntity):
    """An entity of the tapNdo device itself (summary, calendar, to-do, vacation)."""

    def __init__(self, manager: TapndoManager) -> None:
        super().__init__(manager)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name="tapNdo",
            manufacturer="tapNdo",
        )


class ReminderEntity(TapndoEntity):
    """An entity that belongs to one reminder."""

    def __init__(self, manager: TapndoManager, reminder_id: str) -> None:
        super().__init__(manager)
        self.reminder_id = reminder_id
        reminder = manager.reminders[reminder_id]
        info = DeviceInfo(
            identifiers={(DOMAIN, reminder_id)},
            name=reminder.name,
            manufacturer="tapNdo",
        )
        hub = dr.async_get(manager.hass).async_get_device(identifiers={(DOMAIN, manager.entry.entry_id)})
        if hub is not None:
            info["via_device_id"] = hub.id
        self._attr_device_info = info

    @property
    def reminder(self) -> Reminder:
        return self.manager.reminders[self.reminder_id]
