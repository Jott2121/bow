# escalation_valve

**The failure this prevents:** a cheaper model grinds on a call that's expensive to get wrong and cheap to double-check (an architecture fork, a bug that survived one fix attempt already, a plan you're not fully sold on) and either commits to a bad call or stalls trying to reason its own way past a decision it should hand up.
**One receipt:** a receipts ledger instead of a cap; the operator reviews the ledger weekly.

## The idea

The mechanism is one toolless consult: a subprocess call to a stronger model with no tools available to it and a hard timeout, so a consult costs pennies of headroom and can never itself take an action. The prompt asks for a decisive judgment plus the key reasoning plus what evidence would change its mind, capped under 400 words, so you get an answer you can act on instead of a hedge.

The interesting design choice is what doesn't gate it: there's no hard cap on how often the valve fires. `auto()` appends every automatic consult to a JSONL ledger (timestamp, surface, trigger, a truncated question, the outcome) instead of pre-guessing a number and hardcoding a limit that's either too tight to be useful or too loose to matter. The plan is to read that ledger periodically rather than throttle the valve.

Fail-soft is load-bearing on both halves. If the consult itself fails (timeout, no binary, a bad model name), `run()` returns `None` and never raises: a dead valve must never crash the session that pulled it. If the ledger write fails, `auto()` still returns the answer: a dead ledger must not block the consult it's supposed to be logging.

What stays your job: deciding where the trigger points are (a repeated failure, a stalled loop, a flagged build), naming the model, and reading the ledger. The valve doesn't pick a model for you and doesn't have a built-in default; a consult is only as good as the question you inline into it, so trimming that question to the real decision, not the whole transcript, is on you too.

## Use it

```python
import escalation_valve as valve

# name your strongest available tier: there is no built-in default
STRONG_MODEL = "claude-opus-4-8"

answer = valve.run(
    "Two designs for X: A resumes the session, B reads the transcript off disk. "
    "Which one, and what breaks the other?",
    model=STRONG_MODEL,
    effort="high",   # optional: raises reasoning depth on models that support it
)

# or, for an automatic consult that also writes a ledger receipt:
answer = valve.auto(
    "state/valve-ledger.jsonl",
    question="loop stalled after 3 retries, what now?",
    surface="build-runner",
    trigger="stall",
    model=STRONG_MODEL,
)
# -> ledger line: {"ts": ..., "outcome": "answered"}
```

`model` is required and first: name the strongest tier you actually have access to. `effort` is optional and only does anything on models that support a reasoning-effort parameter.

## Run the tests

    python3 -m pytest patterns/escalation_valve/ -q

## Honest limits

- A consult is only as good as the question you inline. It has no access to your codebase, your history, or any tool; if the question doesn't carry the context, the answer won't either.
- There's no cap, by design, which means the ledger discipline (someone actually reading it) is doing the job a cap would otherwise do. Skip that discipline and the valve becomes an unmetered cost center.
- It never takes an action. It gives you a judgment; wiring that judgment back into a decision is still the caller's job.

## The production story

This exact logic runs in my agent daily. The receipts and the bugs it caught:
[docs/RELIABILITY-WEEK.md](../../docs/RELIABILITY-WEEK.md#2-the-escalation-valve)
