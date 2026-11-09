# tapNdo

Tag-based reminders for Home Assistant.

A reminder has a schedule and, if you like, an NFC tag. When it is due, tapNdo notifies any notify target you choose. Touching the tag to any reader, or pressing **Done** on a phone, completes it. Daily vitamin D at 11:00, watering the plants a week after you last did it, changing a filter every 30 days: same thing, different schedule.

tapNdo contains no reader code. It listens to Home Assistant's own `tag_scanned` event, so anything that produces it works: the Home Assistant companion app (phone NFC), ESPHome readers, or a panel such as HearthPanel.

> Status: v0.1, built and tested against Home Assistant 2026.10 in a test harness only. It has not yet been run on a live Home Assistant with a real tag and phone.

## Install

1. Add this repository to HACS as a custom repository (category: Integration), install **tapNdo**, restart Home Assistant.
2. Settings, Devices & services, Add integration, **tapNdo**.
3. On the tapNdo page choose **Add reminder**.

## Reminders

| Setting | Notes |
| --- | --- |
| Schedule type | **Fixed** follows the calendar (every day, chosen weekdays, every N days, monthly). **After last done** comes due a set number of days or weeks after you last did it, so doing it late moves the next one. |
| Time and window | The window is how long it stays due before it counts as missed. 0 means until the end of the day. It never extends past the next occurrence. |
| Tags | Zero or more. *Scan a new tag now* waits 60 seconds for the next tag scan and adds it. One tag can serve several reminders; a tap completes every one that accepts it. |
| Early completion | A tap shortly before the due time counts as done (a quarter of the gap to the next occurrence: 6 hours for a daily reminder). A tap on something you already did is ignored. |
| Notify | Notify services (`notify.mobile_app_...`, `notify.telegram`, ...) and notify entities. Companion app services get **Done** and **Snooze** buttons and the notification is cleared on completion. Other targets get plain text. |
| Nagging and escalation | Repeat every N minutes up to a maximum. From a chosen reminder number on, escalation targets are notified as well. |
| Quiet hours | No notifications in the range. The reminder still changes state. |
| Only when home | Notify only while one of the chosen people is home. |
| Scripts | Run when a reminder becomes due, is done, or is missed. They receive `reminder_id`, `name`, `state` (and `via`, `by`, `where` when done). |

If a reminder is missed, a fixed one moves to the next occurrence. An after-last-done one asks again the next day at the same time instead of waiting another full interval.

## What it creates

* `sensor.<reminder>`: `upcoming`, `due`, `snoozed`, `done` or `missed`, with attributes `next_due`, `window_end`, `last_done`, `streak`, `last_by`, `last_where`, `tags`, `history`.
* `sensor.tapndo_due`: how many reminders are due now. Attribute `items` lists them; `names`, `next_name`, `next_due` and `vacation` are there for dashboards and e-ink displays.
* `calendar.tapndo_schedule`: upcoming due times. `todo.tapndo_due_now`: what is due now; ticking an item completes it.
* `button.<reminder>_done` and `_snooze`, and `switch.tapndo_vacation_mode`, which pauses everything. Nothing is counted as missed while it is on.
* Services on a reminder sensor: `tapndo.complete`, `tapndo.snooze` (optional `minutes`), `tapndo.skip`, `tapndo.reset`.
* Bus events `tapndo_due`, `tapndo_done` (with `via`: `tag`, `phone`, `button`, `service`, `todo`; plus `by` and `where` when known) and `tapndo_missed`.

`where` is the area (or name) of the reader device that fired `tag_scanned`; `by` is the Home Assistant user, when the scan came from the companion app.

## Repairs

tapNdo raises a repair notice when a reminder's tag is no longer in Home Assistant's tag list, or when a notify target does not exist. The reminder keeps working with the other targets and the Done button.

## Limitations

* Action buttons work only for companion app services whose name starts with `mobile_app_`. `notify.send_message` entities carry no buttons.
* Notification texts are English.
* One tapNdo instance per Home Assistant.

## Development

```
docker build -t tapndo-test <a Home Assistant image with pytest-homeassistant-custom-component>
python -m pytest tests -q
```

`tests/test_schedule.py` and `tests/test_engine.py` need no Home Assistant behaviour and cover the schedule maths and state machine, including daylight saving changes.

Licence: MIT.
