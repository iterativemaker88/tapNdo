"""Home Assistant level tests: entities, tags, notifications, services."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events, async_fire_time_changed, async_mock_service

from custom_components.tapndo.const import DOMAIN

from .conftest import PLANTS, VITAMIN, local, setup_entry


async def advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


async def test_lifecycle_with_tag_and_phone_notification(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    due_events = async_capture_events(hass, "tapndo_due")
    done_events = async_capture_events(hass, "tapndo_done")
    await setup_entry(hass, VITAMIN)

    assert hass.states.get("sensor.vitamin_d").state == "upcoming"
    assert calls == []

    await advance(hass, freezer, local(9, 11, 0, 30))
    state = hass.states.get("sensor.vitamin_d")
    assert state.state == "due"
    assert len(due_events) == 1
    assert len(calls) == 1
    sent = calls[0].data
    assert sent["title"] == "Vitamin D"
    assert "11:00" in sent["message"]
    assert sent["data"]["tag"].startswith("tapndo-")
    assert [a["title"] for a in sent["data"]["actions"]] == ["Done", "Snooze"]
    assert hass.states.get("sensor.tapndo_due").state == "1"
    assert hass.states.get("sensor.tapndo_due").attributes["names"] == ["Vitamin D"]

    # Tap the tag on a reader
    hass.bus.async_fire("tag_scanned", {"tag_id": "tag-vit", "device_id": None})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.vitamin_d")
    assert state.state == "done"
    assert state.attributes["streak"] == 1
    assert len(done_events) == 1 and done_events[0].data["via"] == "tag"
    assert hass.states.get("sensor.tapndo_due").state == "0"
    # the phone notification was cleared
    assert calls[-1].data["message"] == "clear_notification"


async def test_unknown_tag_is_ignored(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 11, 0, 30))
    hass.bus.async_fire("tag_scanned", {"tag_id": "someone-elses-tag"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vitamin_d").state == "due"


async def test_phone_buttons_complete_and_snooze(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, VITAMIN)
    rid = next(iter(entry.subentries))
    await advance(hass, freezer, local(9, 11, 0, 30))

    hass.bus.async_fire("mobile_app_notification_action", {"action": f"TAPNDO_SNOOZE_{rid}"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vitamin_d").state == "snoozed"

    await advance(hass, freezer, local(9, 12, 5))
    assert hass.states.get("sensor.vitamin_d").state == "due"

    hass.bus.async_fire("mobile_app_notification_action", {"action": f"TAPNDO_DONE_{rid}"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vitamin_d").state == "done"


async def test_buttons_and_services(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 11, 0, 30))

    await hass.services.async_call("button", "press", {"entity_id": "button.vitamin_d_snooze"}, blocking=True)
    assert hass.states.get("sensor.vitamin_d").state == "snoozed"

    await advance(hass, freezer, local(9, 12, 5))
    await hass.services.async_call(DOMAIN, "complete", {"entity_id": "sensor.vitamin_d"}, blocking=True)
    assert hass.states.get("sensor.vitamin_d").state == "done"

    await hass.services.async_call(DOMAIN, "skip", {"entity_id": "sensor.vitamin_d"}, blocking=True)
    assert hass.states.get("sensor.vitamin_d").attributes["next_due"].startswith("2026-11-11")

    await hass.services.async_call(DOMAIN, "reset", {"entity_id": "sensor.vitamin_d"}, blocking=True)
    assert hass.states.get("sensor.vitamin_d").attributes["streak"] == 0
    assert hass.states.get("sensor.vitamin_d").state == "upcoming"


async def test_early_tap_counts_and_second_tap_is_ignored(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 9, 30))
    hass.bus.async_fire("tag_scanned", {"tag_id": "tag-vit"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vitamin_d").state == "done"
    hass.bus.async_fire("tag_scanned", {"tag_id": "tag-vit"})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vitamin_d").attributes["streak"] == 1


async def test_after_done_reminder_and_scripts(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    script_calls = async_mock_service(hass, "script", "turn_on")
    plants = dict(PLANTS, on_done="script.lamp_off")
    await setup_entry(hass, plants)
    await advance(hass, freezer, local(9, 10, 1))
    assert hass.states.get("sensor.water_plants").state == "due"
    await advance(hass, freezer, local(10, 15))  # a day later, still inside the 48 h window
    assert hass.states.get("sensor.water_plants").state == "due"
    hass.bus.async_fire("tag_scanned", {"tag_id": "tag-plants"})
    await hass.async_block_till_done()
    state = hass.states.get("sensor.water_plants")
    assert state.state == "done"
    assert state.attributes["next_due"].startswith("2026-11-17")  # 7 days after the 10th
    assert script_calls and script_calls[-1].data["entity_id"] == "script.lamp_off"


async def test_vacation_pauses_everything(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, VITAMIN)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.tapndo_vacation_mode"}, blocking=True)
    await advance(hass, freezer, local(9, 11, 5))
    assert hass.states.get("sensor.vitamin_d").state == "upcoming"
    assert calls == []
    await advance(hass, freezer, local(12, 8))
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.tapndo_vacation_mode"}, blocking=True)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.vitamin_d")
    assert state.state == "upcoming"  # nothing counted as missed
    assert state.attributes["next_due"].startswith("2026-11-12")


async def test_todo_and_calendar(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 11, 0, 30))

    result = await hass.services.async_call(
        "todo", "get_items", {"entity_id": "todo.tapndo_due_now"}, blocking=True, return_response=True
    )
    items = result["todo.tapndo_due_now"]["items"]
    assert [i["summary"] for i in items] == ["Vitamin D"]

    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": "todo.tapndo_due_now", "item": items[0]["uid"], "status": "completed"},
        blocking=True,
    )
    assert hass.states.get("sensor.vitamin_d").state == "done"

    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.tapndo_schedule",
            "start_date_time": local(10).isoformat(),
            "end_date_time": local(13).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    assert len(result["calendar.tapndo_schedule"]["events"]) == 3


async def test_state_survives_reload(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    async_mock_service(hass, "notify", "mobile_app_pixel")
    entry = await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 11, 0, 30))
    hass.bus.async_fire("tag_scanned", {"tag_id": "tag-vit"})
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.vitamin_d")
    assert state.state == "done"
    assert state.attributes["streak"] == 1


async def test_missing_notify_target_raises_a_repair(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    # no notify service registered at all
    await setup_entry(hass, VITAMIN)
    await advance(hass, freezer, local(9, 11, 0, 30))
    issues = {i.translation_key for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN}
    # the notify service is missing, and "tag-vit" was never registered as a tag either
    assert issues == {"missing_target", "missing_tag"}
    assert hass.states.get("sensor.vitamin_d").state == "due"  # the reminder still runs


async def test_require_home_holds_notifications_back(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    calls = async_mock_service(hass, "notify", "mobile_app_pixel")
    hass.states.async_set("person.ash", "not_home")
    await setup_entry(hass, dict(VITAMIN, require_home=["person.ash"]))
    await advance(hass, freezer, local(9, 11, 0, 30))
    assert hass.states.get("sensor.vitamin_d").state == "due"
    assert calls == []


async def test_escalation_adds_second_target(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(local(9, 8))
    first = async_mock_service(hass, "notify", "mobile_app_pixel")
    second = async_mock_service(hass, "notify", "mobile_app_partner")
    cfg = dict(VITAMIN, nag_interval=30, nag_max=2, escalate_after=1, escalate_services=["mobile_app_partner"])
    await setup_entry(hass, cfg)
    await advance(hass, freezer, local(9, 11, 0, 30))
    assert len(first) == 1 and second == []
    await advance(hass, freezer, local(9, 11, 31))
    assert len(first) == 2 and len(second) == 1
