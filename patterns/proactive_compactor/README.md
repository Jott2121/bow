# proactive_compactor

**The failure this prevents:** a long-running headless session hits its hard length limit and either stalls the caller for minutes on a blocking flush, or (the design this pattern replaced) tries to summarize itself by resuming the live session in the background, which doesn't fork: the summarization turn lands in the real conversation and quietly pollutes it.
**One receipt:** $0.23 per compaction, a 2,154-char brief rolled from a 1.4MB transcript.

## The idea

The mechanism reads the transcript file straight off disk (`iter_turns`, the parser for Claude Code's session JSONL) instead of ever touching the live session. `needs_compaction()` is a pure trigger rule: start rolling a brief once the transcript passes 60% of your rotation threshold, and refresh it if the transcript grows another 20% past the last snapshot. `build_brief()` hands the previous brief plus the most recent turns to a summarizer callable you supply and gets back `(text, cost)`. `compact()` orchestrates one pass: check an optional budget gate, roll the brief, write it to a cache with exactly one writer, atomically (tmp file + rename, so a crash mid-write never leaves a torn cache).

Why background, off-disk reads instead of resuming the session: see [RESUME-DOES-NOT-FORK.md](RESUME-DOES-NOT-FORK.md) in this directory. A three-call experiment showed that resuming a session id from a "background" process lands in the same conversation, not a fork. Any design that assumes otherwise pollutes the real session with its own summarization chatter.

Every path is fail-soft. If the summarizer throws, or the cache is corrupt, or the budget gate says no, `compact()` returns `False` and does nothing else; it never raises into the caller. That's deliberate: a broken compactor should degrade to the caller's own blocking cliff-flush fallback, not take down the session it was trying to protect.

What stays your job: writing the summarizer (this pattern makes no default model call), wiring a budget gate if you want one, and remembering that a brief is a lossy compression of a long arc, not a database. Durable facts belong in your memory system, not in the brief.

## Use it

The pattern requires a `summarizer` callable: `(prompt) -> (text, cost_usd)`. Here's a reference implementation, one toolless `claude -p` call:

```python
import json
import subprocess

def claude_summarizer(prompt):
    """Reference summarizer: one toolless `claude -p` call. Returns (text, cost_usd)."""
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", "claude-haiku-4-5",
         "--output-format", "json", "--disallowedTools",
         "Bash,Edit,Write,Read,NotebookEdit,WebFetch,WebSearch,Task,Glob,Grep",
         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
         "--setting-sources", "project"],
        capture_output=True, text=True, timeout=120)
    data = json.loads(out.stdout)
    return data.get("result", ""), float(data.get("total_cost_usd", 0))
    # -> ('Handoff brief for successor session: ...', 0.23)
```

**Composition with the budget governor:** `compact()`'s optional `budget_check` is exactly the shape of `budget_governor.check()`, and the two patterns wire together through the caller, not through an import. `compact()` deliberately discards the cost it gets back from `build_brief()` so it can return a plain bool, so record spend at the point where you actually have the cost: inside your own summarizer wrapper, right after the raw call returns.

```python
import budget_governor as governor
import proactive_compactor as compactor

events = "state/events.jsonl"
cache = "state/handoff-cache.json"

def metered_summarizer(prompt):
    text, cost = claude_summarizer(prompt)
    governor.record_spend(events, cost, source="compactor")
    return text, cost

if compactor.needs_compaction(key, sid, transcript_bytes, rotate_bytes,
                              compactor.load_cache(cache)):
    compactor.compact(
        cache, key, sid, transcript_path, transcript_bytes,
        summarizer=metered_summarizer,
        budget_check=lambda: governor.check(events),
    )
```

## Run the tests

    python3 -m pytest patterns/proactive_compactor/ -q

## Honest limits

- A brief is a lossy summary of a long arc. It's fine as a handoff for continuity; it is not a substitute for a real memory system. Durable facts (decisions, deadlines, commitments) belong there, not in the brief.
- This pattern doesn't meter or gate itself. Metering is the budget governor's job, wired in by you; with no `budget_check`, `compact()` always runs.
- The cache has one writer by convention (your caller's single in-flight thread), not by a lock. Running two compactions concurrently against the same cache file is your responsibility to prevent, not this module's.

## The production story

This exact logic runs in my agent daily. The receipts and the bugs it caught:
[docs/RELIABILITY-WEEK.md](../../docs/RELIABILITY-WEEK.md#4-the-proactive-compactor-and-the-design-that-got-killed-before-it-was-built)
