"""Escalation valve is the escalation_valve: ONE toolless consult to a stronger model.
Fail-soft is load-bearing — a dead valve must never crash the session that pulled it."""
import json

import escalation_valve as valve

_MODEL = "claude-opus-4-8"


def test_model_is_explicit():
    seen = {}
    def fake(prompt):
        seen["prompt"] = prompt
        return "ok"
    assert valve.run("q", model=_MODEL, runner=fake) == "ok"
    assert "q" in seen["prompt"]


def test_build_cmd_effort_passthrough():
    with_effort = valve._build_cmd("p", _MODEL, claude_bin="/bin/claude", effort="high")
    i = with_effort.index("--effort")
    assert with_effort[i:i + 2] == ["--effort", "high"]
    assert with_effort[with_effort.index("--model") + 1] == _MODEL   # model lands after --model
    assert "--effort" not in valve._build_cmd("p", _MODEL, claude_bin="/bin/claude")


def test_run_returns_runner_answer_and_caps_question():
    seen = {}
    def fake(prompt):
        seen["prompt"] = prompt
        return "verdict: ship it"
    assert valve.run("q" * (valve.MAX_QUESTION + 5000), model=_MODEL, runner=fake) == "verdict: ship it"
    assert len(seen["prompt"]) <= valve.MAX_QUESTION + 300      # prefix + capped question


def test_run_fails_soft():
    def boom(prompt):
        raise RuntimeError("model down")
    assert valve.run("hard question", model=_MODEL, runner=boom) is None
    assert valve.run("", model=_MODEL, runner=lambda p: "x") is None
    assert valve.run("q", model=_MODEL, runner=lambda p: "") is None


def test_auto_answers_and_writes_receipt(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    ans = valve.auto(lp, "q" * 500, "loop", "stalled pass", model=_MODEL, runner=lambda p: "try Z")
    assert ans == "try Z"
    (line,) = lp.read_text().splitlines()
    e = json.loads(line)
    assert e["surface"] == "loop" and e["trigger"] == "stalled pass"
    assert e["outcome"] == "answered" and len(e["question"]) <= 300 and e["ts"]


def test_auto_unavailable_still_ledgers(tmp_path):
    lp = tmp_path / "ledger.jsonl"
    def boom(p):
        raise RuntimeError("down")
    assert valve.auto(lp, "hard q", "build", "judge flag", model=_MODEL, runner=boom) is None
    e = json.loads(lp.read_text().splitlines()[0])
    assert e["outcome"] == "unavailable"


def test_auto_tolerates_dead_ledger(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    ans = valve.auto(blocker / "ledger.jsonl", "q", "cli", "manual", model=_MODEL,
                      runner=lambda p: "ok")   # parent is a file -> mkdir fails
    assert ans == "ok"                                  # consult survives the dead ledger
