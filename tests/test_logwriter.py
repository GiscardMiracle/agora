"""Run with: python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["AGORA_DATA_DIR"] = tempfile.mkdtemp()

from app import runner  # noqa: E402


def feed(text: str) -> "runner.LogWriter":
    w = runner.LogWriter(Path(tempfile.mkdtemp()) / "x.log", [])
    w.write(text.encode())
    w.close()
    return w


class Parsing(unittest.TestCase):
    def test_score_failures_sections_with_colors(self):
        w = feed("\x1b[1;34m━━ tiny \x1b[0m\n  \x1b[1;32m✔\x1b[0m ok\n  \x1b[1;31m✘\x1b[0m bad\n      detail\n"
                 "\n━━ errors\n  ✘ exit 84\nAGORA_SCORE: 1/3\n")
        self.assertEqual(w.failures, [["tiny", "bad"], ["errors", "exit 84"]])
        self.assertEqual(w.score, "1/3")

    def test_banana_report(self):
        w = feed("./src/main.c:12: MAJOR:C-F3 # too long\n./src/a.c:3: MINOR:C-L2 # x\n./a.c:9: MINOR:C-O1\n./b.h:1: INFO:C-A3\n")
        self.assertEqual(w.style, {"major": 1, "minor": 2, "info": 1})

    def test_clang_diagnostics_with_rule_id(self):
        w = feed("main.c:4:1: warning: function too long [C-F4]\nmain.c:9:1: error: forbidden [C-G1]\n"
                 "main.c:9:1: warning: unused variable 'x' [-Wunused]\n")
        self.assertEqual(w.style, {"major": 1, "minor": 1, "info": 0})

    def test_ordinary_output_is_not_style(self):
        w = feed("warning: something\nINFO: all good\nC-3PO says hi\n")
        self.assertEqual(w.style, {"major": 0, "minor": 0, "info": 0})

    def test_line_split_across_writes(self):
        w = runner.LogWriter(Path(tempfile.mkdtemp()) / "y.log", [])
        w.write(b"a.c:1: MAJ")
        w.write(b"OR:C-F3\n  \xe2\x9c\x98 half")
        w.write(b" line\n")
        w.close()
        self.assertEqual(w.style["major"], 1)
        self.assertEqual(w.failures, [["", "half line"]])


if __name__ == "__main__":
    unittest.main()
