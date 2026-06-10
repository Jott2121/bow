# Bow: case study notes

Moved out of the [README](../README.md) to keep it short. Same rule applies here: receipts over hype.

## What this demonstrates

Transferable signal for an AI-builder reader:

- **Systems design under real constraints.** Auth, cost, macOS TCC, concurrency, reliability, all solved against the wall, not on a whiteboard.
- **An AI-native SDLC.** Spec → plan → subagent build → independent adversarial QC → security review → tests → reversible production cutover.
- **An original orchestration doctrine (Fleet Mode)** that generalizes how to run agent fleets, directly transferable to anyone building agentic products.
- **Build-vs-buy and cost judgment.** Collapsed a multi-tool, multi-provider stack to one AI at about $0 marginal cost over an existing plan.
- **Honest engineering communication.** A scorecard with explicit misses and a real limitations section.
- **Shipped and operated.** It runs daily and absorbed a live job via an atomic, reversible cutover. A redacted tail of the live daemon log, with real ISO timestamps showing a routine firing and the watchdog confirming the heartbeat, is in [`assets/daemon-log-excerpt.txt`](../assets/daemon-log-excerpt.txt).

A note on the artifacts in `assets/`: the pytest output and the daemon log excerpt are raw tool output (only secrets, ids, and paths redacted). The FLEET MODE and QC receipts are hand-formatted summaries of real runs, clearly stylized, not raw console capture. The two kinds are kept visibly distinct on purpose; conflating a formatted summary with raw evidence is exactly the kind of thing this project is trying not to do. Raw: [`receipt-tests`](../assets/receipt-tests.txt), [`daemon-log-excerpt`](../assets/daemon-log-excerpt.txt). Formatted summaries: [`receipt-fleet-mode`](../assets/receipt-fleet-mode.txt), [`receipt-qc-catch`](../assets/receipt-qc-catch.txt).

## Cost

> About $0/mo over an existing flat-rate plan, vs. metered API pricing that is nonzero and recurring forever for an equivalent do-everything agent.

The build-vs-buy reasoning is the whole architecture in one line: a do-everything agent built on a metered API key costs real money every month, forever, on top of a flat-rate plan I already pay for. The exact metered figure depends on traffic, so I won't dress a guess as analysis. The load-bearing point is the shape: a recurring monthly bill that scales with use, versus about $0 marginal. As one worked anchor, a do-everything assistant running all day at even ~1M Opus-4.8 tokens/day of mixed input/output lands in the low tens of dollars a month at current metered rates and climbs from there with heavier build traffic. Recurring, forever.

By being a first-party Claude Code user rather than a third-party API caller, Bow puts every chat turn and every build under the plan I already have, and inherits skills, memory, MCP servers, and tools for free instead of rebuilding two-thirds of the old system. That is why the marginal cost is about $0 and why two-thirds of the old feature list was never rebuilt: it wasn't needed.

## Closing

**Full private repo and the test suite available on request.**

I architected this system, made the central bet (*be the tool, don't call the API*), and then directed and gated fleets of Claude (Opus 4.8) subagents to implement and adversarially review it, under the Fleet Mode doctrine, which runs as a live skill so the orchestration is operational, not an essay. The gates caught real bugs every single time; the soft-lock catch in the README's section 5 is the proof that orchestration-under-gates earns its keep.
