from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = ROOT / "scripts" / "safe_extract.py"


class SafeExtractTests(unittest.TestCase):
    def test_extracts_normal_tar_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "toolchain.tar.gz"
            output = root / "out"
            with tarfile.open(archive, "w:gz") as tar:
                data = b"#!/bin/sh\necho clang\n"
                info = tarfile.TarInfo("clang/bin/clang")
                info.mode = 0o755
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            result = subprocess.run([sys.executable, str(EXTRACTOR), str(archive), str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / "clang/bin/clang").is_file())

    def test_rejects_archive_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "malicious.tar.gz"
            output = root / "out"
            with tarfile.open(archive, "w:gz") as tar:
                data = b"owned"
                info = tarfile.TarInfo("../../outside.txt")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            result = subprocess.run([sys.executable, str(EXTRACTOR), str(archive), str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "outside.txt").exists())
            self.assertIn("Unsafe archive path", result.stderr)

    def test_rejects_symlink_target_outside_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "symlink.tar.gz"
            output = root / "out"
            with tarfile.open(archive, "w:gz") as tar:
                link = tarfile.TarInfo("clang/bin/clang")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../../../outside"
                tar.addfile(link)
            result = subprocess.run([sys.executable, str(EXTRACTOR), str(archive), str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Archive symlink escapes destination", result.stderr)


if __name__ == "__main__":
    unittest.main()
