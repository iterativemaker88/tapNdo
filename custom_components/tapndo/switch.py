"""Vacation switch: pauses every reminder."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapndoConfigEntry
from .entity import GlobalEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: TapndoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VacationSwitch(entry.runtime_data)])


class VacationSwitch(GlobalEntity, SwitchEntity):
    _attr_translation_key = "vacation"
    _attr_icon = "mdi:airplane"

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_vacation"

    @property
    def is_on(self) -> bool:
        return self.manager.vacation

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.manager.async_set_vacation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.manager.async_set_vacation(False)
