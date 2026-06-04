# Bow

**An all-Claude (Opus 4.8) chief-of-staff agent I architected, built, and run — reachable from my phone, at ≈ $0/mo marginal cost.**

`16 modules` · `1,025 LOC code + 1,339 LOC tests` · `101 tests` · `6 milestones shipped` · `~$0/mo`

> A single always-on daemon wraps the headless `claude -p` CLI as first-party usage, routes my phone messages, runs autonomous builds, fires scheduled routines, and self-heals — built and adversarially reviewed by fleets of Claude subagents I directed and gated.

This repo is a sanitized engineering case study, not a runnable clone. The proof is the architecture, an original orchestration doctrine, real annotated code, the build process, and honest receipts. Tone throughout: receipts over hype.

**The one thing to take away:** this is an AI-built system where my value-add is the *orchestration doctrine and the gates* — not the typing. I architected it, then directed and gated fleets of Claude (Opus 4.8) subagents to implement and adversarially review every piece. The gates earned their keep with real bugs caught, not assertions — the sharpest single instance: an independent QC pass caught a malformed-routine field that could **soft-lock the entire daemon** (routine dispatch ran before the message poll, so one bad routine raising an exception froze the phone channel too), a failure the happy-path unit tests never saw. Directing agent fleets to ship *correct* work, with the gates proving it, is the competency on display. The cost bet below is the architecture decision that makes it cheap; the orchestration is the skill.

---

## 1. What it is (30 seconds)

I run an earlier multi-provider personal agent. It died on auth — `HTTP 400: "You're out of extra usage"` — because a flat-rate subscription credential can't legally serve a *third-party* agent's API traffic; that traffic gets metered, and when the balance hits zero, the agent stops. The only honest fix inside that design is a real metered API key, and for a do-everything assistant that runs all day, that is real money every month.

So I rebuilt it on a different bet:

> **Don't call the API — be the tool.**

Instead of an agent that makes metered third-party API calls, Bow *is* a first-party Claude Code user. The whole system is a thin, disciplined wrapper around the headless `claude -p` CLI. The brain is a persistent `claude -p --resume` session, so it inherits my real skills, memory, MCP servers, and tools for free — no rebuild — and bills under the flat-rate plan I already pay for instead of a separate metered key. One AI (Claude, Opus 4.8), not a two-provider stack.

Bow runs two real workloads in production: a daily scheduled quantitative job and a personal knowledge base. Both are described generically on purpose — the point is the architecture, not the payloads.

As above, the agents built it under my direction and my gates, under a doctrine I'd already shipped as a skill — **Fleet Mode** (section 3). Bow is an all-Claude system; the cost bet is *what* it's built on, the orchestration is *how* it was built correctly.

---

## 2. Architecture

A single tick loop is the only event source. The build path crosses a process boundary through one file with one writer. Liveness is judged by an independent watchdog rather than self-reported.

```mermaid
flowchart TD
    phone["📱 Phone (Telegram)"]
    lp["Telegram long-poll"]
    daemon["Daemon (single tick loop)"]
    disp["Dispatcher (classify + allowlist)"]
    brain["Persistent brain session<br/>(claude -p --resume, self-heal)"]
    build["Detached build runner<br/>(single writer)"]
    result["Result file"]
    sched["Scheduler tick — due()"]
    routines["Due routines fire"]
    wd["Watchdog"]
    hb["Heartbeat timestamp"]

    phone -->|message / voice note| lp
    lp --> daemon
    daemon --> disp

    disp -->|chat turn| brain
    brain -->|answer| daemon

    disp -->|/build| build
    build -->|writes once| result
    result -->|daemon polls + reads| daemon

    daemon -->|reply| phone

    daemon --> sched
    sched -->|due == true| routines
    routines -->|push| phone

    daemon -->|every tick| hb
    wd -->|reads on interval| hb
    wd -->|stale → restart / alert| phone
```

Full component responsibilities, the data flow, and the four hard decisions that actually cost me time are in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## 3. ⭐ Fleet Mode — the orchestration doctrine

