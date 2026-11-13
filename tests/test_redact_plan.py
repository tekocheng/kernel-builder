from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "redact_plan.py"


class RedactPlanTests(unittest.TestCase):
    def test_removes_query_and_fragment_from_artifact_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "plan.env"
            plan.write_text(
                "TOOLCHAIN_URL='https://downloads.example/clang.tar.xz?token=secret#fragment'\n"
                "DEVICE=marble\n",
                encoding="utf-8",
            )
            result = subprocess.run([sys.executable, str(SCRIPT), str(plan)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = plan.read_text(encoding="utf-8")
            self.assertIn("https://downloads.example/clang.tar.xz", text)
            self.assertNotIn("secret", text)
            self.assertNotIn("fragment", text)
            self.assertIn("DEVICE=marble", text)

    def test_build_script_redacts_plan_on_exit(self) -> None:
        build_script = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
        self.assertIn("trap redact_plan_artifact EXIT", build_script)
        self.assertIn('python3 "${ROOT}/scripts/redact_plan.py"', build_script)


if __name__ == "__main__":
    unittest.main()
