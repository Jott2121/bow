"""Proactive compactor — keeps a headless chat agent's handoff brief ready BEFORE
rotation needs it.

LOAD-BEARING FACT (see RESUME-DOES-NOT-FORK.md in this directory): resuming a Claude Code
session from a background process does not fork it — a maintenance turn lands in the
live conversation. So this module NEVER touches the session: it reads the transcript
FILE from disk (`iter_turns`, below) and rolls a brief in the background instead. The
cache has ONE writer (the caller's single in-flight thread) and is written atomically
(tmp+rename). Every path is fail-soft: a broken compactor only means rotation falls back
to the caller's own cliff flush.

Extracted from a production personal-agent system where this exact logic keeps a
headless chat agent's handoff brief warm across session rotations. Reference
implementation: copy the file, keep the tests."""
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TRIGGER = 0.6          # start compacting at 60% of the rotation threshold
REGROW = 0.2           # refresh after the transcript grows another 20%
TAIL_CHARS = 40_000    # how much recent turn text the summarizer sees
BRIEF_MAX_CHARS = 4000 # same cap as the cliff flush handoff

_PROMPT = (
    "You are writing a HANDOFF BRIEF for the successor of a chat session that will soon "
    "be rotated out (its history will NOT be visible to the successor). Below are (1) the "
    "previous brief, if any, and (2) the most recent conversation turns. Roll them into "
    "ONE updated brief, max ~25 lines: active threads, commitments and deadlines, "
    "decisions with provenance ('the operator said/decided X on <date>'), anything "
    "mid-flight. Newest information wins on conflicts. Output ONLY the brief.\n\n"
)

_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _text_of(content):
    """A transcript message's content is a plain str OR a list of typed blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def iter_turns(transcript_path):
    """Yield (role, text) for real main-chain conversation turns out of a Claude Code
    session JSONL transcript file: only `type` user/assistant entries, sidechains
    skipped, harness noise (system-reminders, command stdout, attachments) skipped."""
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                e = json.loads(ln)
            except (ValueError, TypeError):
                continue
            if not isinstance(e, dict) or e.get("isSidechain"):
                continue
            if e.get("type") not in ("user", "assistant"):
                continue
            text = _REMINDER_RE.sub("", _text_of((e.get("message") or {}).get("content"))).strip()
            if not text or text.startswith("<"):        # command stdout / caveat / attachment
                continue
            yield e["type"], text


def needs_compaction(key, sid, transcript_bytes, rotate_bytes, cache):
    """Pure trigger rule: past 60% of the threshold, and either no usable cache entry
    (missing / different session) or the transcript grew 20% past the last snapshot."""
    if not sid or transcript_bytes < TRIGGER * rotate_bytes:
        return False
    e = (cache or {}).get(key)
    if not e or e.get("sid") != sid:
        return True
    try:
        return transcript_bytes >= float(e.get("bytes_at", 0)) * (1 + REGROW)
    except (TypeError, ValueError):
        return True


def load_cache(cache_path):
    try:
        d = json.loads(Path(cache_path).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_cache(cache_path, cache):
    """Atomic replace — the single-writer discipline's mechanical half."""
    p = Path(cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fresh_brief(cache_path, key, sid, transcript_bytes):
    """The brief, IF it covers this session and at least half the current transcript."""
    e = load_cache(cache_path).get(key)
    if not e or e.get("sid") != sid:
        return None
    try:
        if float(e.get("bytes_at", 0)) < 0.5 * float(transcript_bytes):
            return None
    except (TypeError, ValueError):
        return None
    b = e.get("brief")
    return b if isinstance(b, str) and b.strip() else None


def drop_entry(cache_path, key):
    """Remove a consumed/stale entry. Idempotent, fail-soft."""
    try:
        cache = load_cache(cache_path)
        if key in cache:
            del cache[key]
            _write_cache(cache_path, cache)
    except Exception as e:
        print(f"[proactive_compactor] drop_entry failed: {e}", file=sys.stderr)


def build_brief(transcript_path, prev_brief, summarizer):
    """(brief|None, cost). Reads the transcript file, never the session. Fail-soft.
    `summarizer` is a required callable (prompt) -> (text, cost_usd): this pattern makes
    no default model call, so bring your own (the README shows a `claude -p` reference
    summarizer)."""
    try:
        lines = [f"{role.upper()}: {text}" for role, text in iter_turns(transcript_path)]
        tail = "\n".join(lines)[-TAIL_CHARS:]
        if not tail.strip():
            return None, 0.0
        prompt = (_PROMPT + "PREVIOUS BRIEF:\n" + (prev_brief or "(none)")
                  + "\n\nRECENT TURNS:\n" + tail)
        text, cost = summarizer(prompt)
        return ((text or "").strip()[:BRIEF_MAX_CHARS] or None), float(cost or 0)
    except Exception as e:
        print(f"[proactive_compactor] build_brief failed: {e}", file=sys.stderr)
        return None, 0.0


def compact(cache_path, key, sid, transcript_path, transcript_bytes, summarizer, budget_check=None):
    """Orchestrate one compaction: optional budget gate -> roll brief -> atomic cache
    write. True only when the cache was updated. Fail-soft (False + stderr) otherwise.

    `budget_check` is an optional caller-supplied callable returning `(ok, reason)`;
    `None` always allows. This pattern does not meter its own spend or call any budget
    module directly — `build_brief`'s cost is the caller's to record (e.g. against
    `budget_governor.record_spend`), and the gate it can be checked against (e.g.
    `budget_governor.check`) is passed in as `budget_check`. The two patterns compose
    through the caller, never through an import — see this pattern's README."""
    try:
        if budget_check is not None:
            ok, reason = budget_check()
            if not ok:
                print(f"[proactive_compactor] skipped ({reason})", file=sys.stderr)
                return False
        cache = load_cache(cache_path)
        prev = (cache.get(key) or {}).get("brief")
        brief, _cost = build_brief(transcript_path, prev, summarizer)
        if not brief:
            return False
        cache[key] = {"sid": sid, "brief": brief, "bytes_at": int(transcript_bytes),
                      "ts": datetime.now().isoformat(timespec="seconds")}
        _write_cache(cache_path, cache)
        return True
    except Exception as e:
        print(f"[proactive_compactor] compact failed: {e}", file=sys.stderr)
        return False
