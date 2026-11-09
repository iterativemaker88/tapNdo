"""tapNdo: tag-based reminders for Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.start import async_at_started

from .const import DOMAIN
from .manager import TapndoManager

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.SWITCH, Platform.CALENDAR, Platform.TODO]

type TapndoConfigEntry = ConfigEntry[TapndoManager]


async def async_setup_entry(hass: HomeAssistant, entry: TapndoConfigEntry) -> bool:
    """Set up tapNdo from a config entry. Each reminder is a sub-entry."""
    manager = TapndoManager(hass, entry)
    await manager.async_load()
    entry.runtime_data = manager

    # The hub device that every reminder device hangs under
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="tapNdo",
        manufacturer="tapNdo",
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await manager.async_start()

    @callback
    def _check_tags(_hass: HomeAssistant) -> None:
        manager.check_tags()

    async_at_started(hass, _check_tags)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TapndoConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: TapndoConfigEntry) -> None:
    """Reminders were added, changed or removed."""
    await hass.config_entries.async_reload(entry.entry_id)
