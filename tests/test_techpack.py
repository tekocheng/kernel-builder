import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "techpack.sh"


class TechpackWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.kernel = self.base / "tree" / "kernel_platform" / "xiaomi" / "sm8450"
        self.modules = self.base / "tree" / "kernel_platform" / "xiaomi" / "sm8450-modules" / "qcom" / "opensource"
        self.out = self.kernel / "out"
        self.kernel.mkdir(parents=True)
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _run_helper(self, module: Path, result_file: Path):
        script = (
            'source "$1"\\n'
            'run_techpack_module "$2" "$3" 2 "$4" arm64 clang\\n'
        )
        env = os.environ.copy()
        env["TECHPACK_TEST_RESULT"] = str(result_file)
        return subprocess.run(
            ["bash", "-c", script, "test", str(HELPER), str(self.kernel), str(module), str(self.out)],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    def _write_kernel_makefile(self, body: str):
        (self.kernel / "Makefile").write_text(body)

    def test_mmrm_wrapper_passes_relative_m_root_and_kbuild_output(self):
        module = self.modules / "mmrm-driver"
        (module / "config").mkdir(parents=True)
        (module / "config" / "waipiommrm.conf").write_text("export CONFIG_MSM_MMRM=y\\n")
        (module / "Makefile").write_text(
            "KBUILD_OPTIONS += MMRM_ROOT=$(KERNEL_SRC)/$(M)\\n"
            "modules:\\n"
            "\t$(MAKE) -C $(KERNEL_SRC) M=$(M) modules $(KBUILD_OPTIONS)\\n"
        )
        self._write_kernel_makefile(
            "modules:\\n"
            "\t@printf 'M=%s\\nMMRM_ROOT=%s\\nO=%s\\n' '$(M)' '$(MMRM_ROOT)' '$(O)' > \"$(TECHPACK_TEST_RESULT)\"\\n"
            "\t@test -f '$(MMRM_ROOT)/config/waipiommrm.conf'\\n"
        )

        result_file = self.base / "result.txt"
        completed = self._run_helper(module, result_file)
        output = result_file.read_text()
        expected_m = os.path.relpath(module, self.kernel)
        self.assertIn(f"M={expected_m}", output)
        mmrm_root = next(line.split("=", 1)[1] for line in output.splitlines() if line.startswith("MMRM_ROOT="))
        self.assertEqual(Path(mmrm_root).resolve(), module.resolve())
        self.assertIn(f"O={self.out}", output)
        self.assertIn("Techpack wrapper:", completed.stdout)

    def test_parent_wrapper_builds_nested_qcacld_profile(self):
        wrapper = self.modules / "wlan" / "qcacld-3.0"
        module = wrapper / ".qca6490"
        module.mkdir(parents=True)
        (wrapper / "Makefile").write_text(
            "KERNEL_SRC ?= /lib/modules/build\\n"
            "M ?= $(shell pwd)\\n"
            "LOCAL_DEV_NAME := $(patsubst .%,%,$(lastword $(strip $(subst /, ,$(M)))))\\n"
            "KBUILD_OPTIONS := WLAN_ROOT=$(KERNEL_SRC)/$(M)\\n"
            "all:\\n"
            "\t$(MAKE) -C $(KERNEL_SRC) M=$(M) modules $(KBUILD_OPTIONS)\\n"
        )
        self._write_kernel_makefile(
            "modules:\\n"
            "\t@printf 'M=%s\\nWLAN_ROOT=%s\\n' '$(M)' '$(WLAN_ROOT)' > \"$(TECHPACK_TEST_RESULT)\"\\n"
        )

        result_file = self.base / "result-parent.txt"
        completed = self._run_helper(module, result_file)
        output = result_file.read_text()
        expected_m = os.path.relpath(module, self.kernel)
        self.assertIn(f"M={expected_m}", output)
        wlan_root = next(line.split("=", 1)[1] for line in output.splitlines() if line.startswith("WLAN_ROOT="))
        self.assertEqual(Path(wlan_root).resolve(), module.resolve())
        self.assertIn("target=all", completed.stdout)

    def test_direct_kbuild_fallback_keeps_absolute_module_path(self):
        module = self.modules / "plain-module"
        module.mkdir(parents=True)
        (module / "Kbuild").write_text("obj-m += example.o\\n")
        self._write_kernel_makefile(
            "modules:\\n"
            "\t@printf 'M=%s\\nO=%s\\n' '$(M)' '$(O)' > \"$(TECHPACK_TEST_RESULT)\"\\n"
        )

        result_file = self.base / "result-direct.txt"
        completed = self._run_helper(module, result_file)
        output = result_file.read_text()
        self.assertIn(f"M={module}", output)
        self.assertIn(f"O={self.out}", output)
        self.assertIn("Techpack direct Kbuild:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
