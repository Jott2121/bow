# single_writer_dispatcher.py
#
# THE PROBLEM
# A build can take minutes. The daemon ticks on the order of seconds. So I can't
# run a build inline — it would wedge the long-poll loop and the watchdog would
# (correctly) decide the daemon had hung. The build has to run detached, outliving
# the tick that started it.
#
# THE RACE I REFUSED TO SHIP
# The obvious design has the daemon and each detached build both writing the shared
# jobs.json — daemon flips a job to "running", the build flips it to "done". Two
# processes writing one JSON file with no lock is a torn-write waiting to happen:
# last-writer-wins clobbers state, and you only find out in production at 2am.
#
# THE DECISION: ONE WRITER, ALWAYS.
#   - The detached runner writes EXACTLY ONE thing it owns: queue/output/<id>.json.
#     It never touches jobs.json.
#   - The daemon owns jobs.json outright and detects completion by the *presence*
#     of that result file — not by a status another process tried to set.
# The filesystem becomes the handoff: an atomic create the daemon polls for. No
# lock, no shared mutable file, no torn write. The trade is a tiny latency (you
# learn a build finished on the next tick, not the instant it exits) — cheap
# insurance against a class of bug that's miserable to debug after the fact.
#
# Excerpt — trimmed for standalone reading; not runnable as-is.

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAP = 3  # never run more than this many builds concurrently


# --- DISPATCHER SIDE: spawn detached, then record "running" (daemon-owned write) ---

def _default_spawn(job_id):
    # Detached: survives the daemon tick; runs to completion and writes its status file.
    # start_new_session=True puts it in its own process group so it isn't killed when
    # the tick that launched it returns.
    log = (ROOT / "queue" / "output" / f"{job_id}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    f = open(log, "w")
    subprocess.Popen(
        [sys.executable, "-m", "bow.runbuild", job_id],
        cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def dispatch(job_id, store, spawn=None):
    (spawn or _default_spawn)(job_id)
    store.set(job_id, status="running")   # daemon owns jobs.json — this write is safe


def drain(store, cap=CAP, spawn=None):
    # Backpressure: only ever have `cap` builds in flight at once.
    running = sum(1 for j in store.all() if j["status"] == "running")
    for job in store.all():
        if running >= cap:
            break
        if job["status"] == "queued":
            dispatch(job["id"], store=store, spawn=spawn)
            running += 1


# --- RUNNER SIDE: the detached process. Writes ONLY its own result file. ---

def run_build(job_id, store, outdir, runner):
    """Detached build worker. Drives a headless `claude -p` agent for the job, then
    writes the one file it is allowed to write. It NEVER opens jobs.json."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    job = store.get(job_id)

    # The agent is invoked under a Fleet Mode preamble: classify stakes, fan out
    # read-only subagents for research, keep edits single-threaded, run deterministic
    # checks then an independent refute-first review, and leave irreversible acts for
    # me to approve. (Preamble text lives in the real module.)
    cmd = [
        resolve_claude_bin(), "-p", build_prompt(job["task"]),
        "--effort", "xhigh", "--permission-mode", "bypassPermissions",
        "--output-format", "json",
    ]
    rc, out, err = runner(cmd, job["repo"])

    if rc == 0:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = {}
        summary = (payload.get("result") or "")[:1500]
        status = "failed" if payload.get("is_error") else "done"
        result = {
            "status": status, "exit_code": rc,
            "session_id": payload.get("session_id", ""),
            "cost": payload.get("total_cost_usd", 0.0), "summary": summary,
        }
    else:
        result = {"status": "failed", "exit_code": rc, "session_id": "",
                  "cost": 0.0, "summary": (err or "").strip()[:1500]}

    # SINGLE-WRITER RULE: the runner writes its own result file and nothing else.
    # The daemon owns jobs.json and detects completion by the presence of this file,
    # which sidesteps a two-process write race on shared state entirely.
    (outdir / f"{job_id}.json").write_text(
        json.dumps({"id": job_id, **result}, indent=2)
    )
    return result


# --- DAEMON SIDE: watch for the result file. The only place jobs.json changes. ---

def notify_completed_builds(store, outdir, send_message, chat_id):
    """A build is done when its detached runner has written queue/output/<id>.json.
    The runner never touches jobs.json (single-writer rule), so completion is detected
    by that file's presence — not by a status the daemon can't otherwise see. This is
    the ONLY place a finished build mutates jobs.json, so there is no writer to race."""
    outdir = Path(outdir)
    for j in store.all():
        if j.get("announced"):
            continue
        result_file = outdir / f"{j['id']}.json"
        if not result_file.exists():
            continue   # not done yet; check again next tick
        try:
            res = json.loads(result_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue   # half-written file — try again next tick rather than crash
        status = res.get("status", "done")
        icon = "✅" if status == "done" else "❌"
        send_message(
            f"{icon} build `{j['id']}` {status} (${res.get('cost', 0):.2f})\n"
            f"{res.get('summary', '')[:1200]}", chat_id=chat_id)
        # daemon-owned write — the single writer of jobs.json
        store.set(j["id"], announced=True, status=status,
                  cost=res.get("cost", 0.0), summary=res.get("summary", ""))


# Referenced from the real modules; stubbed here so the excerpt reads standalone.
def resolve_claude_bin(): ...
def build_prompt(task): ...
