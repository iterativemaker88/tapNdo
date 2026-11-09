"""Sending reminders to notify targets."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import ACTION_DONE_PREFIX, ACTION_SNOOZE_PREFIX, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Notify "services" that are not targets
_NOT_TARGETS = {"send_message", "persistent_notification", "notify"}


@dataclass
class Targets:
    """Where a reminder is sent. `services` are names under the notify domain, `entities` are notify entities."""

    services: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.services or self.entities)


def normalise_service(name: str) -> str:
    """Accept 'notify.mobile_app_pixel' as well as 'mobile_app_pixel'."""
    name = name.strip()
    return name.split(".", 1)[1] if name.startswith("notify.") else name


def available_services(hass: HomeAssistant) -> list[str]:
    return sorted(s for s in hass.services.async_services_for_domain("notify") if s not in _NOT_TARGETS)


def is_phone(service: str) -> bool:
    """Companion app services accept action buttons and clearing."""
    return service.startswith("mobile_app_")


def compose(name: str, due_at: datetime, index: int, has_tag: bool) -> tuple[str, str]:
    since = dt_util.as_local(due_at).strftime("%H:%M")
    how = "Tap its tag or press Done." if has_tag else "Press Done when finished."
    if index == 0:
        return name, f"Due at {since}. {how}"
    return name, f"Still due since {since} (reminder {index + 1}). {how}"


async def async_send(
    hass: HomeAssistant,
    entry_id: str,
    reminder_id: str,
    targets: Targets,
    title: str,
    message: str,
    with_actions: bool = True,
) -> None:
    """Send one reminder to every target. A broken target never stops the others."""
    tag = f"tapndo-{reminder_id}"
    for entity in targets.entities:
        issue = f"missing_target_{reminder_id}_{entity}"
        if hass.states.get(entity) is None:
            _raise_issue(hass, issue, entity)
            continue
        ir.async_delete_issue(hass, DOMAIN, issue)
        await _call(
            hass,
            "send_message",
            {"entity_id": entity, "message": message, "title": title},
        )
    for service in targets.services:
        issue = f"missing_target_{reminder_id}_{service}"
        if not hass.services.has_service("notify", service):
            _raise_issue(hass, issue, f"notify.{service}")
            continue
        ir.async_delete_issue(hass, DOMAIN, issue)
        data: dict = {"tag": tag, "group": "tapndo"}
        if with_actions and is_phone(service):
            data["actions"] = [
                {"action": f"{ACTION_DONE_PREFIX}{reminder_id}", "title": "Done"},
                {"action": f"{ACTION_SNOOZE_PREFIX}{reminder_id}", "title": "Snooze"},
            ]
        await _call(hass, service, {"title": title, "message": message, "data": data})


async def async_clear(hass: HomeAssistant, reminder_id: str, targets: Targets) -> None:
    """Remove the notification from phones once the reminder is done or missed."""
    for service in targets.services:
        if is_phone(service) and hass.services.has_service("notify", service):
            await _call(
                hass,
                service,
                {"message": "clear_notification", "data": {"tag": f"tapndo-{reminder_id}"}},
            )


async def _call(hass: HomeAssistant, service: str, data: dict) -> None:
    try:
        await hass.services.async_call("notify", service, data, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.warning("Notify target %s failed: %s", service, err)


def _raise_issue(hass: HomeAssistant, issue_id: str, target: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="missing_target",
        translation_placeholders={"target": target},
    )
