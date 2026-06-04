# session_self_heal.py
#
# THE PROBLEM
# Conversation continuity comes from passing `--resume <session_id>` to the headless
# `claude -p` CLI. I persist that session id to disk so a chat survives across daemon
# restarts. But a stored session id is not guaranteed to still exist when I go to use
# it: the on-disk session can be expired, relocated, or pruned out from under me. When
# that happens `--resume` fails with "no conversation found." The naive behavior is to
# surface that raw error back to the person texting from their phone — which is a
# terrible experience for a failure they didn't cause and can't fix.
#
# THE DECISION: SELF-HEAL INSTEAD OF ERRORING AT THE USER.
# If a resume fails *specifically because the session is stale* (matched narrowly — I do
# NOT swallow auth/billing/timeout failures, which mean something real), I retry once
# with a fresh session. The user loses prior context for that one turn but gets a real
# answer instead of an error. The new session id is then persisted, so the next turn
# is continuous again. The system quietly repairs its own state.
#
# Two supporting calls that matter:
#   - Error classification is narrow on purpose. Stale-session is the only thing I
#     auto-retry. Auth/billing/timeout get a coarse category surfaced to chat and the
#     full stderr logged locally — never raw stderr to the user.
#   - The session store writes ATOMICALLY (temp file + rename). A crash mid-write can't
#     leave a half-written sessions.json that would itself look like corruption next boot.
#
# Excerpt — trimmed for standalone reading; not runnable as-is.

import json
import sys
from pathlib import Path


class Brain:
    def __init__(self, session_store, cwd, model, claude_bin, runner):
        self.store = session_store
        self.cwd = cwd
        self.model = model
        self.claude_bin = claude_bin
        self._run = runner

    def _invoke(self, message, sid):
        cmd = [self.claude_bin, "-p", message, "--output-format", "json", "--model", self.model]
        if sid:
            cmd += ["--resume", sid]
        return self._run(cmd, self.cwd)

    @staticmethod
    def _is_stale_session(err):
        # Narrow match: ONLY a dead/missing session. Anything else is a real failure
        # I must not paper over by silently starting fresh.
        e = (err or "").lower()
        return "no conversation found" in e or ("session id" in e and "not found" in e)

    @staticmethod
    def _error_category(err):
        # Coarse, user-safe category for chat. Full stderr is logged locally, never shown.
        e = (err or "").lower()
        if "not logged in" in e or "keychain" in e or "/login" in e:
            return "auth"
        if "out of extra usage" in e or "credit balance" in e:
            return "billing"
        if "timed out" in e or "timeout" in e:
            return "timeout"
        return "error"

    def ask(self, message, key="default"):
        sid = self.store.get_session_id(key)
        rc, out, err = self._invoke(message, sid)

        # SELF-HEAL: a stored session can vanish (relocation, expiry, deletion). If
        # resume failed for THAT reason, start a fresh session instead of erroring.
        if rc != 0 and sid and self._is_stale_session(err):
            rc, out, err = self._invoke(message, None)

        if rc != 0:
            # Log full detail locally; surface only rc + a coarse category to chat.
            print(f"[bow.brain] claude -p failed rc={rc}: {(err or '').strip()[:2000]}",
                  file=sys.stderr)
            raise RuntimeError(f"claude -p failed (rc={rc}, {self._error_category(err)})")

        payload = json.loads(out)
        new_sid = payload.get("session_id")
        if new_sid:
            self.store.set_session_id(new_sid, key)   # persist so the NEXT turn resumes
        return payload.get("result", "")


class SessionStore:
    """Maps a conversation key -> session id, persisted as JSON. Reads tolerate a
    corrupt file (fall back to empty); writes are atomic so a crash can't create one."""

    def __init__(self, path):
        self.path = Path(path)
        self._data = {}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text())
                self._data = loaded if isinstance(loaded, dict) else {}
            except json.JSONDecodeError:
                self._data = {}   # corrupt store -> start clean rather than crash on boot

    def get_session_id(self, key="default"):
        return self._data.get(key, {}).get("session_id")

    def set_session_id(self, session_id, key="default"):
        self._data.setdefault(key, {})["session_id"] = session_id
        self._save()

    def _save(self):
        # Atomic write: a crash mid-save can't leave a half-written sessions.json.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)
