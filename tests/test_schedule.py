"""Run with: python -m unittest discover -s tests"""
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["AGORA_TZ"] = "Europe/Paris"

from app import schedule as sc  # noqa: E402


def ts(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=sc.tz()).timestamp()


def at(t):
    return datetime.fromtimestamp(t, sc.tz()).strftime("%Y-%m-%d %H:%M %a")


class Cron(unittest.TestCase):
    def test_daily(self):
        self.assertEqual(at(sc.next_cron("30 18 * * *", ts(2026, 11, 19, 17))), "2026-11-19 18:30 Thu")
        self.assertEqual(at(sc.next_cron("30 18 * * *", ts(2026, 11, 19, 18, 30))), "2026-11-20 18:30 Fri")

    def test_every_15_minutes(self):
        self.assertEqual(at(sc.next_cron("*/15 * * * *", ts(2026, 11, 19, 10, 1))), "2026-11-19 10:15 Thu")

    def test_weekdays(self):
        # Saturday 2026-11-21 -> Monday
        self.assertEqual(at(sc.next_cron("0 8 * * 1-5", ts(2026, 11, 21, 9))), "2026-11-23 08:00 Mon")

    def test_sunday_both_notations(self):
        for e in ("0 9 * * 0", "0 9 * * 7"):
            self.assertEqual(at(sc.next_cron(e, ts(2026, 11, 19))), "2026-11-22 09:00 Sun")

    def test_dom_or_dow(self):
        # both restricted: the 1st OR a Monday, whichever comes first (Mon 23rd)
        self.assertEqual(at(sc.next_cron("0 0 1 * 1", ts(2026, 11, 19))), "2026-11-23 00:00 Mon")

    def test_month_rollover_and_leap(self):
        self.assertEqual(at(sc.next_cron("0 0 29 2 *", ts(2026, 11, 19))), "2028-02-29 00:00 Tue")
        self.assertEqual(at(sc.next_cron("0 12 31 * *", ts(2026, 11, 19))), "2026-12-31 12:00 Thu")

    def test_lists_and_macros(self):
        self.assertEqual(at(sc.next_cron("0 8,12,20 * * *", ts(2026, 11, 19, 9))), "2026-11-19 12:00 Thu")
        self.assertEqual(at(sc.next_cron("@hourly", ts(2026, 11, 19, 9, 5))), "2026-11-19 10:00 Thu")

    def test_dst_spring_forward(self):
        # 2026-03-29: Paris jumps 02:00 -> 03:00. A daily 09:00 job still fires at 09:00 local.
        self.assertEqual(at(sc.next_cron("0 9 * * *", ts(2026, 3, 28, 10))), "2026-03-29 09:00 Sun")

    def test_invalid(self):
        for bad in ("", "* * * *", "61 * * * *", "* 24 * * *", "a b c d e", "*/0 * * * *", "5-1 * * * *", "0 0 31 2 *"):
            with self.assertRaises(sc.ScheduleError, msg=bad):
                sc.next_cron(bad, ts(2026, 11, 19))


class Once(unittest.TestCase):
    def test_future_ok_past_refused(self):
        now = ts(2026, 11, 19, 12)
        self.assertEqual(at(sc.first_run("once", "2026-11-20T23:59", now)), "2026-11-20 23:59 Fri")
        with self.assertRaises(sc.ScheduleError):
            sc.first_run("once", "2026-11-19T11:00", now)
        with self.assertRaises(sc.ScheduleError):
            sc.first_run("once", "tomorrow", now)


class Tick(unittest.TestCase):
    def setUp(self):
        import tempfile
        from app import config, db
        self.db = db
        d = tempfile.mkdtemp()
        config.DB_PATH = Path(d) / "t.db"
        config.DATA_DIR = Path(d)
        db.init()
        with db.tx() as c:
            c.execute("INSERT INTO jobs (id,name,image,command,created_at,updated_at) VALUES (1,'j','i','c',0,0)")

    def add(self, kind, expr, nxt):
        with self.db.tx() as c:
            return c.execute("INSERT INTO schedules (job_id,kind,expr,user_id,next_run,created_at) VALUES (1,?,?,7,?,0)",
                             kind, expr, nxt).lastrowid

    def row(self, i):
        with self.db.read() as c:
            return self.db.row(c, "SELECT * FROM schedules WHERE id=?", i)

    def test_once_fires_one_time(self):
        i, calls = self.add("once", "x", 1000), []
        self.assertEqual(sc.tick(lambda j, u: calls.append((j, u)) or 3, now=1005), 1)
        self.assertEqual(sc.tick(lambda j, u: calls.append((j, u)) or 3, now=1100), 0)
        self.assertEqual(calls, [(1, 7)])
        r = self.row(i)
        self.assertEqual((r["enabled"], r["last_queued"], r["last_error"]), (0, 3, None))

    def test_cron_reschedules(self):
        now = ts(2026, 11, 19, 18, 30)
        i = self.add("cron", "30 18 * * *", now - 5)
        sc.tick(lambda j, u: 1, now=now)
        r = self.row(i)
        self.assertEqual((r["enabled"], at(r["next_run"])), (1, "2026-11-20 18:30 Fri"))

    def test_missed_is_skipped_not_fired(self):
        i, calls = self.add("once", "x", 1000), []
        self.assertEqual(sc.tick(lambda j, u: calls.append(1), now=1000 + sc.GRACE + 60), 0)
        self.assertEqual(calls, [])
        self.assertIn("missed", self.row(i)["last_error"])

    def test_failure_is_recorded(self):
        def boom(j, u):
            raise RuntimeError("no SSH key")
        i = self.add("once", "x", 1000)
        sc.tick(boom, now=1001)
        self.assertEqual(self.row(i)["last_error"], "no SSH key")

    def test_disabled_is_ignored(self):
        i = self.add("once", "x", 1000)
        with self.db.tx() as c:
            c.execute("UPDATE schedules SET enabled=0")
        self.assertEqual(sc.tick(lambda j, u: 1, now=1001), 0)


if __name__ == "__main__":
    unittest.main()
