"""State machine: pure Python, no Home Assistant."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.tapndo import engine as eng
from custom_components.tapndo import schedule as sch

TZ = ZoneInfo("Europe/Berlin")


def at(d, hh=0, mm=0, m=11):
    return datetime(2026, m, d, hh, mm, tzinfo=TZ)


def vitamin(**kw):
    return eng.ReminderConfig(
        id="vit", name="Vitamin D", schedule=sch.ScheduleConfig(freq=sch.FREQ_DAILY, at=time(11, 0)), **kw
    )


def plants(**kw):
    return eng.ReminderConfig(
        id="pl",
        name="Water plants",
        schedule=sch.ScheduleConfig(
            kind=sch.KIND_AFTER_DONE, interval=1, unit=sch.UNIT_WEEKS, at=time(10, 0), window_hours=48
        ),
        **kw,
    )


def kinds(events):
    return [e.kind for e in events]


def test_new_reminder_is_upcoming_then_due_at_time():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert rt.due_at == at(9, 11)
    assert eng.state_of(rt) == eng.STATE_UPCOMING
    assert eng.tick(cfg, rt, at(9, 10, 59), TZ) == []
    ev = eng.tick(cfg, rt, at(9, 11), TZ)
    assert kinds(ev) == ["due", "notify"]  # the first notification goes out with the due event
    assert eng.state_of(rt) == eng.STATE_DUE


def test_notify_once_when_no_nagging():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert kinds(eng.tick(cfg, rt, at(9, 11), TZ)) == ["due", "notify"]
    assert eng.tick(cfg, rt, at(9, 11, 1), TZ) == []
    assert eng.tick(cfg, rt, at(9, 12), TZ) == []


def test_nagging_and_escalation():
    cfg = vitamin(nag_interval_min=30, nag_max=3, escalate_after=2)
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    got = []
    for minutes in range(0, 200, 5):
        for e in eng.tick(cfg, rt, at(9, 11) + timedelta(minutes=minutes), TZ):
            if e.kind == "notify":
                got.append((minutes, e.index, e.escalate))
    assert got == [(0, 0, False), (30, 1, False), (60, 2, True), (90, 3, True)]  # initial + 3 nags, then stops


def test_done_moves_to_next_day_and_counts_streak():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    eng.tick(cfg, rt, at(9, 11, 5), TZ)
    ev = eng.complete(cfg, rt, at(9, 11, 10), TZ, via="tag", by="Ash", where="Study")
    assert ev.kind == "done" and not ev.early
    assert rt.due_at == at(10, 11)
    assert eng.state_of(rt) == eng.STATE_DONE
    assert rt.streak == 1 and rt.last_done == at(9, 11, 10)
    assert rt.history[-1]["by"] == "Ash" and rt.history[-1]["where"] == "Study"


def test_second_tap_after_done_is_ignored():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    eng.tick(cfg, rt, at(9, 11, 5), TZ)
    assert eng.complete(cfg, rt, at(9, 11, 10), TZ, via="tag")
    assert eng.complete(cfg, rt, at(9, 11, 11), TZ, via="tag") is None
    assert eng.complete(cfg, rt, at(9, 23, 30), TZ, via="tag") is None  # more than 6 h before tomorrow 11:00
    assert rt.streak == 1


def test_early_tap_counts_within_lead_and_not_before():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert eng.complete(cfg, rt, at(9, 4), TZ, via="tag") is None  # 7 h early
    ev = eng.complete(cfg, rt, at(9, 6), TZ, via="tag")  # 5 h early
    assert ev is not None and ev.early
    assert rt.due_at == at(10, 11)
    assert rt.history[-1]["early"] is True


def test_early_completion_can_be_switched_off():
    cfg = vitamin(early_completion=False)
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert eng.complete(cfg, rt, at(9, 10), TZ, via="tag") is None


def test_missed_at_end_of_day_resets_streak():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(8, 8), TZ)
    eng.tick(cfg, rt, at(8, 11), TZ)
    eng.complete(cfg, rt, at(8, 11, 5), TZ, via="tag")
    assert rt.streak == 1
    eng.tick(cfg, rt, at(9, 11), TZ)
    ev = eng.tick(cfg, rt, at(10, 0), TZ)
    assert "missed" in kinds(ev)
    assert eng.state_of(rt) == eng.STATE_MISSED
    assert rt.streak == 0
    assert rt.due_at == at(10, 11)
    # next day it becomes due again
    assert "due" in kinds(eng.tick(cfg, rt, at(10, 11), TZ))


def test_long_outage_reports_one_missed_with_count():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(1, 8), TZ)
    ev = eng.tick(cfg, rt, at(6, 8), TZ)
    assert kinds(ev) == ["missed"]
    assert ev[0].count == 5  # the 1st..5th
    assert rt.due_at == at(6, 11)


def test_snooze_and_return():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    eng.tick(cfg, rt, at(9, 11), TZ)
    assert eng.snooze(cfg, rt, at(9, 11, 2), minutes=60).kind == "snoozed"
    assert eng.state_of(rt) == eng.STATE_SNOOZED
    assert eng.tick(cfg, rt, at(9, 12), TZ) == []
    ev = eng.tick(cfg, rt, at(9, 12, 2), TZ)
    assert kinds(ev)[0] == "unsnoozed"
    assert eng.state_of(rt) == eng.STATE_DUE


def test_snooze_ignored_when_not_due():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert eng.snooze(cfg, rt, at(9, 9), minutes=10) is None


def test_quiet_hours_delay_notifications():
    cfg = vitamin(quiet_start=time(10, 0), quiet_end=time(12, 0))
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert kinds(eng.tick(cfg, rt, at(9, 11), TZ)) == ["due"]  # state changes, but no notification yet
    assert eng.state_of(rt) == eng.STATE_DUE
    assert eng.tick(cfg, rt, at(9, 11, 30), TZ) == []
    assert kinds(eng.tick(cfg, rt, at(9, 12), TZ)) == ["notify"]


def test_after_done_schedule_follows_the_person():
    cfg = plants()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    assert rt.due_at == at(9, 10)
    eng.tick(cfg, rt, at(9, 10), TZ)
    # watered a day late relative to nothing: done on the 11th, next due is the 18th
    eng.complete(cfg, rt, at(11, 15), TZ, via="tag")
    assert rt.due_at == at(18, 10)
    assert rt.window_end_at == at(20, 10)


def test_after_done_missed_asks_again_tomorrow_not_after_a_week():
    cfg = plants()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    eng.tick(cfg, rt, at(9, 10), TZ)
    ev = eng.tick(cfg, rt, at(11, 10), TZ)  # 48 h window over
    assert "missed" in kinds(ev)
    assert rt.due_at == at(12, 10)


def test_skip_moves_on_without_streak_change():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    rt.streak = 4
    eng.skip(cfg, rt, at(9, 9), TZ)
    assert rt.due_at == at(10, 11) and rt.streak == 4
    assert rt.history[-1]["result"] == "skipped"


def test_vacation_resume_shifts_after_done_and_skips_fixed():
    cfg = plants()
    rt = eng.init_runtime(cfg, at(9, 8), TZ)  # due the 9th 10:00
    eng.resume(cfg, rt, at(16, 8), TZ, paused_for=timedelta(days=7))
    assert rt.due_at == at(16, 10)

    cfg2 = vitamin()
    rt2 = eng.init_runtime(cfg2, at(9, 8), TZ)
    eng.resume(cfg2, rt2, at(16, 8), TZ, paused_for=timedelta(days=7))
    assert rt2.due_at == at(16, 11)
    assert rt2.last_result is None  # nothing counted as missed


def test_runtime_roundtrip():
    cfg = vitamin(nag_interval_min=10, nag_max=2)
    rt = eng.init_runtime(cfg, at(9, 8), TZ)
    eng.tick(cfg, rt, at(9, 11), TZ)
    eng.complete(cfg, rt, at(9, 11, 5), TZ, via="button")
    again = eng.Runtime.from_dict(rt.to_dict())
    assert again.to_dict() == rt.to_dict()
    assert again.due_at == rt.due_at and again.last_done == rt.last_done


def test_history_is_capped():
    cfg = vitamin()
    rt = eng.init_runtime(cfg, at(1, 8), TZ)
    for _ in range(80):
        eng.skip(cfg, rt, at(1, 9), TZ)
    assert len(rt.history) == eng.HISTORY_LIMIT
