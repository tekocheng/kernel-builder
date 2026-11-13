import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "techpack.sh"

HEADER = """struct dsi_ctrl_other {
	bool max_hs_timer_supported;
};

struct dsi_ctrl {
	u32 pending_cmd_flags;
	bool max_hs_timer_supported;
	atomic64_t cmd_success_ts;
%s};
"""


class DsiCtrlDuplicateMemberTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.module = Path(self.tmp.name) / "msm"
        (self.module / "dsi").mkdir(parents=True)
        self.header = self.module / "dsi" / "dsi_ctrl.h"

    def tearDown(self):
        self.tmp.cleanup()

    def _fix(self):
        return subprocess.run(
            ["bash", "-c", 'source "$1"; fix_duplicate_dsi_ctrl_member "$2"', "test", str(HELPER), str(self.module)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_removes_repeat_inside_dsi_ctrl_only(self):
        self.header.write_text(HEADER % "\tbool max_hs_timer_supported;\n")
        completed = self._fix()
        text = self.header.read_text()
        self.assertEqual(text.count("bool max_hs_timer_supported;"), 2)
        self.assertEqual(text.split("struct dsi_ctrl {")[1].count("bool max_hs_timer_supported;"), 1)
        self.assertIn("Removed duplicate", completed.stdout)

    def test_clean_header_is_left_alone(self):
        original = HEADER % ""
        self.header.write_text(original)
        completed = self._fix()
        self.assertEqual(self.header.read_text(), original)
        self.assertNotIn("Removed duplicate", completed.stdout)

    def test_second_run_changes_nothing(self):
        self.header.write_text(HEADER % "\tbool max_hs_timer_supported;\n")
        self._fix()
        once = self.header.read_text()
        self._fix()
        self.assertEqual(self.header.read_text(), once)

    def test_missing_header_is_ignored(self):
        self.header.unlink(missing_ok=True)
        self._fix()


if __name__ == "__main__":
    unittest.main()