This is the top-billed part. Fleet Mode is the small set of rules I converged on for running fleets of Claude (Opus 4.8) subagents that earn their keep instead of burning spend on theater. It runs as a live Claude Code skill on the machine that builds Bow, so every headless build auto-applies it.

The load-bearing fact of the entire doctrine, measured in my own runs (not a borrowed benchmark):

> **Default to a single agent. Adding agents has a negative average payoff across tasks; fan out only for read-heavy parallel work that demonstrably earns it.**

The four sub-rules, in short:

1. **Read-heavy work fans out.** Fan-out is for *reading* — research across many sources, auditing a codebase — where each subagent explores in a clean context and returns a tight, condensed summary. Not for acting.
2. **Writes stay single-threaded.** One agent makes the edit, always. Extra agents add *intelligence* to a write (review it, pressure it), never *parallel actions*. Parallel writers race and clobber.
3. **Deterministic machine checks first, then an independent refute-first reviewer.** Tests, types, lint, and re-derived numbers run before any model looks at the work. Only then does a reviewer in a separate clean context try to *break* it. No agent grades its own homework. The gate fails closed.
4. **Default-to-no, anchored on the negative-average finding.** Every reach for another agent puts the burden of proof on the agent. The task has to *demonstrably* earn the fan-out or it doesn't get it.

There's an honest provenance beat in the full doc: after I had Fleet Mode running as my default, the labs shipped essentially the same idea ("ultracode"). I'm not claiming I invented something they copied — I'm claiming I arrived at it independently, from the same pressure, before it had a product name. When you operate agent fleets seriously and adversarially, you converge on the rules the work actually rewards.

Full treatment: **[docs/FLEET-MODE.md](docs/FLEET-MODE.md)**.

---

## 4. Components & key decisions

| Component | Its one job | The non-obvious call |
|---|---|---|
| **Daemon + long-poll** | The single always-on loop: pull messages, route, tick the scheduler, emit a heartbeat. | The long-poll loop is the *only* event source. Everything funnels through one tick, so there is exactly one thread of control to reason about — and the tick must never block. |
| **Dispatcher** | Classify each inbound message and hand it to the right path. | Commands are gated by a chat allowlist, not the model's judgment. In a single-user threat model the allowlist is the load-bearing security boundary, enforced deterministically before the model is invoked. |
| **Detached single-writer build runner** | Run an autonomous headless build to completion out-of-band, then report back. | A build is spawned **detached** (it outlives the tick) and is the **sole writer** of its own result file; the daemon only reads. One writer per file means no torn-write race. → [`snippets/single_writer_dispatcher.py`](snippets/single_writer_dispatcher.py) |
| **Scheduler `due()`** | Decide which routines fire this tick (cron, interval, or daily time-of-day + weekday). | The whole fire/don't-fire decision is a **pure function** — no clock reads, no I/O — so every edge case is unit-testable. Interval and daily routines catch up after the machine sleeps (`due()` re-evaluates on wake); cron fires only within its matching minute by design, so a 9:30 cron job slept through is intentionally not back-fired at 10:15. → [`snippets/scheduler_due.py`](snippets/scheduler_due.py) |
| **Watchdog + heartbeat** | Detect a silent daemon death and self-restart / alert, independent of the daemon. | Liveness is decided by an outside observer, not self-reported — a hung daemon can't honestly report it's healthy. |
| **Brain / persistent session** | One durable conversation with continuity across restarts. | Continuity is the persisted `--resume` session id; a dead session **self-heals** into a fresh one instead of erroring at whoever's texting. Wrapping real `claude -p` means it inherits skills, memory, and tools for free. → [`snippets/session_self_heal.py`](snippets/session_self_heal.py) |

Three of the four hard decisions were macOS-specific and only surfaced under `launchd`: relocating the working tree off a TCC-protected home directory, using launchd wrapper scripts instead of `EnvironmentVariables`, and the fact that headless `claude -p` authenticates where an interactive keychain unlock fails. Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 5. Reliability & security

Each guard exists because the adversarial QC pass found the failure it prevents — not because I anticipated it on the happy path.

