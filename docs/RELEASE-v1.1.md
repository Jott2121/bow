# v1.1: the patterns release

## What's new

Three guardrail patterns, extracted from the production system this repo documents, now
ship as runnable, stdlib-only code with their real tests:

- [`budget_governor`](../patterns/budget_governor/): stops an agent from dying mid-task
  when a shared usage cap runs dry.
- [`proactive_compactor`](../patterns/proactive_compactor/): keeps a long session from
  stalling on a blocking flush at rotation, and includes the three-call experiment that
  proved the tempting "background summarize" design was wrong:
  [resume does not fork](../patterns/proactive_compactor/RESUME-DOES-NOT-FORK.md).
- [`escalation_valve`](../patterns/escalation_valve/): hands a hard call up to a stronger
  model with a receipts ledger instead of a cap.

Alongside the patterns, [`docs/RELIABILITY-WEEK.md`](RELIABILITY-WEEK.md) is a new writeup
covering the hardening pass that produced them: what got proposed, what got measured
before being trusted, and what got caught only by running the thing, not by review or
tests alone. The [README](../README.md) now leads with the patterns instead of the case
study, and each pattern links back to the reliability writeup for the receipt behind it.

## Why

This repo started as a case study of a production system. The July arc was different:
instead of shipping a new feature, the goal was making what already shipped harder to
break and cheaper to run forever, and then pulling the load-bearing pieces of that
hardening pass out into something a reader could actually run, not just read about. The
patterns in this release are behavior-preserving extractions of that real logic, not
rewrites for the demo.

## The numbers

    python3 -m pytest patterns/ -q
    ................................                                 [100%]
    32 passed in 0.03s

32 tests, hermetic, zero live model calls, zero writes outside a tmp directory, under 2
seconds on a clean clone. The receipts behind each pattern (the phantom-spend catch, the
per-compaction cost, the fork experiment) are in each pattern's own README and in
[`docs/RELIABILITY-WEEK.md`](RELIABILITY-WEEK.md).

## Honest limits

These patterns are the mechanism, not the whole system. The governor only sees spend you
record into it; the compactor briefs thin long arcs and durable facts still belong in
your own memory system; the valve's consults are only as good as the question you inline.
Wiring three independent patterns together is still the caller's job, documented in
[`patterns/README.md`](../patterns/README.md#composition), not solved by an import between
pattern directories.
