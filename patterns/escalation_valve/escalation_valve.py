"""Escalation valve: ONE toolless consult to a stronger model at a hard decision point.

The honest boundary of a skills-based agent: process transfers via skills; raw judgment
doesn't. When a cheaper session hits a real fork (architecture choice, subtle triage
after a failed fix, adversarial review), it buys one frontier-tier opinion instead of
pretending. Toolless + hard timeout: a consult costs pennies of headroom and can never
take actions. There is no cap on consults; a receipts ledger records every automatic one
instead, so the operator reviews the ledger rather than throttling the valve.

Extracted from a production personal-agent system where this exact logic backstops hard
judgment calls at run time. Reference implementation: copy the file, keep the tests."""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_QUESTION = 8000
_PREFIX = ("You are a one-shot senior consult with no tools. Give a decisive judgment with the "
           "key reasoning, and name what evidence would change your mind. Under 400 words.\n\n"
           "QUESTION:\n")


def _build_cmd(prompt, model, claude_bin=None, effort=None):
    """The default runner's command line (pure seam, so tests can pin it)."""
    cmd = [claude_bin or shutil.which("claude"), "-p", prompt, "--model", model]
    if effort:
        cmd += ["--effort", effort]
    cmd += [
        "--disallowedTools", "Bash,Edit,Write,Read,NotebookEdit,WebFetch,WebSearch,Task,Glob,Grep",
        # Flags for `claude -p` agents that use NO tools: skip all MCP server startup (no
        # schema listing, no per-call server-process spawns) and skip user settings
        # (plugins/skills a toolless consult can't invoke anyway). Cuts context tokens and
        # startup latency on a call that will never touch a tool.
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--setting-sources", "project",
    ]
    return cmd


def _claude_runner(prompt, model, claude_bin=None, effort=None):
    out = subprocess.run(_build_cmd(prompt, model, claude_bin, effort),
                         capture_output=True, text=True, timeout=300)
    return out.stdout.strip()


def run(question, model, runner=None, claude_bin=None, effort=None):
    """The consult. Fail-soft: ANY failure returns None, never raises. `model` is
    required — name your strongest available tier; there is no built-in default.
    `effort` raises reasoning depth on models that support it; production runs
    consults high."""
    if not isinstance(question, str) or not question.strip():
        return None
    prompt = _PREFIX + question.strip()[:MAX_QUESTION]
    try:
        if runner is not None:
            return runner(prompt) or None
        return _claude_runner(prompt, model, claude_bin, effort) or None
    except Exception as e:
        print(f"[escalation_valve] run failed (fail-soft): {e}", file=sys.stderr)
        return None


def auto(ledger_path, question, surface, trigger, model, runner=None, effort=None):
    """Automatic consult: run() + one append-only receipt. No cap on automatic consults;
    every one is auditable instead. Fail-soft on BOTH halves: a dead ledger must not block
    the consult, a dead consult must not raise."""
    ans = run(question, model, runner=runner, effort=effort)
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "surface": surface, "trigger": trigger,
             "question": (question or "")[:300],
             "outcome": "answered" if ans else "unavailable"}
    try:
        p = Path(ledger_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[escalation_valve] ledger append failed: {e}", file=sys.stderr)
    return ans
