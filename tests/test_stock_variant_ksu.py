import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")


def make_kernel() -> str:
    match = re.search(r"(?ms)^make_kernel\(\) \{.*?^\}\n", BUILD)
    assert match, "make_kernel() not found in build.sh"
    return match.group(0)


class StockVariantHasNoKsuTests(unittest.TestCase):
    """The image-menu stock variant bootstraps a manager's Kconfig. If that
    Kconfig enables KSU by default, olddefconfig turns it on unless -d KSU is
    written explicitly, and the stock Image then equals the plain KernelSU
    Image."""

    def test_build_without_manager_turns_ksu_off_explicitly(self):
        body = make_kernel()
        match = re.search(
            r'(?ms)if \[\[ "\$\{MANAGER\}" != "none" \]\]; then\n'
            r'\s*\( cd "\$\{KERNEL_DIR\}" && "\$\{cfg\[@\]\}" -e KSU \)\n'
            r"\s*else\n(?P<other>.*?)\n\s*fi\n",
            body,
        )
        self.assertIsNotNone(match, "KSU switch block not found in make_kernel()")
        self.assertIn('-d KSU )', match.group("other"))

    def test_build_without_manager_fails_if_ksu_stays_on(self):
        body = make_kernel()
        self.assertRegex(
            body,
            r'"\$\{MANAGER\}" == "none" \]\] && grep -Eq '
            r"'\^\(CONFIG_KSU=y\|CONFIG_KSU=m\)\$' \"\$\{out\}/\.config\"",
        )

    def test_the_guard_runs_after_olddefconfig(self):
        body = make_kernel()
        self.assertLess(body.index("olddefconfig"), body.index("a build without a manager"))


if __name__ == "__main__":
    unittest.main()
