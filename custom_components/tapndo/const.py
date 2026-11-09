"""Constants for tapNdo."""

from __future__ import annotations

DOMAIN = "tapndo"
SUBENTRY_REMINDER = "reminder"

# Settings of one reminder (stored in its config sub-entry)
CONF_NAME = "name"
CONF_KIND = "kind"
CONF_FREQ = "freq"
CONF_TIME = "time"
CONF_WEEKDAYS = "weekdays"
CONF_INTERVAL = "interval"
CONF_UNIT = "unit"
CONF_MONTH_DAY = "month_day"
CONF_ANCHOR = "anchor"
CONF_WINDOW_HOURS = "window_hours"
CONF_TAGS = "tags"
CONF_LEARN = "learn"
CONF_EARLY = "early_completion"
CONF_NOTIFY_SERVICES = "notify_services"
CONF_NOTIFY_ENTITIES = "notify_entities"
CONF_SNOOZE_MINUTES = "snooze_minutes"
CONF_NAG_INTERVAL = "nag_interval"
CONF_NAG_MAX = "nag_max"
CONF_ESCALATE_AFTER = "escalate_after"
CONF_ESCALATE_SERVICES = "escalate_services"
CONF_ESCALATE_ENTITIES = "escalate_entities"
CONF_REQUIRE_HOME = "require_home"
CONF_QUIET_START = "quiet_start"
CONF_QUIET_END = "quiet_end"
CONF_ON_DUE = "on_due"
CONF_ON_DONE = "on_done"
CONF_ON_MISSED = "on_missed"

# Events on the Home Assistant bus
EVENT_DUE = "tapndo_due"
EVENT_DONE = "tapndo_done"
EVENT_MISSED = "tapndo_missed"

# Events tapNdo listens to
EVENT_TAG_SCANNED = "tag_scanned"
EVENT_MOBILE_ACTION = "mobile_app_notification_action"

ACTION_DONE_PREFIX = "TAPNDO_DONE_"
ACTION_SNOOZE_PREFIX = "TAPNDO_SNOOZE_"

# How completions arrive
VIA_TAG = "tag"
VIA_BUTTON = "button"
VIA_SERVICE = "service"
VIA_TODO = "todo"
VIA_PHONE = "phone"

TICK_SECONDS = 20
LEARN_TIMEOUT_SECONDS = 60
STORE_VERSION = 1
