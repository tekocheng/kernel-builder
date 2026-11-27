import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "notify_telegram.sh"

STUB = """#!/usr/bin/env bash
printf '%s\n' "$@" >> "$STUB_DIR/args.txt"
cat > "$STUB_DIR/stdin_now.txt"
cat "$STUB_DIR/stdin_now.txt" >> "$STUB_DIR/stdin.txt"
if [ -n "${STUB_FAIL_ON:-}" ] && grep -q "$STUB_FAIL_ON" "$STUB_DIR/stdin_now.txt"; then exit 22; fi
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

    def make_release(self, tmp: Path, size: int = 10) -> Path:
        release = tmp / "release"
        release.mkdir()
        (release / "kernel-release.txt").write_text("5.10.272-vertex-gabc-ab1\n")
        zip_path = release / "marble-aospa-r62.zip"
        zip_path.write_bytes(b"x" * size)
        (release / "marble-aospa-r62.zip.sha256").write_text("a" * 64 + "  marble-aospa-r62.zip\n")
        return zip_path

    def test_success_sends_the_zip_as_a_document(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            zip_path = self.make_release(tmp)
            result = self.run_script(tmp, JOB_STATUS="success", TELEGRAM_BOT_TOKEN="123:SECRET", TELEGRAM_CHAT_ID="42")
            self.assertEqual(result.returncode, 0)
            args = (tmp / "args.txt").read_text()
            stdin = (tmp / "stdin.txt").read_text()
            self.assertIn(f"document=@{zip_path}", args)
            self.assertIn("\u2705 Build succeeded: marble / aospa / kernelsu (r62)", args)
            self.assertIn("sha256: " + "a" * 64, args)
            self.assertIn("bot123:SECRET/sendDocument", stdin)
            self.assertNotIn("sendMessage", stdin)
            self.assertNotIn("SECRET", args)

    def test_failure_does_not_send_the_zip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self.make_release(tmp)
            self.run_script(tmp, JOB_STATUS="failure", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")
            self.assertNotIn("document=@", (tmp / "args.txt").read_text())
            self.assertIn("sendMessage", (tmp / "stdin.txt").read_text())

    def test_send_zip_false_sends_only_the_message(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self.make_release(tmp)
            self.run_script(tmp, JOB_STATUS="success", SEND_ZIP="false", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")
            self.assertNotIn("document=@", (tmp / "args.txt").read_text())
            self.assertIn("sendMessage", (tmp / "stdin.txt").read_text())

    def test_empty_send_zip_variable_still_sends_the_zip(self) -> None:
        # An unset repository variable reaches the script as an empty string.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self.make_release(tmp)
            self.run_script(tmp, JOB_STATUS="success", SEND_ZIP="", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")
            self.assertIn("document=@", (tmp / "args.txt").read_text())

    def test_oversized_zip_is_not_uploaded(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self.make_release(tmp, size=2 * 1048576)
            self.run_script(tmp, JOB_STATUS="success", MAX_ZIP_BYTES="1048576", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1")
            args = (tmp / "args.txt").read_text()
            self.assertNotIn("document=@", args)
            self.assertIn("too large for Telegram", args)
            self.assertIn("sendMessage", (tmp / "stdin.txt").read_text())

    def test_failed_upload_falls_back_to_the_text_message(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self.make_release(tmp)
            result = self.run_script(
                tmp, JOB_STATUS="success", STUB_FAIL_ON="sendDocument", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1"
            )
            self.assertEqual(result.returncode, 0)
            stdin = (tmp / "stdin.txt").read_text()
            self.assertIn("sendDocument", stdin)
            self.assertIn("sendMessage", stdin)
            self.assertIn("zip upload failed", result.stdout)

    def test_send_failure_never_fails_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            result = self.run_script(
                Path(d), JOB_STATUS="success", TELEGRAM_BOT_TOKEN="t", TELEGRAM_CHAT_ID="1", STUB_EXIT="22"
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("::warning::", result.stdout)


if __name__ == "__main__":
    unittest.main()
