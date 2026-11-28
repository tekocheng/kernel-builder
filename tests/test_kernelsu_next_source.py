import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kernel_plan_next", ROOT / "scripts" / "plan.py")
assert SPEC and SPEC.loader
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)
BUILD = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")


def make_kernel() -> str:
    match = re.search(r"(?ms)^make_kernel\(\) \{.*?^\}\n", BUILD)
    assert match, "make_kernel() not found in build.sh"
    return match.group(0)


class KernelSuNextUsesPershootTests(unittest.TestCase):
    def test_every_build_uses_the_pershoot_fork_with_or_without_susfs(self):
        for susfs in (True, False):
            with self.subTest(susfs=susfs):
                result = plan.resolve_manager("kernelsu-next", susfs, "")
                self.assertEqual(result["MANAGER_REPO"], "pershoot/KernelSU-Next")
                self.assertEqual(result["MANAGER_REF"], "dev-susfs")
                self.assertEqual(result["ENABLE_SUSFS"], "true" if susfs else "false")

    def test_there_is_no_fallback_left_to_a_second_source(self):
        result = plan.resolve_manager("kernelsu-next", True, "")
        self.assertEqual(result["MANAGER_SUSFS_FALLBACK_REPO"], "")
        self.assertEqual(result["MANAGER_SUSFS_FALLBACK_REF"], "")

    def test_a_manager_ref_override_still_wins(self):
        self.assertEqual(plan.resolve_manager("next", True, "abc123")["MANAGER_REF"], "abc123")

    def test_the_short_names_still_resolve(self):
        for alias in ("ksunext", "next", "kernelsu-next"):
            self.assertEqual(plan.resolve_manager(alias, False, "")["MANAGER"], "kernelsu-next")


class KsuSusfsStaysOffWithoutSusfsTests(unittest.TestCase):
    """pershoot's branch (like SukiSU Nova's builtin and BakaSU) already defines
    KSU_SUSFS, so a build that did not ask for SUSFS has to switch it off in
    every scope, not only in the patch-menu."""

    def test_the_switch_does_not_depend_on_the_ak3_style(self):
        body = make_kernel()
        match = re.search(
            r'(?ms)if \[\[ "\$\{ENABLE_SUSFS\}" == "true" \]\]; then\n'
            r'\s*\( cd "\$\{KERNEL_DIR\}" && "\$\{cfg\[@\]\}" -e KSU_SUSFS \)\n'
            r"\s*else\n(?P<other>.*?)\n\s*fi\n",
            body,
        )
        self.assertIsNotNone(match, "KSU_SUSFS switch block not found in make_kernel()")
        self.assertIn("-d KSU_SUSFS", match.group("other"))
        self.assertNotIn("AK3_STYLE", match.group("other"))


if __name__ == "__main__":
    unittest.main()
