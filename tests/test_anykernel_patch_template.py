import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ak3" / "anykernel-patch.sh"
RENDER = ROOT / "scripts" / "render_ak3.py"
REQUIRED = ("BLOCK", "IS_SLOT_DEVICE", "RAMDISK_COMPRESSION", "PATCH_VBMETA_FLAG")


def render(text: str) -> str:
    return (
        text.replace("__KERNEL_STRING__", "test")
        .replace("__DEVICE_NAME_1__", "marble")
        .replace("__DEVICE_NAME_2__", "marblein")
    )


def helper_functions(text: str) -> str:
    """The menu and patch helpers: everything between the key constants and the backup helper."""
    start = text.index("KEYCODE_UP=42;")
    end = text.index("# Keep a copy of the current boot image")
    return text[start:end]


class PatchTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def test_uses_uppercase_variables_only(self):
        for name in REQUIRED:
            self.assertRegex(self.text, rf"(?m)^{name}=", name)
            self.assertIsNone(re.search(rf"(?m)^{name.lower()}=", self.text), name)

    def test_core_is_sourced_before_boot_is_split_and_flashed(self):
        core = self.text.index(". tools/ak3-core.sh;")
        split = self.text.index("split_boot;")
        flash = self.text.index("flash_boot;")
        self.assertLess(core, split)
        self.assertLess(split, flash)

    def test_image_is_checked_before_any_patch_is_applied(self):
        check = self.text.index('"$SHA1_STOCK" ] || abort "! Kernel image is corrupted!"')
        menu = self.text.index("ask_yes_no \\")
        self.assertLess(check, menu)

    def test_no_placeholder_other_than_the_three_known_ones(self):
        self.assertEqual(
            sorted(set(re.findall(r"__[A-Z_0-9]+__", self.text))),
            ["__DEVICE_NAME_1__", "__DEVICE_NAME_2__", "__KERNEL_STRING__"],
        )

    def test_rendered_script_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anykernel.sh"
            path.write_text(render(self.text), encoding="utf-8")
            subprocess.run(["sh", "-n", str(path)], check=True)

    def test_render_script_fills_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "anykernel.sh"
            env = dict(os.environ, AK_KERNEL_STRING="marble it's", AK_DEVICE_NAME_1="marble", AK_DEVICE_NAME_2="marblein")
            subprocess.run(["python3", str(RENDER), str(TEMPLATE), str(out)], check=True, env=env)
            rendered = out.read_text(encoding="utf-8")
            self.assertIn("device.name2=marblein", rendered)
            self.assertIn("kernel.string=marble it'\\''s", rendered)
            self.assertEqual(re.findall(r"__[A-Z_0-9]+__", rendered), [])


@unittest.skipUnless(shutil.which("timeout") and shutil.which("sha1sum"), "needs timeout and sha1sum")
class MenuBehaviourTests(unittest.TestCase):
    """Run the real helper functions with stubbed AnyKernel3 pieces."""

    def run_helpers(self, body: str, keys: list[int], extra_bin: dict[str, str] | None = None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "tools"
            bin_dir.mkdir()
            queue = tmp_path / "keys"
            queue.write_text("\n".join(str(k) for k in keys) + ("\n" if keys else ""))
            # keycheck returns the next scripted key code, or sleeps (no key pressed) when the script is empty.
            (bin_dir / "keycheck").write_text(textwrap.dedent(f"""\
                #!/bin/sh
                next=$(head -n1 {queue})
                if [ -z "$next" ]; then sleep 5; exit 0; fi
                tail -n +2 {queue} > {queue}.tmp; mv {queue}.tmp {queue}
                exit $next
            """))
            (bin_dir / "magiskboot").write_text('#!/bin/sh\n[ "$1" = sha1 ] && sha1sum "$2" | cut -d" " -f1\n')
            for name, content in (extra_bin or {}).items():
                (bin_dir / name).write_text(content)
            for f in bin_dir.iterdir():
                f.chmod(0o755)
            script = textwrap.dedent("""\
                ui_print() { while [ $# != 0 ]; do echo "UI: $1"; shift; done; }
                abort() { echo "ABORT: $*"; exit 1; }
                BIN="%s"
                KEY_TIMEOUT=1
            """) % bin_dir
            script += helper_functions(TEMPLATE.read_text(encoding="utf-8"))
            script += "\nKEY_TIMEOUT=1\n" + body
            return subprocess.run(["sh", "-c", script], capture_output=True, text=True, cwd=tmp, timeout=60)

    def test_volume_up_means_yes(self):
        result = self.run_helpers('ask_yes_no "q"; echo "rc=$?"', [42, 42])
        self.assertIn("rc=0", result.stdout)

    def test_volume_down_means_no(self):
        result = self.run_helpers('ask_yes_no "q"; echo "rc=$?"', [41, 41])
        self.assertIn("rc=1", result.stdout)

    def test_press_and_release_mismatch_asks_again(self):
        result = self.run_helpers('ask_yes_no "q"; echo "rc=$?"', [42, 41, 41, 41])
        self.assertIn("rc=1", result.stdout)

    def test_no_key_defaults_to_no(self):
        result = self.run_helpers('ask_yes_no "q"; echo "rc=$?"', [])
        self.assertIn("rc=1", result.stdout)
        self.assertIn("No key pressed", result.stdout)

    def test_apply_patch_rejects_a_wrong_source_image(self):
        body = 'echo wrong > img; apply_patch img aaaa bbbb p.p; echo "not reached"'
        result = self.run_helpers(body, [])
        self.assertIn("ABORT", result.stdout)
        self.assertNotIn("not reached", result.stdout)

    def test_apply_patch_checks_the_result(self):
        # A patcher that writes the wrong bytes must be caught by the SHA-1 check.
        fake_hpatchz = '#!/bin/sh\necho tampered > "$4"\n'
        body = textwrap.dedent("""\
            echo stock > img
            from=$(sha1 img)
            apply_patch img "$from" 0000000000000000000000000000000000000000 p.p
            echo "not reached"
        """)
        result = self.run_helpers(body, [], {"hpatchz": fake_hpatchz})
        self.assertIn("checksum mismatch", result.stdout)
        self.assertNotIn("not reached", result.stdout)


@unittest.skipUnless(shutil.which("hdiffz") and shutil.which("hpatchz"), "needs hdiffz and hpatchz on PATH")
class DiffRoundTripTests(unittest.TestCase):
    def test_diff_rebuilds_the_new_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            old = tmp_path / "old"
            new = tmp_path / "new"
            data = os.urandom(200_000)
            old.write_bytes(data)
            new.write_bytes(data[:50_000] + b"ksu" * 1000 + data[50_000:])
            patch = tmp_path / "p.p"
            subprocess.run(["hdiffz", "-m-1", "-SD", "-c-zstd-21-24", "-d", "-f", str(old), str(new), str(patch)],
                           check=True, capture_output=True)
            self.assertTrue(patch.read_bytes().startswith(b"HDIFFSF20&zstd"))
            out = tmp_path / "out"
            subprocess.run(["hpatchz", "-f", str(old), str(patch), str(out)], check=True, capture_output=True)
            self.assertEqual(out.read_bytes(), new.read_bytes())


if __name__ == "__main__":
    unittest.main()
