"""Config flow: one hub entry, and every reminder is a sub-entry."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from . import notifier
from . import schedule as sch
from .const import (
    CONF_ANCHOR,
    CONF_EARLY,
    CONF_ESCALATE_AFTER,
    CONF_ESCALATE_ENTITIES,
    CONF_ESCALATE_SERVICES,
    CONF_FREQ,
    CONF_INTERVAL,
    CONF_KIND,
    CONF_LEARN,
    CONF_MONTH_DAY,
    CONF_NAG_INTERVAL,
    CONF_NAG_MAX,
    CONF_NAME,
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_SERVICES,
    CONF_ON_DONE,
    CONF_ON_DUE,
    CONF_ON_MISSED,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_REQUIRE_HOME,
    CONF_SNOOZE_MINUTES,
    CONF_TAGS,
    CONF_TIME,
    CONF_UNIT,
    CONF_WEEKDAYS,
    CONF_WINDOW_HOURS,
    DOMAIN,
    EVENT_TAG_SCANNED,
    LEARN_TIMEOUT_SECONDS,
    SUBENTRY_REMINDER,
)


def _num(minimum: int, maximum: int, step: int = 1) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX))


def _select(options: list[str], key: str | None, multiple: bool = False, custom: bool = False) -> SelectSelector:
    config: dict[str, Any] = {
        "options": options,
        "multiple": multiple,
        "custom_value": custom,
        "mode": SelectSelectorMode.DROPDOWN,
    }
    if key:
        config["translation_key"] = key
    return SelectSelector(SelectSelectorConfig(**config))


def _tag_options(hass: HomeAssistant, selected: list[str]) -> list[dict[str, str]]:
    """Tags from Home Assistant's tag registry, as (tag id, friendly name)."""
    options: dict[str, str] = {}
    for state in hass.states.async_all("tag"):
        tag_id = state.attributes.get("tag_id")
        if tag_id:
            options[tag_id] = state.name
    for tag_id in selected:
        options.setdefault(tag_id, tag_id)
    return [{"value": value, "label": label} for value, label in options.items()]


