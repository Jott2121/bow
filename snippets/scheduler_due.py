# scheduler_due.py
#
# THE PROBLEM
# Scheduled routines need to fire on a cron-style schedule, an interval, or a daily
# time-of-day (optionally restricted to certain weekdays). The naive version of this
# is where scheduling bugs breed: double-fires when a tick lands twice in the same
# matching minute, missed fires across a restart, the classic cron day-of-week-vs-
# day-of-month ambiguity, off-by-one on "has it already run today."
#
# THE DECISION: MAKE THE ENTIRE DECISION A PURE FUNCTION.
# `due(schedule, last_run, now)` takes the schedule, the last-run timestamp, and the
# current time, and returns a bool. No clock reads inside. No I/O. No daemon state.
# That's deliberate — it's the one piece of timing logic I most need to trust, so I
# made it the easiest thing in the system to test: feed it a frozen `now` and a
# `last_run`, assert the bool. Every edge case below is a one-line test, not a
# flaky integration run. The daemon stays a thin caller; the judgment lives here.
#
# Notable correctness calls baked in:
#   - cron fires AT MOST ONCE per matching minute (compare last_run's minute to now's).
#   - cron's real OR-rule when BOTH day-of-month and day-of-week are restricted.
#   - daily won't fire before its target time today, and won't re-fire once it has run.
#   - interval is plain elapsed-seconds since last_run.
#
# CATCH-UP AFTER SLEEP — note the deliberate asymmetry:
#   - interval and daily DO catch up. interval compares elapsed seconds, and daily uses
#     last_dt.date() < now.date(), so a routine slept past its time still fires on wake.
#   - cron does NOT catch up by design. cron_matches() is only true inside the matching
#     minute, so a cron job whose minute elapsed while the machine slept is not back-fired
#     on wake (a 9:30 cron run is intentionally not replayed at 10:15). Use daily-with-
#     weekday for "must survive a sleep"; use cron for "only on this exact wall-clock minute."
# A null/typo'd field returns False (don't fire) rather than throwing — pairs with the
# per-routine isolation in the daemon so a bad schedule degrades to "never runs," not
# "crashes the loop."
#
# Excerpt — the real module, lightly trimmed; pure and unit-tested.

from datetime import datetime


def _parse_field(field, lo, hi):
    """Expand a single cron field into a set of ints.
    Supports  *  ,  a  ,  a-b  ,  */n  ,  a-b/n  , and comma lists of those."""
    values = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return values


def cron_matches(expr, now):
    """True if a 5-field cron expression (min hour dom month dow) matches `now`."""
    if not expr or len(expr.split()) != 5:
        return False
    minute_f, hour_f, dom_f, month_f, dow_f = expr.split()
    if now.minute not in _parse_field(minute_f, 0, 59):
        return False
    if now.hour not in _parse_field(hour_f, 0, 23):
        return False
    if now.month not in _parse_field(month_f, 1, 12):
        return False
    # day-of-week: cron uses 0-6 with 0=Sun (7 also = Sun)
    dow_set = {d % 7 for d in _parse_field(dow_f, 0, 7)}
    cron_dow = now.isoweekday() % 7  # isoweekday 7=Sun -> 0
    dom_set = _parse_field(dom_f, 1, 31)
    dom_ok = now.day in dom_set
    dow_ok = cron_dow in dow_set
    dom_restricted = dom_f != "*"
    dow_restricted = dow_f != "*"
    # The gotcha most hand-rolled cron parsers get wrong: when BOTH day fields are
    # restricted, real cron ORs them. Only one restricted -> just that one applies.
    if dom_restricted and dow_restricted:
        day_ok = dom_ok or dow_ok
    elif dom_restricted:
        day_ok = dom_ok
    elif dow_restricted:
        day_ok = dow_ok
    else:
        day_ok = True
    return day_ok


def due(schedule, last_run, now):
    """Return True if a routine with this schedule should run at `now` (a datetime).
    `last_run` is an epoch float or None. Pure: no clock reads, no I/O — every branch
    below is trivially testable with a frozen `now`."""
    kind = schedule.get("type")

    if kind == "cron":
        expr = schedule.get("expr")
        if not cron_matches(expr, now):
            return False
        if last_run is None:
            return True
        last_dt = datetime.fromtimestamp(last_run, tz=now.tzinfo)
        # fire at most once per matching minute (a tick landing twice won't double-fire)
        return (last_dt.year, last_dt.month, last_dt.day, last_dt.hour, last_dt.minute) != \
               (now.year, now.month, now.day, now.hour, now.minute)

    if kind == "interval":
        minutes = schedule.get("minutes")
        if minutes is None:
            return False
        if last_run is None:
            return True
        return (now.timestamp() - last_run) >= minutes * 60

    if kind == "daily":
        at = schedule.get("at")
        if at is None:
            return False
        weekdays = schedule.get("weekdays")
        if weekdays and now.isoweekday() not in weekdays:
            return False
        try:
            hh, mm = (int(x) for x in at.split(":"))
        except ValueError:
            return False  # malformed time -> don't fire, don't throw
        if (now.hour, now.minute) < (hh, mm):
            return False  # target time hasn't arrived yet today
        if last_run is None:
            return True
        last_dt = datetime.fromtimestamp(last_run, tz=now.tzinfo)
        return last_dt.date() < now.date()  # already ran today?

    return False  # unknown/typo'd type -> never fire (fail safe, don't crash the caller)
