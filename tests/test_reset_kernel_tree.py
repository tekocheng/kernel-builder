import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")


def function(name: str) -> str:
    match = re.search(rf"(?ms)^{name}\(\) \{{.*?^\}}\n", BUILD)
    assert match, f"{name}() not found in build.sh"
    return match.group(0)


@unittest.skipUnless(shutil.which("git"), "needs git")
class ResetKernelTreeTests(unittest.TestCase):
    def test_reset_removes_manager_and_susfs_changes_but_keeps_out(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "kernel"
            script = f"""
set -euo pipefail
die() {{ echo "DIE: $*" >&2; exit 1; }}
KERNEL_DIR="{tree}"
{function("reset_kernel_tree")}
git init -q "$KERNEL_DIR"; cd "$KERNEL_DIR"
mkdir -p drivers fs out
echo "obj-y += base/" > drivers/Makefile
echo "obj-y += open.o" > fs/Makefile
git add -A; git -c user.name=t -c user.email=t@t commit -q -m base
echo "keep" > out/cache.o
# what a manager and SUSFS leave behind
mkdir KernelSU; git init -q KernelSU; echo x > KernelSU/who
ln -s ../KernelSU drivers/kernelsu
echo "obj-y += kernelsu/" >> drivers/Makefile
echo "obj-y += susfs.o" >> fs/Makefile; echo s > fs/susfs.c; echo t > .scmversion
reset_kernel_tree
echo "makefile: $(cat drivers/Makefile)"
echo "fsmake: $(cat fs/Makefile)"
for p in KernelSU drivers/kernelsu fs/susfs.c .scmversion; do [ -e "$p" ] || [ -L "$p" ] && echo "LEFT: $p" || echo "gone: $p"; done
echo "out: $(cat out/cache.o)"
"""
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("makefile: obj-y += base/", result.stdout)
            self.assertIn("fsmake: obj-y += open.o", result.stdout)
            self.assertNotIn("LEFT:", result.stdout)
            self.assertIn("out: keep", result.stdout)

    def test_reset_refuses_a_tree_that_is_not_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            script = f"""
die() {{ echo "DIE: $*" >&2; exit 1; }}
KERNEL_DIR="{d}"
{function("reset_kernel_tree")}
reset_kernel_tree
"""
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a git checkout", result.stderr)


if __name__ == "__main__":
    unittest.main()
