"""Compactor core invariants. Fixtures use the same Claude Code session JSONL shape that
`iter_turns` parses (see the module docstring)."""
import json

import proactive_compactor as compactor


def _write_session(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries))


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text):
    return {"type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def test_needs_compaction_truth_table():
    rb = 1000
    below = int(0.5 * rb); above = int(0.7 * rb)
    assert not compactor.needs_compaction("k", "s1", below, rb, {})          # under trigger
    assert compactor.needs_compaction("k", "s1", above, rb, {})              # first crossing
    cache = {"k": {"sid": "s1", "bytes_at": above, "brief": "b"}}
    assert not compactor.needs_compaction("k", "s1", above, rb, cache)       # no regrow yet
    assert compactor.needs_compaction("k", "s1", int(above * 1.25), rb, cache)  # +20% regrow
    assert compactor.needs_compaction("k", "s2", above, rb, cache)           # sid changed
    assert not compactor.needs_compaction("k", None, above, rb, cache)       # no sid -> never


def test_cache_roundtrip_and_atomicity(tmp_path):
    cp = tmp_path / "handoff-cache.json"
    assert compactor.load_cache(cp) == {}                                    # missing -> {}
    cp.write_text("{corrupt")
    assert compactor.load_cache(cp) == {}                                    # corrupt -> {}
    compactor._write_cache(cp, {"k": {"sid": "s", "brief": "b", "bytes_at": 1, "ts": "t"}})
    assert compactor.load_cache(cp)["k"]["brief"] == "b"
    assert not list(tmp_path.glob("*.tmp"))                                  # rename cleaned up


def test_fresh_brief_rules(tmp_path):
    cp = tmp_path / "c.json"
    compactor._write_cache(cp, {"k": {"sid": "s1", "brief": "the brief",
                                      "bytes_at": 600, "ts": "t"}})
    assert compactor.fresh_brief(cp, "k", "s1", 1000) == "the brief"    # 600 >= 500
    assert compactor.fresh_brief(cp, "k", "s1", 1300) is None           # 600 < 650: stale
    assert compactor.fresh_brief(cp, "k", "s2", 1000) is None           # sid mismatch
    assert compactor.fresh_brief(cp, "nope", "s1", 1000) is None        # no entry


def test_drop_entry(tmp_path):
    cp = tmp_path / "c.json"
    compactor._write_cache(cp, {"k": {"sid": "s", "brief": "b", "bytes_at": 1, "ts": "t"}})
    compactor.drop_entry(cp, "k")
    assert compactor.load_cache(cp) == {}
    compactor.drop_entry(cp, "k")                                       # idempotent


def test_build_brief_rolls_prev_and_tail(tmp_path):
    s = tmp_path / "t.jsonl"
    _write_session(s, [_user("we decided X"), _assistant("noted, X it is")])
    seen = {}
    def fake(prompt):
        seen["p"] = prompt
        return "BRIEF v2", 0.03
    brief, cost = compactor.build_brief(s, "BRIEF v1", summarizer=fake)
    assert brief == "BRIEF v2" and cost == 0.03
    assert "BRIEF v1" in seen["p"] and "we decided X" in seen["p"]
    assert "USER:" in seen["p"]


def test_build_brief_fail_soft(tmp_path):
    s = tmp_path / "t.jsonl"
    _write_session(s, [_user("hello")])
    def boom(prompt):
        raise RuntimeError("model down")
    brief, cost = compactor.build_brief(s, None, summarizer=boom)
    assert brief is None and cost == 0.0
    brief2, _ = compactor.build_brief(tmp_path / "missing.jsonl", None,
                                      summarizer=lambda p: ("x", 0.0))
    assert brief2 is None                                                    # no turns -> None


def test_build_brief_caps_length(tmp_path):
    s = tmp_path / "t.jsonl"
    _write_session(s, [_user("hi")])
    brief, _ = compactor.build_brief(s, None, summarizer=lambda p: ("y" * 9000, 0.0))
    assert brief is not None and len(brief) == compactor.BRIEF_MAX_CHARS


def test_compact_happy_path_writes_cache(tmp_path):
    calls = {"check": 0}
    def budget_check():
        calls["check"] += 1
        return True, "ok"
    s = tmp_path / "t.jsonl"
    _write_session(s, [_user("decision: ship it")])
    cp = tmp_path / "c.json"
    ok = compactor.compact(cp, "k", "s1", s, 700,
                           summarizer=lambda p: ("brief!", 0.04),
                           budget_check=budget_check)
    assert ok and calls["check"] == 1
    e = compactor.load_cache(cp)["k"]
    assert e["sid"] == "s1" and e["brief"] == "brief!" and e["bytes_at"] == 700 and e["ts"]


def test_compact_skips_when_budget_check_says_no(tmp_path):
    s = tmp_path / "t.jsonl"; _write_session(s, [_user("x")])
    assert not compactor.compact(tmp_path / "c.json", "k", "s1", s, 700,
                                 summarizer=lambda p: ("b", 0.0),
                                 budget_check=lambda: (False, "wall until 4pm"))
    assert compactor.load_cache(tmp_path / "c.json") == {}


def test_compact_fail_soft_on_summarizer_death(tmp_path):
    s = tmp_path / "t.jsonl"; _write_session(s, [_user("x")])
    def boom(p):
        raise TimeoutError("240s")
    assert not compactor.compact(tmp_path / "c.json", "k", "s1", s, 700, summarizer=boom)


def test_compact_respects_budget_check(tmp_path):
    s = tmp_path / "t.jsonl"; _write_session(s, [_user("decision: ship it")])
    ok = compactor.compact(tmp_path / "c.json", "k", "s1", s, 700,
                           summarizer=lambda p: ("brief", 0.01),
                           budget_check=lambda: (False, "over budget"))
    assert not ok and compactor.load_cache(tmp_path / "c.json") == {}


def test_compact_default_budget_always_allows(tmp_path):
    s = tmp_path / "t.jsonl"; _write_session(s, [_user("x")])
    ok = compactor.compact(tmp_path / "c.json", "k", "s1", s, 700,
                           summarizer=lambda p: ("brief", 0.01))
    assert ok
