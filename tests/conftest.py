"""Shared fixtures for the Home Assistant level tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tapndo.const import DOMAIN, SUBENTRY_REMINDER

BERLIN = ZoneInfo("Europe/Berlin")


def local(day: int, hh: int = 0, mm: int = 0, ss: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hh, mm, ss, tzinfo=BERLIN)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the tests load custom_components/tapndo."""
    yield


VITAMIN: dict[str, Any] = {
    "name": "Vitamin D",
    "kind": "fixed",
    "freq": "daily",
    "time": "11:00:00",
    "window_hours": 0,
    "tags": ["tag-vit"],
    "notify_services": ["mobile_app_pixel"],
    "snooze_minutes": 60,
    "nag_interval": 0,
    "nag_max": 0,
    "escalate_after": 0,
    "early_completion": True,
}

PLANTS: dict[str, Any] = {
    "name": "Water plants",
    "kind": "after_done",
    "interval": 1,
    "unit": "weeks",
    "time": "10:00:00",
    "window_hours": 48,
    "tags": ["tag-plants"],
    "notify_services": ["mobile_app_pixel"],
    "early_completion": True,
}


async def setup_entry(hass: HomeAssistant, *reminders: dict[str, Any]) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="tapNdo",
        data={},
        subentries_data=[
            ConfigSubentryData(data=r, subentry_type=SUBENTRY_REMINDER, title=r["name"], unique_id=None)
            for r in reminders
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
