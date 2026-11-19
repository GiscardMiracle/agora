"""Server-side colour buckets of the dashboard; must agree with tone() in static/app.js (see test_front.js)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["AGORA_DATA_DIR"] = tempfile.mkdtemp()

from app import main  # noqa: E402


class Outcome(unittest.TestCase):
    def test_same_scale_as_the_front_end(self):
        cases = [
            ("success", "100/100", "ok"), ("success", None, "ok"),
            ("failed", "129/129", "partial"), ("failed", "90/100", "partial"), ("failed", "30/100", "partial"),
            ("failed", "29/100", "ko"), ("failed", "27/129", "ko"), ("failed", None, "ko"),
            ("timeout", "50%", "partial"), ("timeout", None, "ko"),
            ("error", "90/100", "ko"),
        ]
        for status, score, want in cases:
            self.assertEqual(main.outcome(status, score), want, (status, score))

    def test_score_reading(self):
        self.assertAlmostEqual(main.score_pct("27/129"), 20.93, places=1)
        self.assertEqual(main.score_pct("85%"), 85)
        self.assertEqual(main.score_pct("120/100"), 100)
        self.assertIsNone(main.score_pct("0/0"))
        self.assertIsNone(main.score_pct("n/a"))
        self.assertIsNone(main.score_pct(None))


if __name__ == "__main__":
    unittest.main()
