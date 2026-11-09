"""Diagnostics: reminder settings and engine state. Contains no credentials."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TapndoConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TapndoConfigEntry) -> dict[str, Any]:
    manager = entry.runtime_data
    return {
        "vacation": manager.vacation,
        "time_zone": str(manager.tz),
        "reminders": {
            r.id: {
                "settings": r.data,
                "state": r.state,
                "runtime": r.rt.to_dict(),
            }
            for r in manager.reminders.values()
        },
    }
