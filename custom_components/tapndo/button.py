"""Done and Snooze buttons for every reminder."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapndoConfigEntry
from .const import SUBENTRY_REMINDER, VIA_BUTTON
from .entity import ReminderEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: TapndoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    manager = entry.runtime_data
    for sub_id, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_REMINDER and sub_id in manager.reminders:
            async_add_entities(
                [DoneButton(manager, sub_id), SnoozeButton(manager, sub_id)], config_subentry_id=sub_id
            )


class DoneButton(ReminderEntity, ButtonEntity):
    _attr_translation_key = "done"
    _attr_icon = "mdi:check"

    def __init__(self, manager, reminder_id: str) -> None:
        super().__init__(manager, reminder_id)
        self._attr_unique_id = f"{reminder_id}_done"

    async def async_press(self) -> None:
        await self.manager.async_complete(self.reminder_id, VIA_BUTTON)


class SnoozeButton(ReminderEntity, ButtonEntity):
    _attr_translation_key = "snooze"
    _attr_icon = "mdi:bell-sleep"

    def __init__(self, manager, reminder_id: str) -> None:
        super().__init__(manager, reminder_id)
        self._attr_unique_id = f"{reminder_id}_snooze"

    async def async_press(self) -> None:
        await self.manager.async_snooze(self.reminder_id)
