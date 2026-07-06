# Reliability Week: hardening Bow after the launch build

The [build log](BUILD-LOG.md) covers the six milestones that got Bow live. This page covers what
came after: a follow-on week in July 2026 where the target wasn't a new feature, it was making the
thing I'd already shipped harder to break and cheaper to run forever. Same rule as everywhere else
in this repo: receipts over hype, including when the receipt is "the result was flat."

## 1. Mining my own corrections, and an honest flat result

The first idea: stop guessing which behaviors to bake into Bow's skills, and instead mine them out
of real usage. A propose-only miner reads back through session history looking for the pattern
"correction happened here," ranks the clusters, and drafts skill candidates for me to approve or
reject one at a time. Nothing gets installed without a human reading the diff first.

The harder discipline was proving the drafts actually helped before keeping them, instead of just
believing they would. I ran a blind pre/post bench: identical model, identical effort setting, three
tasks, two runs each, before and after installing the mined skills. A separate blind judge scored all
twelve outputs with the run identities shuffled and hidden, so it couldn't tell pre from post. I
wrote the decision rule down *before* looking at a single score: keep the change only if some task
cleared a real margin; anything smaller counts as flat.

The result was +0.5 on all three tasks. Exactly at the threshold I'd pre-committed to, which by the
letter of my own rule means flat, not a win. I could have called it a win by rounding generously. I
didn't.

A closed-prompt bench is a lower bound anyway for skills that only fire when a specific trigger
phrase shows up in a real conversation, which never happens in a one-shot scored task. What I did do
was look past the single number: all three tasks moved the same direction, and the worst run in the
whole set went from a 7 pre-installation to an 8 post. Four of six post-runs scored a 9 versus two of
six pre. Direction plus a rising floor is a real signal even when the mean doesn't clear the bar.
Ruling: keep the installed set, on the direction-and-floor argument, written down as exactly that: a
defensible read of a technically-flat result, not a rounded-up win.

## 2. The escalation valve

Some calls are expensive to get wrong and cheap to double-check: an architecture fork, a bug that
survived one fix attempt already, a plan I'm not fully sold on. For exactly those, there's a small
escalation skill: one toolless call to a fresh instance in a clean context, no history, no ability
to touch anything, just a second opinion.

The interesting design choice is what *doesn't* gate it. There's no hard cap on how often it can
fire. The guardrail is an append-only receipts ledger instead: every consult logs a timestamp, which
surface called it, the trigger, a truncated version of the question, and the outcome. The plan is to
eyeball that ledger weekly rather than pre-guess a number and hardcode a limit that's either too
tight to be useful or too loose to matter.

It also fires on its own now, not just when I remember to ask. Three autopilot triggers: a nudge
after repeated tool or build failures in a row (with a short decay window so it doesn't nag on every
single failure after the first one), a one-shot consult when an autonomous loop stalls out, injected
back in as a senior critique, and a consult on any build that fails or gets flagged by its own
quality judge, riding the same completion ping that already exists. All three were live-verified, not
just unit-tested: I watched the nudge actually fire mid-session, and watched a stalled loop's consult
land in the ledger with a real answered outcome.

Runnable version with tests: [patterns/escalation_valve/](../patterns/escalation_valve/)

## 3. The budget governor: living inside a shared cap, not a wallet

Running everything under a flat-rate plan means the constraint isn't a dollar budget in the usual
sense, it's a shared usage cap that resets on a wall-clock schedule. Two failure modes matter here:
hitting the cap and going silent with no explanation, and burning the whole week's headroom on
autonomous background work before anything urgent gets a turn.

The governor handles both, and the design choices are the interesting part:

- **The cooldown parses its own reset time.** When a call gets rate-limited, the error text names
  when the limit clears. Instead of hardcoding a guessed cooldown window, the governor parses that
  timestamp out of the error itself, adds a slack buffer, and falls back to a conservative fixed
  window only if the message doesn't parse the way it's supposed to.
- **A daily self-meter runs independently of the hard wall**, tracking an estimated spend-equivalent
  against a soft daily target. This catches a single expensive day before it ever needs to touch the
  hard cap to get noticed.
- **Non-urgent scheduled work defers, it doesn't drop.** One summary note per day, not one per
  deferral, and the scheduler's own catch-up logic (the same `due()` behavior from the original
  build) picks deferred work back up automatically. Urgent work bypasses the gate entirely.
- **The whole thing fails open.** If the meter itself throws, it never blocks the work it's
  measuring. The doctrine, in one line: burn is cheaper than silence. A system that goes quiet to
  protect a budget has failed at its actual job.

Live-proven on the real event ledger, not a synthetic test: I watched an actual sequence of wall
limit hit, next call blocked, an urgent job bypass the block anyway, the cooldown expire, and normal
service resume, all four steps present in the real log in order.

Two characteristics I'm noting rather than fixing: some routine spend isn't separately metered yet
(deliberately, in the fail-open direction), and a single heavy day of interactive use alone can push
the daily meter past target and defer routine work for that day. That second one is intended
chat-protection behavior, not a bug, tunable if it ever gets annoying.

Runnable version with tests: [patterns/budget_governor/](../patterns/budget_governor/)

## 4. The proactive compactor, and the design that got killed before it was built

