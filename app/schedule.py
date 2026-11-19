"""Scheduled runs: a job is launched at a given time (grading at a deadline) or on a cron expression.

Times are interpreted in AGORA_TZ (e.g. Europe/Paris), or the server's local time when unset.
A schedule is checked every TICK seconds; one that was missed by more than GRACE seconds
(server down) is skipped instead of firing late, and says so in `last_error`.
"""
import asyncio
import logging
from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, db

log = logging.getLogger("agora.schedule")

TICK = 20
GRACE = 15 * 60
MACROS = {
    "@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *",
}
# (min, max) of each field: minute, hour, day of month, month, day of week (0 and 7 = Sunday)
RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


class ScheduleError(ValueError):
    """Message is safe to show to the user."""


def tz() -> tzinfo | None:
    if not config.TZ:
        return None
    try:
        return ZoneInfo(config.TZ)
    except ZoneInfoNotFoundError:
        return None


def tz_name() -> str:
    return config.TZ if tz() else (datetime.now().astimezone().tzname() or "server time")


def _field(text: str, lo: int, hi: int, name: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.isdigit() or int(s) < 1:
                raise ScheduleError(f"{name}: invalid step")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
            if part == "":
                raise ScheduleError(f"{name}: empty value")
        elif "-" in part:
            x, _, y = part.partition("-")
            if not (x.isdigit() and y.isdigit()):
                raise ScheduleError(f"{name}: invalid range {part!r}")
            a, b = int(x), int(y)
        elif part.isdigit():
            a = int(part)
            b = hi if step > 1 else a  # "5/15" = from 5 to the end, every 15
        else:
            raise ScheduleError(f"{name}: invalid value {part!r}")
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise ScheduleError(f"{name}: {part!r} is out of range ({lo}-{hi})")
        out.update(range(a, b + 1, step))
    return out


def parse_cron(expr: str):
    """-> (minutes, hours, days, months, weekdays, dom_restricted, dow_restricted)"""
    expr = MACROS.get(expr.strip().lower(), expr).strip()
    parts = expr.split()
    if len(parts) != 5:
        raise ScheduleError("A cron expression has 5 fields: minute hour day-of-month month day-of-week")
    names = ["minute", "hour", "day of month", "month", "day of week"]
    sets = [_field(p, lo, hi, n) for p, (lo, hi), n in zip(parts, RANGES, names)]
    sets[4] = {d % 7 for d in sets[4]}  # 7 = Sunday = 0
    return (*sets, parts[2] != "*", parts[4] != "*")


def next_cron(expr: str, after: float) -> float:
    """First matching minute strictly after `after` (epoch seconds)."""
    mi, ho, da, mo, wd, dom_r, dow_r = parse_cron(expr)
    zone = tz()
    t = datetime.fromtimestamp(after, zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = t + timedelta(days=366 * 5)
    while t < limit:
        if t.month not in mo:
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        cron_wd = (t.weekday() + 1) % 7  # Python: Monday=0; cron: Sunday=0
        # Standard cron: when both day fields are restricted, a day matches if either one does.
        if dom_r and dow_r:
            day_ok = t.day in da or cron_wd in wd
        else:
            day_ok = t.day in da and cron_wd in wd
        if not day_ok:
            t = t.replace(hour=0, minute=0) + timedelta(days=1)
            continue
        if t.hour not in ho:
            t = t.replace(minute=0) + timedelta(hours=1)
            continue
        if t.minute not in mi:
            t += timedelta(minutes=1)
            continue
        return t.timestamp()
    raise ScheduleError("This expression never matches")


def parse_once(text: str) -> float:
    try:
        dt = datetime.fromisoformat(text.strip())
    except ValueError:
        raise ScheduleError("Invalid date (expected YYYY-MM-DDTHH:MM)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz()) if tz() else dt.astimezone()
    return dt.timestamp()


def first_run(kind: str, expr: str, now: float) -> float:
    """Validates a schedule and returns its first run time."""
    if kind == "cron":
        return next_cron(expr, now)
    if kind == "once":
        ts = parse_once(expr)
        if ts <= now:
            raise ScheduleError("This time is already past")
        return ts
    raise ScheduleError("kind must be 'once' or 'cron'")


def tick(enqueue_for, now: float | None = None) -> int:
    """Fire what is due. `enqueue_for(job_id, user_id) -> int` queues the builds (raises on failure).

    Each schedule is moved to its next run *before* firing, so a crash can never fire it twice.
    Returns the number of schedules fired.
    """
    now = db.now() if now is None else now
    with db.tx() as c:
        due = db.rows(c, "SELECT * FROM schedules WHERE enabled=1 AND next_run<=?", now)
        for s in due:
            late = now - s["next_run"] > GRACE
            if s["kind"] == "cron":
                try:
                    nxt = next_cron(s["expr"], max(now, s["next_run"]))
                except ScheduleError:
                    nxt = None
            else:
                nxt = None
            c.execute(
                "UPDATE schedules SET next_run=?, enabled=?, last_run=?, last_error=? WHERE id=?",
                nxt, 1 if nxt else 0, now,
                "missed (the server was not running at that time)" if late else None, s["id"],
            )
    fired = 0
    for s in due:
        if now - s["next_run"] > GRACE:
            continue
        try:
            n = enqueue_for(s["job_id"], s["user_id"])
            err, queued = None, n
        except Exception as e:  # noqa: BLE001 - shown to the user in the schedule row
            err, queued = str(getattr(e, "detail", e))[:300], 0
            log.warning("schedule %s failed: %s", s["id"], err)
        with db.tx() as c:
            c.execute("UPDATE schedules SET last_error=?, last_queued=? WHERE id=?", err, queued, s["id"])
        fired += 1
    return fired


async def loop(enqueue_for) -> None:
    while True:
        try:
            await asyncio.to_thread(tick, enqueue_for)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK)