- **Watchdog / heartbeat self-restart.** The daemon writes a heartbeat every tick; a separate watchdog restarts it if that goes stale. (An early version crashed on a *missing* heartbeat by computing `int(inf)` — the adversarial review caught it before it shipped.)
- **Session self-heal.** A dead `--resume` session id falls back to a fresh session instead of surfacing a raw "no conversation found" error to the phone. → [`snippets/session_self_heal.py`](snippets/session_self_heal.py)
- **The single-writer race avoided.** Two processes writing one shared JSON file with no lock is a torn write waiting to happen — intermittent, data-dependent, invisible until production. I refused to ship it: each build is the sole writer of its own result file, the daemon is a pure reader. → [`snippets/single_writer_dispatcher.py`](snippets/single_writer_dispatcher.py)
- **A path-traversal hole, found and closed.** The independent security review flagged an unsanitized inbound path; it was closed before anything went live.
- **Routine isolation.** Routine dispatch ran *before* the message fetch each tick, so one malformed routine raising an exception soft-locked the *entire* daemon, every tick, freezing the phone channel too. Now each routine is isolated in its own try/except and `due()` reads its fields defensively. → [`snippets/daemon_resilience.py`](snippets/daemon_resilience.py)
- **No live vulnerabilities** for the single-user threat model after the review and fixes — zero critical findings remaining.
- **`bypassPermissions` is a documented, gated, accepted risk.** Queued builds run with permissions bypassed (the security review rated this HIGH). I did *not* silently ship it: the chat allowlist is the load-bearing gate, a sandbox is a deferred item, and the trade-off is written down. An honest "accepted risk, here's the mitigation" beats a hidden one.

---

## 6. Engineering process

Spec → plan → subagent-driven build → **independent adversarial QC** → security review → 101 tests → reversible production cutover. Every milestone passed a deterministic check (tests, a live invocation) *and* a separate refute-first review before I let myself write "shipped."

![pytest: 101 passed](assets/receipt-tests.png)

*The deterministic gate — the full suite green. Raw `pytest` output, not a summary.*

Most of this landed inside one focused session — which is mechanically unremarkable once you see how: fleets of Claude subagents did the implementation in parallel, under my direction and my gates. I wasn't typing 1,025 lines by hand; I was classifying stakes, fanning out read-heavy work, keeping writes single-threaded, and refusing to let any milestone past a deterministic check and an independent refute-first review. The compression came from the orchestration plus the discipline of the gates — and where I cut a corner, the review caught it and I logged it.

The capstone was a 37-agent adversarial review across six dimensions (correctness, concurrency, reliability, resource leaks, operational safety, edge cases): 30 raw findings → each adversarially verified → 13 confirmed → 7 deduped (1 high, 6 medium, 0 critical), all fixed with new regression tests. That fan-out was justified *because* it was read-heavy, parallelizable review on a system about to take a live job — exactly the narrow case the doctrine fans out for. Most tasks don't earn it.

![Adversarial QC receipt — the soft-lock catch](assets/receipt-qc-catch.png)

*A hand-formatted summary of the real adversarial QC run — see the note in §8 on keeping stylized summaries and raw evidence visibly distinct.*

The full chronological story, scrubbed, with the QC catch that mattered at each milestone: **[docs/BUILD-LOG.md](docs/BUILD-LOG.md)**.

---

## 7. Honest scorecard

The ❌s are intact. Several prior-agent features were cut **by choice** — they were bloat I never used, and several conflict with the one-AI bet.

| Goal | Status | Note |
|---|---|---|
| Cheaper than a metered API agent | ✅ | ≈ $0/mo over the flat-rate plan; no metered key in the loop. |
| Reachable from anywhere | ✅ | Answers from my phone; proactive push works. |
| All-Claude (Opus 4.8), one-AI stack | ✅ | No two-provider fallback. |
| Autonomous build dispatch | ✅ | Message a build request → headless build runs → reports back. |
| Scheduler (cron / interval / daily) | ✅ | Pure `due()`; interval/daily catch up after sleep, cron fires within its matching minute by design. |
| Files + voice | ✅ | Two-way transfer; local whisper.cpp transcription, no cloud. |
| Live production cutover | ✅ | Absorbed a live scheduled job via an atomic, reversible cutover. |
| Multi-channel chat relays | ❌ | Cut by choice — unused bloat. |
| OpenAI-compat / multi-provider proxy | ❌ | Cut by choice — conflicts with the one-AI bet. |
| Dashboard / GUI | ❌ | Cut by choice — the phone is the interface. |
| Build sandbox | ❌ | Deferred; accepted risk documented, allowlist is the gate. |