Long-running sessions eventually need to compact their own history or they hit a hard length limit
and stall. The obvious design for a background compactor is: open a maintenance conversation against
the same resumed session, ask it to summarize itself, done.

Before writing a line of that design, I ran a small empirical check instead of assuming the obvious
design was safe: three calls against the same resumed session id, checking whether a "maintenance"
turn shares state with the real conversation or forks off into its own branch. It does not fork. A
maintenance turn run against a live resumed session lands in the exact same line as the real
conversation, meaning the obvious design would have polluted the actual session with its own
summarization chatter every time it ran. That's the kind of bug that would have shown up as Bow
occasionally saying strange things for no visible reason, weeks later, nearly impossible to trace
back to its cause. The three-call experiment killed the wrong design before it existed instead of
after it shipped.

The design that survived: read the transcript file directly off disk, a static artifact that's
already been written, instead of resuming the live session to ask it to summarize itself. A single
toolless role turns that transcript into a short handoff brief. The brief gets written by exactly one
writer to an atomic cache file (the same single-writer discipline as the original build's result
files), gated and metered by the governor like everything else, one compaction running at a time,
kicked off at a threshold comfortably below the hard rotation cliff so there's room to finish before
rotation is forced. When a fresh brief is ready, rotation is instant: swap in a new session carrying
the brief forward. The old blocking flush-and-wait behavior stays as an untouched fallback for the
case where no fresh brief exists yet.

Live-proven end to end: a real brief generated from an actual multi-megabyte transcript, the governor
gate correctly blocking the very first attempt (proof the two systems are actually wired together,
not just sitting next to each other), and a real instant rotation afterward carrying that brief
forward. Metered cost for one compaction call: about $0.23.

Runnable version with tests: [patterns/proactive_compactor/](../patterns/proactive_compactor/)

## 5. What live verification caught that reviews and tests could not

Every one of these passed code review. Two of them passed the test suite too. All three only surfaced
once I stopped trusting a green check and went and watched the running system. The theme: a command
sent is not a command landed.

1. **Six test call-sites were quietly making real model calls.** Not mocked, not faked, just live
   calls happening inside what everyone assumed was a hermetic test suite. Found by review, not by a
   failure, because nothing was failing: the tests passed and burned real usage on every run. Fixed;
   the full suite now runs in under a second with zero live calls.
2. **Test runs were writing into the same production ledger the budget governor reads.** No isolation
   between a pytest run's fake events and the real append-only spend ledger meant every test suite
   run was quietly inflating the real number. About $65 of phantom test spend had accumulated in the
   production ledger by the time this was caught, well past the daily target, which means the
   governor was already refusing real work for a completely fictional reason. In fact that is how
   the bug surfaced: the governor blocked a legitimate run, I went to see why, and the ledger was
   full of test fixtures. Root-fixed with proper per-run isolation; verified by
   running the full suite twice in a row and confirming zero new entries landed in the real ledger
   either time.
3. **A wrapper introduced on one branch silently broke a feature built on another.** A guarding
   wrapper added around the session object didn't transparently forward two methods the compactor
   depended on. Neither branch's review caught it, because each branch was correct in isolation; the
   break only existed at the intersection of both, after they merged. The compactor's background tick
   died on every single poll, silently, with no crash and no alert, for as long as the two features
   sat merged and unobserved. It was caught by watching the live daemon after the merge, not by
   anything static. Fixed by making the wrapper delegate transparently, covered with a regression
   test, then re-verified by watching the real feature fire correctly in production afterward with an
   actual metered receipt in hand.

None of these three were reachable by a smarter unit test written in advance. Two of them required
two different pieces of correct-in-isolation code to actually be combined and run. The lesson I keep
relearning: a passing test suite and a clean review are necessary and never sufficient. Go watch the
thing run.

## 6. Absorbing a model lineup that changed out from under the system, more than once

The model tier a piece of work runs on isn't hardcoded anywhere in Bow. Every call resolves through a
small routing table: a role (chat, build, background judge, and so on) maps to a tier, and that
mapping lives in a config file the system re-reads on every call, not in the code. Chat tags like
"cheap" or "deep" are aliases into that same table, not names of specific models.

That design choice got tested for real within about a month. A premium tier I'd wired in for the
hardest escalation path appeared, later became unavailable, came back, and then went away again. A
separate everyday tier jumped a full generation and got promoted from mid-tier to the system's
default. In every one of those events, in both directions, the fix was the same: one line in a config
file, never a code change, because a tag was never actually the model, it was always an alias that
resolved through the table. The one follow-on discipline that mattered: after the everyday tier
jumped generations, the independent judge role that grades its output got re-pinned to a different
tier on purpose, so the reviewer stays a genuinely different reader from the writer instead of
quietly becoming the same generation grading its own homework.

## Where this leaves things

Nothing here shipped with a hard cap standing in for judgment. The escalation ledger is read weekly,
not enforced by a limit. The governor fails open by design. The compactor's fallback path is the
original blocking flush, deliberately left alone rather than rewritten just because a better path
now exists most of the time. Every one of those is a written-down trade-off, not an oversight, in
keeping with the rest of this repo: an accepted risk with a stated mitigation beats a hidden one, and
a measured flat result reported honestly beats a rounded-up win.
