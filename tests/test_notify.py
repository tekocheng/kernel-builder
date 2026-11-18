import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "notify_telegram.sh"

STUB = """#!/usr/bin/env bash
printf '%s\n' "$@" > "$STUB_DIR/args.txt"
cat > "$STUB_DIR/stdin.txt"
exit "${STUB_EXIT:-0}"
"""


class NotifyTelegramTests(unittest.TestCase):
    def run_script(self, tmp: Path, **env: str) -> subprocess.CompletedProcess:
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        curl.write_text(STUB)
        curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
        full_env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STUB_DIR": str(tmp),
            "RELEASE_DIR": str(tmp / "release"),
            "DEVICE": "marble",
            "SOURCE": "aospa",
            "MANAGER": "kernelsu",
            "RUN_NUMBER": "62",
            "RUN_URL": "https://example.invalid/run/1",
        }
        full_env.update(env)
        return subprocess.run(["bash", str(SCRIPT)], env=full_env, capture_output=True, text=True)

    def test_skips_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            result = self.run_script(tmp, JOB_STATUS="success")
            self.assertEqual(result.returncode, 0)
            self.assertIn("skipped", result.stdout)
            self.assertFalse((tmp / "args.txt").exists())

    def test_failure_message_and_token_not_in_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "release").mkdir()
            (tmp / "release" / "kernel-release.txt").write_text("5.10.272-vertex-gabc-ab1\n")
            (tmp / "release" / "marble-aospa-r62.zip").write_text("x")
            result = self.run_script(
                tmp, JOB_STATUS="failure", TELEGRAM_BOT_TOKEN="123:SECRET", TELEGRAM_CHAT_ID="42"
            )
            self.assertEqual(result.returncode, 0)
            args = (tmp / "args.txt").read_text()
            self.assertIn("\u274c Build failed: marble / aospa / kernelsu (r62)", args)
            self.assertIn("uname: 5.10.272-vertex-gabc-ab1", args)
            self.assertIn("zip: marble-aospa-r62.zip", args)
            self.assertNotIn("SECRET", args)
            self.assertIn("bot123:SECRET/sendMessage", (tmp / "stdin.txt").read_text())

    def test_success_and_cancelled_icons(self) -> None:
        for status, expected in (("success", "\u2705 Build succeeded"), ("cancelled", "\u26a0\ufe0f Build cancelled")):
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d)
                self.run_script(tmp, JOB_STATUS=status, TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")
                self.assertIn(expected, (tmp / "args.txt").read_text())

    def test_send_failure_never_fails_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self.run_script(
                Path(d), JOB_STATUS="success", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1", STUB_EXIT="22"
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("::warning::", result.stdout)


if __name__ == "__main__":
    unittest.main()
