"""Budget governor — defers scheduled work instead of dying at the shared Max wall.

Caps live in DETERMINISTIC code (Loop-Engineering doctrine): no model calls, no API keys.
Two signals: WALL (a limit error names its own reset time) and SELF-METER (the system's
own daily API-value spend from call receipts). State is an APPEND-ONLY event ledger so any
number of detached processes can record concurrently without a JSON-rewrite race. Fail-OPEN
on governor errors: a broken governor must never silently strangle the operator's routines —
burn is cheaper than silence (the operator's policy, spec 3a).

Extracted from a production personal-agent system where this exact logic gates scheduled
work daily. Reference implementation: copy the file, keep the tests."""
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

_DEFAULTS = {"daily_value_usd": 25.0, "wall_slack_min": 10}
_TAIL_LINES = 2000

LIMIT_RE = re.compile(
    r"session limit|usage limit|rate limit|limit reached|limit · resets|temporarily limiting",
    re.I)
_RESET_RE = re.compile(r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*([ap])m", re.I)


def _config(config_path=None):
    # No implicit config location in a standalone pattern: absent config_path means built-in defaults.
    if not config_path:
        return dict(_DEFAULTS)
    try:
        cfg = json.loads(Path(config_path).read_text())
        return {**_DEFAULTS, **cfg} if isinstance(cfg, dict) else dict(_DEFAULTS)
    except Exception:
        return dict(_DEFAULTS)


def matches_limit(text):
    """Is this error text a shared-cap limit signal (vs some other failure)?"""
    return bool(LIMIT_RE.search(text or ""))


def _append(events_path, event):
    try:
        p = Path(events_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"[budget_governor] ledger append failed: {e}", file=sys.stderr)


def _tail_events(events_path):
    try:
        lines = Path(events_path).read_text().splitlines()[-_TAIL_LINES:]
    except Exception:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue      # tolerant: one garbled line must not poison the governor
        if isinstance(e, dict):
            out.append(e)
    return out


def _now_dt(now=None):
    return now if isinstance(now, datetime) else datetime.now()


def record_spend(events_path, cost, source="", now=None):
    """Meter one call receipt. 0/None/garbage cost is a silent no-op. Never raises."""
    try:
        c = float(cost or 0)
    except (TypeError, ValueError):
        return
    if c <= 0:
        return
    _append(events_path, {"ts": _now_dt(now).isoformat(timespec="seconds"), "kind": "spend",
             "cost": round(c, 6), "source": str(source)[:80]})


def record_wall(events_path, reset_hint, now=None, config_path=None):
    """Record a limit hit. The error usually names its reset ('resets 4pm'); if not,
    assume an hour. Cooldown = reset + wall_slack_min. Never raises."""
    now_dt = _now_dt(now)
    cfg = _config(config_path)
    try:
        m = _RESET_RE.search(reset_hint or "")
        if m:
            hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
            until = now_dt.replace(hour=hour, minute=int(m.group(2) or 0),
                                   second=0, microsecond=0)
            if until <= now_dt:
                until += timedelta(days=1)
        else:
            until = now_dt + timedelta(minutes=60)
        try:
            slack = float(cfg.get("wall_slack_min", 10))
        except (TypeError, ValueError):
            slack = 10
        until += timedelta(minutes=slack)
        _append(events_path, {"ts": now_dt.isoformat(timespec="seconds"), "kind": "wall",
                 "until": until.isoformat(timespec="seconds"),
                 "raw": (reset_hint or "")[:120]})
    except Exception as e:
        print(f"[budget_governor] record_wall failed: {e}", file=sys.stderr)


def check(events_path, config_path=None, urgent=False, now=None):
    """(ok, reason). Urgent work always passes. FAIL-OPEN on any internal error."""
    try:
        if urgent:
            return True, "urgent"
        now_dt = _now_dt(now)
        cfg = _config(config_path)
        today = now_dt.date().isoformat()
        spent, latest_wall = 0.0, None
        for e in _tail_events(events_path):
            if e.get("kind") == "spend" and str(e.get("ts", ""))[:10] == today:
                try:
                    spent += float(e.get("cost") or 0)
                except (TypeError, ValueError):
                    pass
            elif e.get("kind") == "wall":
                latest_wall = e.get("until") or latest_wall
        if latest_wall:
            try:
                until = datetime.fromisoformat(latest_wall)
                if now_dt < until:
                    return False, f"wall until {until.strftime('%I:%M%p').lstrip('0').lower()}"
            except ValueError:
                pass
        if spent >= cfg["daily_value_usd"]:
            return False, (f"daily target ${cfg['daily_value_usd']:g} reached "
                           f"(${spent:.2f} spent)")
        return True, "ok"
    except Exception as e:
        print(f"[budget_governor] check failed (fail-open): {e}", file=sys.stderr)
        return True, "governor error (fail-open)"


def should_note(events_path, routine_id, now=None):
    """True once per routine per local day (appends the dedup marker on True).
    Best-effort: a broken ledger returns False — silence beats spam."""
    try:
        today = _now_dt(now).date().isoformat()
        for e in _tail_events(events_path):
            if (e.get("kind") == "defer_note" and e.get("routine") == routine_id
                    and str(e.get("ts", ""))[:10] == today):
                return False
        _append(events_path, {"ts": _now_dt(now).isoformat(timespec="seconds"),
                 "kind": "defer_note", "routine": routine_id})
        return True
    except Exception:
        return False
