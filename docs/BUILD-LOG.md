# Bow — Build Log

A dated, evidence-first record of building **Bow**: an all-Claude (Opus 4.8) chief-of-staff I can
reach from my phone, that I built to replace an earlier multi-provider agent of mine at near-zero
marginal cost. One entry per milestone. The point of this log is receipts, not narration — every
claim below traces to a test count, a live run, or a bug the review pass caught.

A note on the timeline up front, because it's the thing people misread: most of this shipped inside
one focused session. The mechanism is the explanation — fleets of Claude subagents did the
implementation in parallel under my direction and my gates, so "one session" for a 1,025-LOC system
with 101 tests is unremarkable once you account for who was doing the typing. What made it *land*
rather than just land fast: every milestone below has a deterministic check (tests, a live
invocation) and an independent adversarial review *before* I let myself write "shipped." Where I cut
a corner, the review caught it, and I logged it.

---

## The wall — why this started

The earlier agent died on auth. The failure was an `HTTP 400: "You're out of extra usage"`.

Root cause was architectural, not a quota I forgot to top up: a flat-rate subscription credential
can't legally serve a *third-party* agent's API traffic. That traffic gets shunted to metered
pay-as-you-go "extra usage," and when that balance is zero, the agent simply stops. The only honest
fix inside that design is to put the agent on a real metered API key — and for a do-everything
assistant that runs all day, that is real money:

