import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")

GOOD = """--- a/kernel/one.c
+++ b/kernel/one.c
@@ -1,5 +1,5 @@
 a
-b
+B
 c
 d
 e
"""
BAD = GOOD.replace("-b\n", "-NOTB\n")


def apply_patch_function() -> str:
    match = re.search(r"(?ms)^apply_patch\(\) \{.*?^\}\n", BUILD)
    assert match, "apply_patch() not found in build.sh"
    return match.group(0)


@unittest.skipUnless(shutil.which("patch") and shutil.which("awk"), "needs patch and awk")
class ApplyPatchTests(unittest.TestCase):
    def run_patch(self, patch_text: str):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "tree" / "kernel").mkdir(parents=True)
            (tmp / "tree" / "kernel" / "one.c").write_text("a\nb\nc\nd\ne\n")
            (tmp / "x.patch").write_text(patch_text)
            script = (
                "log() { printf '%s\\n' \"$*\"; }\n"
                "die() { printf '::error::%s\\n' \"$*\" >&2; exit 1; }\n"
                + apply_patch_function()
                + f'apply_patch "{tmp}/tree" "{tmp}/x.patch"; echo "rc=$?"\n'
            )
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
            return result, (tmp / "tree" / "kernel" / "one.c").read_text()

    def test_a_matching_patch_is_applied(self):
        result, content = self.run_patch(GOOD)
        self.assertIn("rc=0", result.stdout)
        self.assertIn("B", content)
        self.assertNotIn("::group::", result.stdout)

    def test_a_failing_patch_names_the_file_and_the_hunk(self):
        result, content = self.run_patch(BAD)
        self.assertIn("rc=1", result.stdout)
        self.assertIn("::group::Why x.patch does not apply", result.stdout)
        self.assertIn("kernel/one.c", result.stdout)
        self.assertIn("Hunk #1 FAILED", result.stdout)
        self.assertEqual(content, "a\nb\nc\nd\ne\n")


if __name__ == "__main__":
    unittest.main()
