"""Docker arguments of the sandbox: unprivileged by default, a narrow root only when a job asks for it."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["AGORA_DATA_DIR"] = tempfile.mkdtemp()

from app import runner  # noqa: E402

B = {"memory_mb": 256, "image": "img"}


def args(**kw):
    return runner.Runner._sandbox_args("n", B, Path("/r"), Path("/t"), "true", False, **kw)


class Sandbox(unittest.TestCase):
    def test_default_is_the_host_user_with_no_capability(self):
        a = args()
        self.assertEqual(a[a.index("--user") + 1], f"{os.getuid()}:{os.getgid()}")
        self.assertNotIn("--cap-add", a)
        self.assertIn("--network", a)

    def test_privileged_is_root_with_a_short_capability_list(self):
        a = args(privileged=True)
        self.assertEqual(a[a.index("--user") + 1], "0:0")
        added = {a[i + 1] for i, v in enumerate(a) if v == "--cap-add"}
        self.assertEqual(added, set(runner.PRIV_CAPS))
        self.assertLessEqual(added, {"SETUID", "SETGID", "DAC_OVERRIDE", "CHOWN", "FOWNER", "KILL"})
        self.assertEqual(a[a.index("--network") + 1], "none")
        self.assertEqual(a[a.index("--cap-drop") + 1], "ALL")
        self.assertIn("no-new-privileges", a)


if __name__ == "__main__":
    unittest.main()