> **≈ $0/mo over an existing flat-rate plan, vs. metered API pricing that is nonzero and recurring
> forever for an equivalent do-everything agent.** (Worked anchor: an all-day assistant at even
> ~1M Opus-4.8 tokens/day of mixed traffic runs into the low tens of dollars a month at current
> metered rates, and climbs from there with heavier build use. The point is the *shape* — a
> recurring bill that scales with use — not a precise figure I can't pin without knowing the load.)

So the wall was: keep paying a flat rate I already pay *and* pay metered API on top, forever, to run
a worse-architected version of tools I already had access to.

---

## The bet — be the tool, don't call the API

The insight that unlocked everything: **don't call the API — be the tool.**

Instead of building an agent that makes third-party API calls (metered, and the thing that hit the
wall), I rebuilt the parts I actually used as **first-party Claude Code**, wrapping the headless
`claude -p` CLI as ordinary first-party usage under the flat-rate plan I already have. One AI
(Claude, Opus 4.8), not a two-provider stack.

What that bet bought, mechanically:

- **The brain is a persistent `claude -p --resume` session.** It inherits my real skills, memory,
  MCP servers, web/browser access, and session continuity *for free* — no rebuild of two-thirds of
  the old system, because it isn't a clone of Claude Code, it *is* Claude Code, driven headlessly.
- **Heavy builds run as real Claude Code sessions** I can spawn in parallel and attach to from my
  phone.
- **Marginal cost ≈ $0** over the plan I already pay for, because there is no separate metered key
  in the loop. That was the entire point.

I deliberately did **not** rebuild everything the old agent did. A pile of extra chat-channel
relays, a multi-provider fallback, an OpenAI-compat proxy, a dashboard/GUI, webhooks, a kanban — all
cut by choice. They were bloat I never used, and several of them conflict with the one-AI bet. The
honest scorecard keeps those ❌s visible; I'm not going to pretend I shipped features I chose to drop.

**Method note — how this whole repo was built.** I architected, directed, and *gated* fleets of
Claude subagents to implement and adversarially review this system, under an orchestration doctrine
I'd already shipped as a skill (**Fleet Mode**). That orchestration is the work. The rule that does
the most load-bearing duty — and it's a finding from my own runs, not a borrowed benchmark:

> **Default to a single agent. Adding agents has a negative average payoff across tasks; fan out
> only for read-heavy parallel work that demonstrably earns it.**

So "fleets of agents" never means "more agents = better." It means: classify the stakes, fan out
*only* for read-heavy parallel work, keep all writes single-threaded, and never let an agent grade
its own work — a separate clean-context reviewer has to try to *refute* it before anything ships.

---

## M0 — de-risk before building

Before writing build code I ran the two gating spikes live, because the whole bet rests on two
assumptions and I wanted them proven, not hoped.

**Brain / session persistence — full pass.** Headless `claude -p` authenticated from a clean
directory as Opus 4.8, returned the `{result, session_id}` contract, and `--resume` recalled a
codeword across two separate invocations (same session confirmed). The brain path was proven
end-to-end before a line of integration code existed.

**Build dispatcher — mechanical pass.** Drove a detached Claude session via `tmux send-keys` and
captured three real implementation details for the dispatcher: launch the absolute binary (the bare
name is a shell function, not an executable), auto-confirm the folder-trust prompt, and submit with
a separate Enter. One open item flagged for later: interactive-TUI auth was keychain-locked in the
sandbox context — headless `-p` worked, so I noted it as the dispatcher's first gate rather than
papering over it.

**The QC catch that mattered:** the keychain-lock finding. Carrying that forward honestly (instead
of assuming interactive mode would "probably work") is what made M3 land cleanly instead of
discovering it the hard way mid-build.

Net: foundation GO. Verify-before-build held — no code written on an unproven assumption.

---

## M1 + M2 — Bow is live on my phone

Bow became reachable, answering, and proactive. Built subagent-driven: a fresh implementer per
task plus a spec/quality review with a fix loop, then an adversarial final review before I'd call it
done.

Receipts:

- **23/23 tests pass.** The daemon runs under `launchd` (KeepAlive, auto-restart), long-polling for
  messages. I sent it a question from my phone and got back a real Opus-4.8 answer.
- **Proactive push works** — the daemon can message my phone unprompted; a heartbeat + watchdog
  (every 300s) alerts me if Bow ever goes silent.
- **Cost: ≈ $0** over the existing flat-rate plan (first-party `claude -p`, no API key — the whole
  point).

**The QC catches that mattered** — three real bugs caught and fixed *before* I declared done. This
is the entire reason the review pass exists:

1. **Watchdog crashed on a missing heartbeat** (`int(inf)` overflow). The adversarial final
   reviewer found a latent bug I had written into the *plan itself*. Fixed and tested.
2. **`~/Documents` is TCC-protected on macOS** → the `launchd` daemon got "Operation not permitted."
   Relocated state off the protected path to a non-TCC home root. Also learned `launchd` ignores
   `EnvironmentVariables` in this setup → switched to explicit wrapper scripts.
3. **The brain bricked on a stale session id** (orphaned by the relocation above). Now it
   self-heals: a dead `--resume` falls back to a fresh session instead of erroring at the user.

Scorecard update: "cheaper" ✅ (proven, ≈ $0 over the plan), "reachable from anywhere" ✅,
"all-Claude Opus 4.8" ✅. Still ahead: the build dispatcher, the scheduler, files/voice, and the
migration.

---

## M3 — the build dispatcher, and closing the orchestration gap

The headline feature: message Bow a build request → it runs an autonomous headless build and reports
back. **40/40 tests, final review zero bugs.**

The interesting part is *how* the dispatcher got disciplined orchestration. A `launchd`-spawned
*interactive* session can't unlock the keychain (the M0 finding — which is exactly why I carried it
forward). So forcing an interactive high-effort mode was off the table. Instead of fighting it, I
reused my own pre-existing framework — **Fleet Mode**, already shipped as a skill — promoted it to a
global skill, and now **every headless `claude -p` build auto-applies it.** That gives every
dispatched build the same orchestration reflex: classify stakes, bias-to-NO on adding agents
(anchored on the negative-average payoff I measured in my own runs), write single-threaded, and run an independent refute-first review
before declaring done. It natively *is* the producer/QC split.

Proof, end-to-end: a dispatched build created and ran code, then auto-wrote a Fleet Mode receipt
showing it correctly chose *not* to fan out for a trivial task, wrote single-threaded, and ran an
independent review before finishing — no keychain, no interactive mode, ≈ $0 over the plan.

