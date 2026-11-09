"""To-do list of the reminders that are due. Ticking an item completes the reminder."""

from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TapndoConfigEntry
from .const import DOMAIN, VIA_TODO
from .entity import GlobalEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: TapndoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([TapndoTodo(entry.runtime_data)])


class TapndoTodo(GlobalEntity, TodoListEntity):
    _attr_translation_key = "due_list"
    _attr_icon = "mdi:format-list-checks"
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._attr_unique_id = f"{manager.entry.entry_id}_todo"

    @property
    def todo_items(self) -> list[TodoItem]:
        return [
            TodoItem(
                uid=item["id"],
                summary=item["name"] + (" (snoozed)" if item["snoozed"] else ""),
                status=TodoItemStatus.NEEDS_ACTION,
                due=self.manager.reminders[item["id"]].rt.due_at,
            )
            for item in self.manager.due_items()
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid not in self.manager.reminders:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_reminder")
        if item.status == TodoItemStatus.COMPLETED:
            await self.manager.async_complete(item.uid, VIA_TODO)
