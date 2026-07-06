# budget_governor

**The failure this prevents:** a scheduled agent running under a flat-rate usage cap either dies mid-task with no explanation when the cap runs dry, or burns the whole day's headroom on background work before anything urgent gets a turn.
**One receipt:** $65 of phantom test spend caught because the governor refused a legitimate run.

## The idea

Two signals decide whether work goes ahead. The WALL signal comes from the provider's own rate-limit error: when a call gets blocked, the error text usually names when the limit clears ("resets 4pm"), so the governor parses that timestamp instead of guessing a cooldown window, adds a slack buffer, and only falls back to a conservative fixed window if the text doesn't parse the way it's supposed to. The SELF-METER signal is independent of the wall: every call you choose to record accumulates against a soft daily target, so a single expensive day gets caught before it ever needs the hard wall to notice.

State is one append-only event ledger (a JSONL file), not a JSON blob that gets rewritten. That's the concurrency story: any number of detached processes can append a spend or wall event at the same time with no lock and no torn-write race. Reads tail the last 2000 lines and tolerate one garbled line without poisoning the whole check.

The doctrine is fail-open, on purpose. If the governor's own logic throws, `check()` still returns `True`. Burn is cheaper than silence: a system that goes quiet to protect a budget has failed at its actual job. Urgent work bypasses the gate entirely, by the caller passing `urgent=True`, not by the governor guessing what's important.

What stays your job: deciding what "urgent" means for your caller, actually calling `record_spend()` after real calls (the self-meter only sees what you record into it), and setting a `daily_value_usd` that fits your own cap.

## Use it

```python
import budget_governor as governor

events = "state/events.jsonl"

ok, reason = governor.check(events, urgent=False)
# -> (False, 'wall until 4:10pm')
if not ok:
    print(f"deferred: {reason}")
else:
    # ... do the work, then meter it
    governor.record_spend(events, cost=0.14, source="daily-digest")

# when a call comes back rate-limited, record the reset hint verbatim
# governor.record_wall(events, "session limit reached, resets 4pm")
```

Every function takes `events_path` first, and it's a required argument: there's no implicit state directory in a standalone pattern. Point it at whatever file your caller owns.

## Run the tests

    python3 -m pytest patterns/budget_governor/ -q

## Honest limits

- The self-meter only sees what you record into it. Spend you never call `record_spend()` on is invisible to the daily target, deliberately, in the fail-open direction.
- A single heavy day of interactive use alone can push the daily meter past target and defer routine work for that day. That's intended chat-protection behavior, not a bug, but it's worth knowing before it surprises you.
- The wall-reset parser matches a specific shape of reset text (`resets 4pm`, `resets 4:30pm`). Text outside that shape falls back to a flat 60-minute cooldown, which is conservative but not exact.

## The production story

This exact logic runs in my agent daily. The receipts and the bugs it caught:
[docs/RELIABILITY-WEEK.md](../../docs/RELIABILITY-WEEK.md#3-the-budget-governor-living-inside-a-shared-cap-not-a-wallet)