**The QC catch that mattered:** the security review flagged that queued builds run with permissions
bypassed (rated HIGH). I did **not** silently ship that. I accepted it *with controls* and
documented it: the chat allowlist is the load-bearing gate; a sandbox is a deferred item. An honest
"accepted risk, here's why and here's the mitigation" beats a hidden one.

---

## M4 — the scheduler

Recurring routines, in two modes — **script → notify** and **`claude -p` prompt → notify** (agentic)
— evaluated on each daemon poll by a pure `due()` predicate (interval plus daily-with-weekday).
**58/58 tests, zero bugs.**

**The design decision that mattered:** I chose an in-daemon tick over per-routine `launchd` plists.
It's simpler, self-contained, and — the non-obvious win — interval and daily routines *catch up
after the machine sleeps*, because `due()` re-evaluates on wake instead of silently missing a fire.
Cron is the deliberate exception: a cron routine fires only inside its matching minute, so one whose
minute elapsed while asleep is not back-fired (you don't want a 9:30 job suddenly running at 10:15).
That asymmetry is a design choice, not an oversight — it's why daily-with-weekday exists for jobs
that must survive a sleep, and cron exists for jobs that should only run on an exact wall-clock
minute. Live-verified: a 1-minute routine fired and delivered a ping to my phone.

This is also where I locked in the rule for the real migration to come: the existing scheduled
production job would move in M6 via a *staged parallel run*, never a flip-and-pray.

---

## M5 — files + voice (and a feature that fell out for free)

Bow gained two-way file transfer and voice. **67/67 tests, zero bugs.**

- **Voice:** an inbound voice note is downloaded and transcribed locally (ffmpeg → whisper.cpp, a
  small English model, entirely on the Mac, no cloud) and then handled as if typed. I verified the
  transcription pipeline on real speech *before* writing the integration code.
- **Files:** a send command pushes a file to my phone (confirmed live); inbound files land in a
  local inbox. The multipart upload is hand-rolled stdlib — I kept Bow dependency-light, the only
  new external pieces being two local binaries.

**The architecture-pays-off moment:** read/write access to my personal knowledge base needed
*no new code*. The brain is real Claude Code, so once a one-time macOS Full Disk Access grant was in
place, it already reached those files — it just needed a map of where they live. That's the dividend
of the "be the tool" bet: whole features fall out for free instead of being rebuilt.

**The QC catch that mattered:** the Full Disk Access grant didn't land where I assumed. An empirical
probe in the `launchd` context showed the grant had attached to the homebrew Python and the `claude`
binary — but the daemon was running the system Python, which had no access. Fix: point the `launchd`
wrappers at the homebrew Python (the same interpreter all the tests run on). Proof: a
daemon-dispatched build then wrote a file into the previously-blocked path. I'd have shipped a silent
"works on my machine" bug without that probe.

---

## M6 — the cutover (the careful one)

**72/72 tests** (67 from M5 plus 5 cutover-specific tests covering seeded-`last_run` cold-start
and the staged-parallel logic). I migrated the one real recurring production job I cared about —
**a daily scheduled quantitative job** — onto Bow, and retired the old gateway. I treated this as
the highest-stakes step in the build, because it touches live operations, so it got the most
caution, not the least:

1. **Read the actual job first.** Confirmed it runs in a safe, non-destructive mode, with its own
   internal guards, a cooldown, and a threshold — i.e. I understood exactly what I was rehoming
   before I rehomed it.
2. **Verified the runtime environment** imported its dependencies under Bow's invocation path.
3. **Atomic cutover — never two schedulers on the same job at once.** Bow's routine runs the same
   wrapper through the same runtime; I seeded its `last_run` state so it would *not* fire
   off-schedule the moment it went live (confirmed: no spurious run was triggered).
4. **Fully reversible.** I paused the old schedule and archived the old gateway's plist rather than
   deleting anything. Backing out is a one-step restore, not a rebuild.

Live proof was the next scheduled run reporting in from Bow on time. Bow became the all-Claude
operator; the old gateway was retired.

**The QC catch that mattered:** the seeded-`last_run` step. Without it, the atomic cutover would have
been atomic *and* would have immediately fired the job off its real schedule — correct in spirit,
wrong in timing. Reversibility plus a deliberate cold-start is what makes a live cutover safe to do
in one session.

Still owed after this: generalize the scheduler to accept any cron expression, then an extensive QC
pass and a security pass.

---

## The extensive QC pass, then cron-for-anything

These were the last two pieces, and they account for the rest of the test count: the QC pass took
the suite from **72 → 86** (+14 regression tests), and generalizing the scheduler took it from
**86 → 101** (+15). That's the whole chain, monotonic and traceable: 23 (M1+M2) → 40 (M3) →
58 (M4) → 67 (M5) → 72 (M6) → 86 (QC) → 101 (cron-for-anything).

**The extensive QC pass** is the part I'm proudest of, because it's where multi-agent review earned
its keep on a real, irreversible-feeling system instead of a toy. It was a 37-agent adversarial
review across six dimensions (correctness, concurrency, reliability, resource-leaks,
operational-safety, edge-cases): **30 raw findings → each adversarially verified → 13 confirmed → 7
deduped (1 high, 6 medium, 0 critical).** All fixed, with **14 new regression tests (72 → 86).**

**Cron-for-anything.** With the system hardened, I generalized the scheduler to accept any cron
expression — `*`, lists, ranges, steps, the day-of-month / day-of-week OR-rule, and
once-per-minute dedup — and to reload routines from disk on each poll, so Bow can take on a new
scheduled job of any kind without a restart. That generalization and its edge cases added the final
**15 regression tests (86 → 101).**

**The bug that justified the whole pass — the soft-lock.** The independent QC caught that a single
malformed scheduled-job field could **freeze the entire daemon.** Routine dispatch ran *before* the
message-fetch step in the poll loop, so one bad routine raising an exception would take down message
handling too — Bow would go silent, and the only symptom would be "it stopped answering." This is a
class of bug unit tests on the happy path never see. The fix:

- **Per-routine isolation.** Each routine now runs inside its own `try/except`; one malformed job can
  no longer poison the loop.
- **Defensive field reads** in `due()`, so a missing or wrong-typed field degrades gracefully instead
  of raising.

The same pass closed a family of silent-drop bugs: guarded the voice/document downloads, added
central message chunking (long messages were being dropped past the size limit), made sends
best-effort (a notify-channel outage can no longer abort a whole poll), and added
non-dict-JSON guards on every persistent store. The live production job was verified unaffected
throughout.

> The multi-agent QC earned its cost here — these were real bugs the unit tests missed. That is also
> exactly why the doctrine *defaults to a single agent*: I only fanned out 37 ways because this was
> read-heavy, parallelizable adversarial review on a system I was about to trust with a live job. The
> stakes earned the fan-out; most tasks don't.

---

## Where this stands

Bow runs daily as my all-Claude chief-of-staff, reachable from my phone, on first-party Claude Code
at ≈ $0 marginal cost over a flat-rate plan I already pay for. It absorbed a live scheduled job via
an atomic, reversible cutover. The numbers in the metrics strip — 16 modules, 1,025 LOC of package
code against 1,339 LOC of tests, 101 test functions, 6 milestones — are re-verified by command, not
recalled from memory. The ❌s on the scorecard are real and I left them in.

The honest summary of the skill on display isn't "I wrote a daemon." It's: I made an architectural
bet (*be the tool, don't call the API*), then architected, directed, and gated fleets of Claude
agents to build and adversarially review it — and the gates caught real bugs every single time. The
soft-lock bug below is the clearest single instance: an independent QC pass caught a malformed
routine field that could freeze the entire daemon, a failure the happy-path unit tests never saw.
That is what the orchestration buys, and it's the competency on display.
