import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "ak3" / "anykernel.sh"
# AnyKernel3 reads only these UPPERCASE names. Lowercase ones are silently
# ignored, which leaves BLOCK empty and aborts with "Unable to determine
# partition" on every flash.
REQUIRED = ("BLOCK", "IS_SLOT_DEVICE", "RAMDISK_COMPRESSION", "PATCH_VBMETA_FLAG")
OLD_LOWERCASE = ("block", "is_slot_device", "ramdisk_compression", "patch_vbmeta_flag")


class AnyKernelTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def test_uses_uppercase_variables_only(self):
        for name in REQUIRED:
            self.assertRegex(self.text, rf"(?m)^{name}=", name)
        for name in OLD_LOWERCASE:
            self.assertIsNone(re.search(rf"(?m)^{name}=", self.text), name)

    def test_installs_kernel_only_and_sources_core_first(self):
        core = self.text.index(". tools/ak3-core.sh;")
        self.assertGreater(self.text.index("split_boot;"), core)
        self.assertGreater(self.text.index("flash_boot;"), self.text.index("split_boot;"))

    def test_rendered_script_parses(self):
        rendered = (
            self.text.replace("__KERNEL_STRING__", "test")
            .replace("__DEVICE_NAME_1__", "marble")
            .replace("__DEVICE_NAME_2__", "marblein")
        )
        self.assertEqual(re.findall(r"__[A-Z_0-9]+__", rendered), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anykernel.sh"
            path.write_text(rendered, encoding="utf-8")
            subprocess.run(["sh", "-n", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()
