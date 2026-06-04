# Fleet Mode

*The orchestration doctrine behind Bow. Receipts over hype.*

I didn't set out to write a doctrine. I set out to build a chief-of-staff agent I
could reach from my phone, and I kept running into the same question on every
non-trivial task: **how many agents do I throw at this, and where do I put the
gate?** Fleet Mode is the answer I converged on — a small set of rules for running
fleets of Claude (Opus 4.8) subagents that earns its keep instead of burning
tokens on theater. Bow is an all-Claude system; I architected, directed, and gated
the fleets that built and adversarially reviewed it. The rules below are what I
direct them with.

It is the rule I reach for on any change that is non-trivial or hard to undo. A
typo, a rename, a one-line doc tweak — those skip the fleet and take a single fast
pass. Everything with stakes goes through the gate.

---

## The core rule: know when to fan out

Most of the value in multi-agent work is in *not* using it. The skill being
demonstrated here is not "spin up twelve agents." It is knowing, before you spend a
token, which of two shapes the task is — and the default answer is one agent.

> **Default to a single agent. Across my own runs, adding agents has a negative
> average payoff — naive fan-out usually costs more than the single-agent baseline
> rather than beating it; fan out only for read-heavy parallel work that demonstrably
> earns it.**

That directional finding is the load-bearing fact of the whole doctrine, and I want to
be precise about where it comes from: it's what I measured in my own multi-agent runs
on this and adjacent work, not a published benchmark I'm borrowing authority from. If
you internalize one thing, internalize that adding agents has a *negative* average
payoff. Fan-out is a tool with a narrow indication, not a default. Treating "more
agents = better" as a reflex is the single most expensive mistake in agentic work, and
it is the one everyone makes first.

So the core rule has a sharp edge: **bias to no.** You start from one strong agent
and you only break that posture when the task structurally demands it. Below are the
four sub-rules that say exactly when.

---

## The four sub-rules

### 1. Read-heavy work fans out

Fan-out is for *reading*, not for acting. The legitimate use is work that is
parallelizable and exceeds what one context window can hold cleanly: research across
many sources, reviewing a large diff, auditing a codebase or a set of files for one
property. Each subagent explores in its own clean context and returns a tight,
condensed summary — on the order of one to two thousand tokens — instead of dragging
its full transcript back into the parent. That is the whole trick: many cheap reads,
collapsed into a few small answers, with the expensive synthesis done once.

If the work isn't read-heavy and parallelizable, this sub-rule does not fire, and
you are back to one agent.

### 2. Writes stay single-threaded

One agent makes the edit. Always. There is no version of "fan out to write this
faster" that survives contact with reality — parallel writers race, clobber each
other, and leave you reconciling a mess that costs more than the time you thought you
saved. Extra agents are allowed to add *intelligence* to a write (review it, pressure
it, propose alternatives) but never *parallel actions*. Map-reduce-and-manage: the
fan-out reads, the single writer writes.

This is the rule people most want to break, because writing is where the work
*feels* like it's happening. Break it and you'll spend your savings on merge
conflicts and corrupted state.

### 3. Deterministic machine checks first, then an independent refute-first reviewer

The QC gate runs in a fixed order, and the order matters.

**Deterministic first.** Before any model looks at the work, run the checks that need
no judgment: tests, types, lint, build, and re-derive every number that's going to be
printed. These are objective, cheap, and they fail loudly. There is no reason to
spend a model's attention on something a test can settle.

**Then an independent reviewer — whose job is to refute.** Only if the deterministic
checks pass do you bring in a reviewer, and that reviewer runs in a *separate, clean
context* with one mandate: try to break the work, not bless it. No agent grades its
own homework — the author and the reviewer are never the same agent. For high-stakes,
irreversible, or published output, the reviewer escalates to a different-model judge.
The gate fails closed: if the reviewer isn't satisfied, the work doesn't ship.

This sequencing is deliberate. Machine checks are free and certain; reviewer
attention is expensive and fallible. You spend the cheap certain thing first and only
pay for judgment on what survives.

### 4. Default-to-no, anchored on the negative-average finding

The other three sub-rules tell you *how* to fan out, review, and write. This one is
the governor on all of them, and it points back at the core fact:

> **Default to a single agent. Across my own runs, adding agents has a negative
> average payoff; fan out only for read-heavy parallel work that demonstrably earns
> it.**

Every time you reach for another agent, the burden of proof is on the agent, not on
you. "More would be better" is not a reason — my own runs say it usually isn't. The
task has to *demonstrably* earn the fan-out (read-heavy, parallelizable, over one
context window) or it doesn't get it. Scale to the task; start at one.

There's a parallel gate for irreversible acts that rides on top of this: anything
genuinely MAJOR — hard to reverse, changes a core default, deploys, sends, posts,
spends, or deletes at scale — stops and waits for a human before it happens. The
fleet is autonomous up to the point where a mistake stops being cheap.

---

## The honest beat: the labs shipped the same idea

I'll be straight about provenance, because the receipts-over-hype posture cuts both
ways. After I had Fleet Mode running as my default operating mode, the labs shipped
essentially the same idea — an orchestration reflex marketed as "ultracode":
extra-high effort plus dynamic workflow orchestration, an agent that decides when to
fan out and reviews its own output before declaring done.

I'm not claiming I invented something the labs then copied. I'm claiming I *arrived
at it independently* — the same conclusion, from the same pressure, before it had a
product name. When my interactive sessions couldn't reach that mode in the headless
environment Bow runs in, I didn't try to force the labs' version. I reached for the
framework I'd already built and made every headless build auto-apply it. The result
is ultracode's reflex, but headless and, frankly, more disciplined: it's explicitly
biased *against* spawning agents (grounded in the negative-average payoff I measured in
my own runs), and it natively *is* the producer/reviewer split rather than asking one
agent to honestly grade itself.

That convergence is the point I'd want a reader to take away. When you operate agent
fleets seriously and adversarially, you converge on the same rules the people
building the models converge on — because they're the rules the work actually
rewards, not the ones that demo well.

---

Fleet Mode is not an essay. It runs as a Claude Code skill on the machine that
builds Bow — every headless build classifies its own stakes, fans out (or doesn't),
writes single-threaded, passes deterministic checks then an independent refute-first
review, human-gates the irreversible, and logs a receipt with the real number.
The doctrine is operational.
