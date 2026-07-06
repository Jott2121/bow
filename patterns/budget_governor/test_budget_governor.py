"""Governor invariants: urgent always passes; walls parse their own reset time; the
self-meter rolls over at local midnight; a broken ledger fails OPEN; notes dedup per day.
All state goes through tmp paths — the real ledger is never touched by tests."""
import json
from datetime import datetime

import budget_governor as governor


def _dt(s):
    return datetime.fromisoformat(s)


def test_urgent_always_passes(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_wall(lp, "resets 4pm (America/Denver)", now=_dt("2026-07-05T14:00:00"))
    ok, reason = governor.check(lp, urgent=True, now=_dt("2026-07-05T14:05:00"))
    assert ok and reason == "urgent"


def test_wall_defers_until_named_reset_plus_slack(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_wall(lp, "You've hit your session limit · resets 4pm (America/Denver)",
                         now=_dt("2026-07-05T14:00:00"))
    ok, reason = governor.check(lp, now=_dt("2026-07-05T15:59:00"))
    assert not ok and "wall until" in reason
    ok2, _ = governor.check(lp, now=_dt("2026-07-05T16:11:00"))   # 4pm + 10min slack passed
    assert ok2


def test_wall_reset_earlier_today_rolls_to_tomorrow(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_wall(lp, "resets 9am", now=_dt("2026-07-05T22:00:00"))
    ok, _ = governor.check(lp, now=_dt("2026-07-05T23:30:00"))
    assert not ok                                                     # 9am tomorrow, not past


def test_unparseable_wall_hint_defaults_to_an_hour(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_wall(lp, "rate limited, try later", now=_dt("2026-07-05T14:00:00"))
    ok, _ = governor.check(lp, now=_dt("2026-07-05T14:30:00"))
    assert not ok
    ok2, _ = governor.check(lp, now=_dt("2026-07-05T15:15:00"))  # 60min + 10 slack passed
    assert ok2


def test_self_meter_defers_past_daily_target_and_rolls_over(tmp_path):
    lp = tmp_path / "ev.jsonl"
    for _ in range(6):
        governor.record_spend(lp, 5.0, source="loop:x", now=_dt("2026-07-05T10:00:00"))
    ok, reason = governor.check(lp, now=_dt("2026-07-05T12:00:00"))
    assert not ok and "daily target" in reason and "$30.00 spent" in reason
    ok2, _ = governor.check(lp, now=_dt("2026-07-06T08:00:00"))  # fresh day, fresh meter
    assert ok2


def test_spend_ignores_zero_none_and_garbage(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_spend(lp, 0)
    governor.record_spend(lp, None)
    governor.record_spend(lp, "not a number")
    assert not lp.exists() or lp.read_text() == ""


def test_check_fails_open_on_unreadable_ledger(tmp_path, monkeypatch):
    def boom(events_path):
        raise OSError("disk gone")
    monkeypatch.setattr(governor, "_tail_events", boom)
    ok, reason = governor.check(tmp_path / "x", now=_dt("2026-07-05T12:00:00"))
    assert ok and "fail-open" in reason


def test_garbled_ledger_line_is_skipped(tmp_path):
    lp = tmp_path / "ev.jsonl"
    governor.record_spend(lp, 30.0, now=_dt("2026-07-05T10:00:00"))
    lp.write_text(lp.read_text() + "{not json\n")
    ok, _ = governor.check(lp, now=_dt("2026-07-05T11:00:00"))
    assert not ok                                                     # spend still counted


def test_should_note_once_per_routine_per_day(tmp_path):
    lp = tmp_path / "ev.jsonl"
    assert governor.should_note(lp, "r1", now=_dt("2026-07-05T10:00:00"))
    assert not governor.should_note(lp, "r1", now=_dt("2026-07-05T15:00:00"))
    assert governor.should_note(lp, "r2", now=_dt("2026-07-05T15:00:00"))
    assert governor.should_note(lp, "r1", now=_dt("2026-07-06T10:00:00"))


def test_config_overrides_target(tmp_path):
    lp, cp = tmp_path / "ev.jsonl", tmp_path / "governor.json"
    cp.write_text(json.dumps({"daily_value_usd": 2.0}))
    governor.record_spend(lp, 3.0, now=_dt("2026-07-05T10:00:00"))
    ok, _ = governor.check(lp, now=_dt("2026-07-05T11:00:00"), config_path=cp)
    assert not ok


def test_matches_limit():
    assert governor.matches_limit("You've hit your session limit · resets 4pm")
    assert governor.matches_limit("API Error: Server is temporarily limiting requests")
    assert not governor.matches_limit("Prompt is too long")
    assert not governor.matches_limit(None)


def test_record_wall_never_raises_on_freak_inputs(tmp_path, capsys):
    lp = tmp_path / "ev.jsonl"
    governor.record_wall(lp, "resets 4:75pm", now=_dt("2026-07-05T14:00:00"))  # minute>59
    # must not raise; event may be absent, stderr notes the failure
    assert "record_wall failed" in capsys.readouterr().err or lp.exists()


def test_record_wall_tolerates_bad_slack_type(tmp_path):
    lp, cp = tmp_path / "ev.jsonl", tmp_path / "governor.json"
    cp.write_text('{"wall_slack_min": "ten"}')
    governor.record_wall(lp, "resets 4pm", now=_dt("2026-07-05T14:00:00"), config_path=cp)
    assert lp.exists()   # falls back to default slack, event recorded