class TapndoConfigFlow(ConfigFlow, domain=DOMAIN):
    """The hub entry holds no settings: reminders are added as sub-entries."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="tapNdo", data={})
        return self.async_show_form(step_id="user")

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_REMINDER: ReminderSubentryFlow}


class ReminderSubentryFlow(ConfigSubentryFlow):
    """Add or change one reminder: name, schedule, tags, targets, extras."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._learn_task: asyncio.Task[str | None] | None = None

    # -------------------------------------------------------------- helpers

    def _schema(self, fields: dict[Any, Any]) -> vol.Schema:
        return self.add_suggested_values_to_schema(vol.Schema(fields), self._data)

    def _finish(self) -> SubentryFlowResult:
        data = {k: v for k, v in self._data.items() if v not in (None, "", [])}
        data.pop(CONF_LEARN, None)
        if data.get(CONF_FREQ) == sch.FREQ_EVERY_N_DAYS and not data.get(CONF_ANCHOR):
            data[CONF_ANCHOR] = dt_util.as_local(dt_util.utcnow()).date().isoformat()
        if self.source == "reconfigure":
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=data[CONF_NAME], data=data
            )
        return self.async_create_entry(title=data[CONF_NAME], data=data)

    # -------------------------------------------------------------- steps

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._data = dict(self._get_reconfigure_subentry().data)
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "name_required"
            else:
                self._data.update(user_input)
                self._data[CONF_NAME] = user_input[CONF_NAME].strip()
                return await self.async_step_schedule()
        schema = self._schema(
            {
                vol.Required(CONF_NAME): TextSelector(),
                vol.Required(CONF_KIND, default=sch.KIND_FIXED): _select(
                    [sch.KIND_FIXED, sch.KIND_AFTER_DONE], "kind"
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_schedule(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        after_done = self._data.get(CONF_KIND) == sch.KIND_AFTER_DONE
        errors: dict[str, str] = {}
        if user_input is not None:
            for key in (CONF_INTERVAL, CONF_MONTH_DAY, CONF_WINDOW_HOURS):
                if key in user_input:
                    user_input[key] = int(user_input[key])
            if not after_done and user_input.get(CONF_FREQ) == sch.FREQ_WEEKLY and not user_input.get(CONF_WEEKDAYS):
                errors[CONF_WEEKDAYS] = "weekdays_required"
            else:
                self._data.update(user_input)
                return await self.async_step_tags()
        if after_done:
            fields: dict[Any, Any] = {
                vol.Required(CONF_INTERVAL, default=7): _num(1, 365),
                vol.Required(CONF_UNIT, default=sch.UNIT_DAYS): _select([sch.UNIT_DAYS, sch.UNIT_WEEKS], "unit"),
                vol.Required(CONF_TIME, default="09:00:00"): TimeSelector(),
                vol.Required(CONF_WINDOW_HOURS, default=48): _num(0, 720),
            }
        else:
            fields = {
                vol.Required(CONF_FREQ, default=sch.FREQ_DAILY): _select(
                    [sch.FREQ_DAILY, sch.FREQ_WEEKLY, sch.FREQ_EVERY_N_DAYS, sch.FREQ_MONTHLY], "freq"
                ),
                vol.Required(CONF_TIME, default="09:00:00"): TimeSelector(),
                vol.Optional(CONF_WEEKDAYS): _select([str(d) for d in range(7)], "weekday", multiple=True),
                vol.Optional(CONF_INTERVAL, default=2): _num(1, 365),
                vol.Optional(CONF_MONTH_DAY, default=1): _num(1, 31),
                vol.Required(CONF_WINDOW_HOURS, default=0): _num(0, 720),
            }
        return self.async_show_form(step_id="schedule", data_schema=self._schema(fields), errors=errors)

    async def async_step_tags(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._data[CONF_TAGS] = list(user_input.get(CONF_TAGS, []))
            if user_input.get(CONF_LEARN):
                return await self.async_step_learn()
            return await self.async_step_notify()
        selected = list(self._data.get(CONF_TAGS, []))
        schema = self._schema(
            {
                vol.Optional(CONF_TAGS): SelectSelector(
                    SelectSelectorConfig(
                        options=_tag_options(self.hass, selected),
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_LEARN, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="tags", data_schema=schema)

    async def _wait_for_tag(self) -> str | None:
        future: asyncio.Future[str | None] = self.hass.loop.create_future()

        @callback
        def _on_tag(event) -> None:
            if not future.done():
                future.set_result(event.data.get("tag_id"))

        unsub = self.hass.bus.async_listen(EVENT_TAG_SCANNED, _on_tag)
        try:
            async with asyncio.timeout(LEARN_TIMEOUT_SECONDS):
                return await future
        except TimeoutError:
            return None
        finally:
            unsub()

    async def async_step_learn(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Wait for the next tag_scanned event and add that tag to the reminder."""
        if self._learn_task is None:
            self._learn_task = self.hass.async_create_task(self._wait_for_tag())
        if not self._learn_task.done():
            return self.async_show_progress(
                step_id="learn", progress_action="scan", progress_task=self._learn_task
            )
        task, self._learn_task = self._learn_task, None
        tag = task.result()
        if tag:
            self._data[CONF_TAGS] = list(dict.fromkeys([*self._data.get(CONF_TAGS, []), tag]))
        return self.async_show_progress_done(next_step_id="notify")

    async def async_step_notify(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        services = notifier.available_services(self.hass)
        if user_input is not None:
            for key in (CONF_NOTIFY_SERVICES, CONF_ESCALATE_SERVICES):
                names = [notifier.normalise_service(s) for s in user_input.get(key, [])]
                if any(not self.hass.services.has_service("notify", n) for n in names):
                    errors[key] = "unknown_service"
                user_input[key] = names
            for key in (CONF_SNOOZE_MINUTES, CONF_NAG_INTERVAL, CONF_NAG_MAX, CONF_ESCALATE_AFTER):
                if key in user_input:
                    user_input[key] = int(user_input[key])
            has_main = bool(user_input.get(CONF_NOTIFY_SERVICES) or user_input.get(CONF_NOTIFY_ENTITIES))
            has_escalation = bool(user_input.get(CONF_ESCALATE_SERVICES) or user_input.get(CONF_ESCALATE_ENTITIES))
            if has_escalation and not has_main:
                # Escalation targets only join the normal ones, so on their own nothing would ever be sent
                errors[CONF_NOTIFY_SERVICES] = "targets_missing"
            if has_escalation and user_input.get(CONF_ESCALATE_AFTER, 0) < 1:
                errors[CONF_ESCALATE_AFTER] = "escalate_needs_number"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_extras()
        current = {
            CONF_NOTIFY_SERVICES: self._data.get(CONF_NOTIFY_SERVICES, []),
            CONF_ESCALATE_SERVICES: self._data.get(CONF_ESCALATE_SERVICES, []),
        }
        entity_selector = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
        schema = self._schema(
            {
                vol.Optional(CONF_NOTIFY_SERVICES): _select(sorted({*services, *current[CONF_NOTIFY_SERVICES]}), None, True, True),
                vol.Optional(CONF_NOTIFY_ENTITIES): entity_selector,
                vol.Required(CONF_SNOOZE_MINUTES, default=60): _num(1, 1440),
                vol.Required(CONF_NAG_INTERVAL, default=0): _num(0, 1440),
                vol.Required(CONF_NAG_MAX, default=0): _num(0, 50),
                vol.Required(CONF_ESCALATE_AFTER, default=0): _num(0, 50),
                vol.Optional(CONF_ESCALATE_SERVICES): _select(sorted({*services, *current[CONF_ESCALATE_SERVICES]}), None, True, True),
                vol.Optional(CONF_ESCALATE_ENTITIES): entity_selector,
                vol.Optional(CONF_REQUIRE_HOME): EntitySelector(EntitySelectorConfig(domain="person", multiple=True)),
            }
        )
        return self.async_show_form(step_id="notify", data_schema=schema, errors=errors)

    async def async_step_extras(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if bool(user_input.get(CONF_QUIET_START)) != bool(user_input.get(CONF_QUIET_END)):
                errors[CONF_QUIET_END] = "quiet_both"
            else:
                # Optional fields that were cleared must not keep their old value
                for key in (CONF_QUIET_START, CONF_QUIET_END, CONF_ON_DUE, CONF_ON_DONE, CONF_ON_MISSED):
                    self._data.pop(key, None)
                self._data.update(user_input)
                return self._finish()
        script = EntitySelector(EntitySelectorConfig(domain="script"))
        schema = self._schema(
            {
                vol.Required(CONF_EARLY, default=True): BooleanSelector(),
                vol.Optional(CONF_QUIET_START): TimeSelector(),
                vol.Optional(CONF_QUIET_END): TimeSelector(),
                vol.Optional(CONF_ON_DUE): script,
                vol.Optional(CONF_ON_DONE): script,
                vol.Optional(CONF_ON_MISSED): script,
            }
        )
        return self.async_show_form(step_id="extras", data_schema=schema, errors=errors)
