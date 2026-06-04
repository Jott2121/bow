# daemon_resilience.py
#
# THE PROBLEM (caught by the adversarial QC pass, not by me writing the happy path)
# The daemon dispatches scheduled routines on every tick. The first cut iterated the
# routine list and evaluated each one's schedule inline. That works right up until one
# routine has a malformed schedule field — a typo'd cron expression, a null where a
# number should be, a hand-edited config. One bad routine throws, the exception escapes
# the loop, and the whole dispatch tick dies. Worse: it dies on EVERY tick, forever,
# because the bad routine never goes away. One typo soft-locks the entire daemon, and
# every other routine silently stops firing.
#
# I ran an independent adversarial QC pass over my own build (a fleet of Claude reviewers,
# 6 dimensions, refute-first) precisely to surface this class of bug before it shipped.
# It found exactly this soft-lock. The fix below is what the review forced in.
#
# THE DECISION: ISOLATE THE BLAST RADIUS PER ITEM.
#   - Each routine is evaluated inside its own try/except. A malformed routine fails
#     ALONE, gets logged, and the loop keeps going. One bad job can't take down the rest.
#   - The completion reader treats a half-written result file as "not ready yet" rather
#     than a crash — `continue` on JSONDecodeError/OSError, retry next tick.
#   - reload() before iterating so routines added at runtime are picked up without a
#     daemon restart.
# The trade: a genuinely broken routine fails quietly (you find it in the log, not in
# your face). For an unattended daemon that's the right default — degrade one feature,
# never the whole process. Availability of the supervisor beats loud failure of a leaf.
#
# Excerpt — trimmed for standalone reading; not runnable as-is.

import json
from pathlib import Path


def dispatch_due_routines(self):
    """Fire any routine whose schedule is due. Per-routine isolation is the whole point:
    a malformed schedule on ONE routine must not take down the dispatch loop (and with
    it every other routine) on this tick or any future tick."""
    if not self.routines:
        return
    self.routines.reload()   # pick up routines added since startup — no restart needed
    now = self._now()
    for r in self.routines.all():
        if not r.get("enabled", True):
            continue
        try:
            if _schedule.due(r["schedule"], r.get("last_run"), now):
                # set_last_run BEFORE spawning so a crash mid-spawn can't double-fire it
                self.routines.set_last_run(r["id"], now.timestamp())
                self._routine_spawn(r["id"])
        except Exception as e:
            # One malformed routine fails alone and loudly-in-the-log; the loop survives
            # and every other routine still gets its chance this tick.
            print(f"[bow.daemon] routine {r.get('id')} error: {e}", flush=True)


def notify_completed_builds(self):
    """Announce finished builds. A result file that's mid-write (the detached runner
    hasn't flushed yet) is treated as 'not ready' — we retry next tick instead of
    crashing the announce path on a partial read."""
    if not self.store:
        return
    for j in self.store.all():
        if j.get("announced"):
            continue
        result_file = self._outdir / f"{j['id']}.json"
        if not result_file.exists():
            continue
        try:
            res = json.loads(result_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue   # half-written or transiently unreadable — try again next tick
        status = res.get("status", "done")
        icon = "✅" if status == "done" else "❌"
        self.tg.send_message(
            f"{icon} build `{j['id']}` {status} (${res.get('cost', 0):.2f})\n"
            f"{res.get('summary', '')[:1200]}", chat_id=self.config.chat_id)
        self.store.set(j["id"], announced=True, status=status,
                       cost=res.get("cost", 0.0), summary=res.get("summary", ""))


def run(self):
    """The supervisor loop itself is wrapped: a poll that throws backs off and retries
    rather than killing the process. Combined with the heartbeat the watchdog watches,
    the daemon either keeps working or gets restarted — it does not silently die."""
    self.running = True
    while self.running:
        try:
            self.poll_once()
        except Exception as e:
            print(f"[bow.daemon] poll error: {e}", flush=True)
            self._sleep(5)


# Referenced from the real daemon module; named here so the excerpt reads standalone.
class _schedule:
    @staticmethod
    def due(schedule, last_run, now): ...