**What I'd do differently / limitations.** The biggest open item is the build sandbox: queued builds run with elevated permissions and the only enforced boundary is the chat allowlist — fine for a single-user system, not fine if this ever grew multi-user. The in-daemon scheduler tick is simple and self-healing but couples scheduling to daemon liveness; a separate scheduler process would be more robust at the cost of more moving parts. And it is single-user and single-host by design — nothing here is built for a team or for horizontal scale, because nothing here needed to be.

---

## 8. What this demonstrates

Transferable signal for an AI-builder reader:

- **Systems design under real constraints** — auth, cost, macOS TCC, concurrency, reliability, all solved against the wall, not on a whiteboard.
- **An AI-native SDLC** — spec → plan → subagent build → independent adversarial QC → security review → tests → reversible production cutover. Most candidates can't show a *process*.
- **An original orchestration doctrine (Fleet Mode)** that generalizes how to run agent fleets — directly transferable to anyone building agentic products.
- **Build-vs-buy / cost judgment** — collapsed a multi-tool, multi-provider stack to one AI at ≈ $0 marginal cost over an existing plan.
- **Honest engineering communication** — a scorecard with explicit ❌s and a real limitations section.
- **Shipped and operated** — it runs daily and absorbed a live job via an atomic, reversible cutover. A redacted tail of the live daemon log, with real ISO timestamps showing a routine firing and the watchdog confirming the heartbeat, is in [`assets/daemon-log-excerpt.txt`](assets/daemon-log-excerpt.txt).

> A note on the artifacts in `assets/`: the pytest output and the daemon log excerpt are raw tool output (only secrets/ids/paths redacted). The FLEET MODE and QC "receipts" are hand-formatted *summaries* of real runs — clearly stylized, not raw console capture — so you can read the outcome at a glance. I keep the two visibly distinct on purpose; conflating a formatted summary with raw evidence is exactly the kind of thing this repo is trying not to do. Raw: [`receipt-tests`](assets/receipt-tests.txt), [`daemon-log-excerpt`](assets/daemon-log-excerpt.txt). Formatted summaries: [`receipt-fleet-mode`](assets/receipt-fleet-mode.txt), [`receipt-qc-catch`](assets/receipt-qc-catch.txt).

---

## 9. Cost

> ≈ $0/mo over an existing flat-rate plan, vs. metered API pricing that is nonzero and recurring forever for an equivalent do-everything agent.

The build-vs-buy reasoning is the whole architecture in one line: a do-everything agent built on a metered API key costs real money every month, forever, *on top of* a flat-rate plan I already pay for. The exact metered figure depends on traffic, so I won't dress a guess as analysis — the load-bearing point is the *shape*: a recurring monthly bill that scales with use, versus ≈ $0 marginal. As one worked anchor: a do-everything assistant running all day at even ~1M Opus-4.8 tokens/day of mixed input/output lands in the low tens of dollars a month at current metered rates and climbs from there with heavier build traffic — recurring, forever. By being a first-party Claude Code user rather than a third-party API caller, Bow puts every chat turn and every build under the plan I already have — and inherits skills, memory, MCP servers, and tools for free instead of rebuilding two-thirds of the old system. That is why the marginal cost is ≈ $0 and why two-thirds of the old feature list was never rebuilt: it wasn't needed.

---

## 10. In closing

**Full private repo and the test suite available on request.**

I architected this system, made the central bet (*be the tool, don't call the API*), and then directed and gated fleets of Claude (Opus 4.8) subagents to implement and adversarially review it — under the Fleet Mode doctrine, which runs as a live skill so the orchestration is operational, not an essay. The gates caught real bugs every single time; the soft-lock catch in section 5 is the proof that the orchestration-under-gates earns its keep.
