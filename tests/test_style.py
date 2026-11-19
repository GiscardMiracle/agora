"""Run with: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import style  # noqa: E402

# Real epiclang output of a student's Makefile run (indented by the test set, pseudo-tty line ends).
EPICLANG = """epiclang -o my_ls alpha.c my_compute_power_rec.c my_isneg.c flag_l.c
    sflag_lsbase.c:38:14: warning: [Banana] [Major] nested if statement at depth 3 (C-C1)\r
       38 |         else if (!S_ISDIR(buf.st_mode))\r
          |              ^\r
    sflag_lsbase.c:40:14: warning: [Banana] [Major] nested if statement at depth 4 (C-C1)\r
       40 |         else if (sans_flagp(av[i]) == 84)\r
          |              ^\r
    2 warnings generated.\r
"""


def collect(text):
    c = style.Collector()
    for line in text.splitlines():
        c.feed(line.rstrip("\r"))
    return c


class Epiclang(unittest.TestCase):
    def test_real_output(self):
        c = collect(EPICLANG)
        self.assertEqual(c.counts, {"major": 2, "minor": 0, "info": 0})
        self.assertEqual(c.items[0], {"file": "sflag_lsbase.c", "line": 38, "col": 14, "sev": "major", "rule": "C-C1",
                                      "msg": "nested if statement at depth 3"})

    def test_same_warning_printed_by_several_builds_counts_once(self):
        c = collect(EPICLANG * 3)
        self.assertEqual(c.counts["major"], 2)

    def test_checker_ran_without_findings_is_a_clean_result(self):
        c = collect("epiclang -o my_ls a.c b.c\n")
        self.assertTrue(c.checked)
        self.assertEqual(c.counts, {"major": 0, "minor": 0, "info": 0})

    def test_no_checker_means_no_result(self):
        c = collect("gcc -o prog a.c\na.c:3:1: warning: unused variable 'x' [-Wunused-variable]\nmake: epiclangish\n")
        self.assertFalse(c.checked)

    def test_severities(self):
        c = collect("a.c:1:1: warning: [Banana] [Minor] too long (C-F3)\na.c:2:1: warning: [Banana] [Info] note (C-A3)\n"
                    "a.c:3:1: warning: [Banana] [Major] bad (C-G1)\n")
        self.assertEqual(c.counts, {"major": 1, "minor": 1, "info": 1})
        self.assertEqual([v["sev"] for v in c.items], ["major", "minor", "info"])


class Other(unittest.TestCase):
    def test_banana_check_repo_format(self):
        c = collect("./src/main.c:12: MAJOR:C-F3 # too long\n./a.c:3: MINOR:C-L2\n")
        self.assertEqual(c.counts, {"major": 1, "minor": 1, "info": 0})
        self.assertEqual(c.items[0]["file"], "src/main.c")

    def test_plain_clang_diagnostic_with_rule(self):
        c = collect("main.c:4:1: warning: function too long [C-F4]\nmain.c:9:1: error: forbidden (C-G1)\n")
        self.assertEqual(c.counts, {"major": 1, "minor": 1, "info": 0})

    def test_ordinary_output_ignored(self):
        c = collect("warning: something\nINFO: all good\nC-3PO says hi\ntests/a.c:1:1: note: C-F1\n")
        self.assertFalse(c.checked)


if __name__ == "__main__":
    unittest.main()


class Step(unittest.TestCase):
    """The dedicated style step: its raw output goes through a LineSink into the same Collector."""

    def test_sink_handles_chunks_cut_anywhere(self):
        c = style.Collector()
        sink = style.LineSink(c)
        data = ("a.c:1:1: warning: [Banana] [Major] x (C-C1)\r\n" "b.c:2:2: warning: [Banana] [Info] y (C-A3)").encode()
        for i in range(0, len(data), 7):
            sink.write(data[i:i + 7])
        sink.close()
        self.assertEqual(c.counts, {"major": 1, "minor": 0, "info": 1})

    def test_missing_checker_detected(self):
        self.assertTrue(style.missing_checker(127, ""))
        self.assertTrue(style.missing_checker(0, "sh: 1: epiclang: not found\n"))
        self.assertFalse(style.missing_checker(1, "a.c:1:1: error: 'x.h' file not found"))
        self.assertFalse(style.missing_checker(0, ""))

    def test_default_command_covers_every_c_file(self):
        self.assertIn("-name '*.c'", style.DEFAULT_COMMAND)
        self.assertIn("epiclang -fsyntax-only", style.DEFAULT_COMMAND)
