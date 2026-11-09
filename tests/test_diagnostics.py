"""Diagnostics."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.tapndo.diagnostics import async_get_config_entry_diagnostics

from .conftest import VITAMIN, local, setup_entry


async def test_diagnostics(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, VITAMIN)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["vacation"] is False
    (reminder,) = result["reminders"].values()
    assert reminder["state"] == "upcoming"
    assert reminder["settings"]["name"] == "Vitamin D"
    assert reminder["runtime"]["phase"] == "waiting"
