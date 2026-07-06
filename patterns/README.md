# Patterns

Three guardrail patterns for headless Claude Code agents that must not die at the usage wall. Each one is stdlib-only, self-contained (no imports from the rest of this repo), and shipped with the real production tests. Clone the file, keep the tests, wire it into your own agent.

| Pattern | The failure it prevents | Receipt |
|---|---|---|
| [budget_governor](budget_governor/) | your agent dies mid-task, or silently blows the day's headroom on background work, when it's running under a shared usage cap | $65 of phantom test spend caught because the governor refused a legitimate run |
| [proactive_compactor](proactive_compactor/) | a long session hits its hard length limit and stalls on a blocking flush, or the "obvious" background-summarize design pollutes the live session because resuming doesn't fork | $0.23 per compaction, a 2,154-char brief from a 1.4MB transcript |
| [escalation_valve](escalation_valve/) | a cheap model grinds on a hard call it should hand up | a receipts ledger instead of a cap; the operator reviews the ledger weekly |

## Quickstart

```bash
git clone https://github.com/Jott2121/bow && cd bow
python3 -m pytest patterns/ -q
```

## Composition

These three patterns are designed to compose through the caller, never through an import between pattern directories. The two pairings that come up in production:

The compactor exists because a three-call experiment killed the obvious design first: [resume does not fork](proactive_compactor/RESUME-DOES-NOT-FORK.md).

```
governor.check(events) ------> budget_check -----> compactor.compact()
compactor's summarizer -------> governor.record_spend(events, cost)
valve.auto(ledger, ...) ------> its own ledger, sitting beside governor's events ledger
```

- **Governor gates the compactor.** `budget_governor.check(events_path)` is exactly the `(ok, reason)` shape that `proactive_compactor.compact()`'s optional `budget_check` callable expects: `budget_check=lambda: governor.check(events_path)`.
- **The compactor's cost feeds the governor's meter.** `build_brief()` returns `(text, cost)`, but `compact()` discards that cost so it can return a plain bool. Record the spend where you actually have the cost value: inside your own summarizer callable, right after the raw model call returns, with `governor.record_spend(events_path, cost, source="compactor")`.

Each pattern's README has the full wiring example.

## Fidelity

These are behavior-preserving extractions from a live production system, not toy rewrites. See [docs/RELIABILITY-WEEK.md](../docs/RELIABILITY-WEEK.md) for the receipts and the bugs that live verification caught after code review and a green test suite both missed them.
