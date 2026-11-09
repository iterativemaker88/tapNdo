"""Config flow and reminder sub-entry flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.tapndo.const import DOMAIN, SUBENTRY_REMINDER

from .conftest import VITAMIN, setup_entry


async def test_hub_entry_is_single_instance(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "tapNdo"

    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "single_instance_allowed"


async def test_add_fixed_reminder(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_REMINDER), context={"source": SOURCE_USER})
    assert flow["step_id"] == "user"

    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "Stretch", "kind": "fixed"})
    assert flow["step_id"] == "schedule"

    # weekly without days is rejected
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"freq": "weekly", "time": "07:30:00", "window_hours": 0, "interval": 2, "month_day": 1}
    )
    assert flow["errors"] == {"weekdays": "weekdays_required"}

    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"freq": "weekly", "weekdays": ["0", "3"], "time": "07:30:00", "window_hours": 4, "interval": 2, "month_day": 1},
    )
    assert flow["step_id"] == "tags"

    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"tags": ["tag-stretch"], "learn": False})
    assert flow["step_id"] == "notify"

    # an unknown notify service is rejected
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"notify_services": ["notify.nope"], "snooze_minutes": 30, "nag_interval": 0, "nag_max": 0, "escalate_after": 0},
    )
    assert flow["errors"] == {"notify_services": "unknown_service"}

    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {
            "notify_services": ["notify.mobile_app_pixel"],
            "snooze_minutes": 30,
            "nag_interval": 15,
            "nag_max": 3,
            "escalate_after": 2,
        },
    )
    assert flow["step_id"] == "extras"

    # quiet hours need both ends
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"early_completion": True, "quiet_start": "22:00:00"}
    )
    assert flow["errors"] == {"quiet_end": "quiet_both"}

    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"early_completion": True, "quiet_start": "22:00:00", "quiet_end": "07:00:00"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["title"] == "Stretch"
    data = flow["data"]
    assert data["freq"] == "weekly" and data["weekdays"] == ["0", "3"]
    assert data["notify_services"] == ["mobile_app_pixel"]  # stored without the "notify." prefix
    assert data["tags"] == ["tag-stretch"]
    assert data["quiet_start"] == "22:00:00"
    await hass.async_block_till_done()
    assert hass.states.get("sensor.stretch") is not None  # the entry reloaded and the entity exists


async def test_add_after_done_reminder_every_n_days_gets_anchor(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_REMINDER), context={"source": SOURCE_USER})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "Filter", "kind": "fixed"})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"freq": "every_n_days", "time": "09:00:00", "window_hours": 0, "interval": 3, "month_day": 1}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"tags": [], "learn": False})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"snooze_minutes": 60, "nag_interval": 0, "nag_max": 0, "escalate_after": 0}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"early_completion": True})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"]["anchor"]  # every N days counts from the day it was created
    assert "tags" not in flow["data"]  # empty values are not stored


async def test_learn_tag_step(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    flow = await hass.config_entries.subentries.async_init((entry.entry_id, SUBENTRY_REMINDER), context={"source": SOURCE_USER})
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "Bottle", "kind": "after_done"})
    assert flow["step_id"] == "schedule"
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"interval": 30, "unit": "days", "time": "09:00:00", "window_hours": 48}
    )
    assert flow["step_id"] == "tags"
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"learn": True})
    assert flow["type"] is FlowResultType.SHOW_PROGRESS
    assert flow["progress_action"] == "scan"

    hass.bus.async_fire("tag_scanned", {"tag_id": "04-AA-BB"})
    await hass.async_block_till_done()
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"])
    assert flow["step_id"] == "notify"  # the finished scan moved the flow on by itself
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"snooze_minutes": 60, "nag_interval": 0, "nag_max": 0, "escalate_after": 0}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"early_completion": True})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["data"]["tags"] == ["04-AA-BB"]


async def test_reconfigure_keeps_other_values(hass: HomeAssistant) -> None:
    async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, VITAMIN)
    sub_id = next(iter(entry.subentries))
    flow = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_REMINDER), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub_id}
    )
    assert flow["step_id"] == "user"
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"name": "Vitamin D3", "kind": "fixed"})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"], {"freq": "daily", "time": "12:00:00", "window_hours": 0, "interval": 2, "month_day": 1}
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"tags": ["tag-vit"], "learn": False})
    flow = await hass.config_entries.subentries.async_configure(
        flow["flow_id"],
        {"notify_services": ["mobile_app_pixel"], "snooze_minutes": 60, "nag_interval": 0, "nag_max": 0, "escalate_after": 0},
    )
    flow = await hass.config_entries.subentries.async_configure(flow["flow_id"], {"early_completion": True})
    assert flow["type"] is FlowResultType.ABORT
    assert flow["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    updated = entry.subentries[sub_id]
    assert updated.title == "Vitamin D3"
    assert updated.data["time"] == "12:00:00"
    assert updated.data["tags"] == ["tag-vit"]
