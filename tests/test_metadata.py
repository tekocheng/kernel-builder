from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("write_metadata", ROOT / "scripts" / "write_metadata.py")
assert SPEC and SPEC.loader
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)


class MetadataTests(unittest.TestCase):
    def test_writes_build_manifest_and_checksum_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            release = Path(temp)
            (release / "sample.zip").write_bytes(b"kernel zip")
            (release / "kernel-commit.txt").write_text("abc123\n", encoding="utf-8")
            (release / "manager-commit.txt").write_text("def456\n", encoding="utf-8")
            (release / "project-commits.tsv").write_text(
                "kernel\thttps://example.invalid/kernel.git\tmain\tabc123\n", encoding="utf-8"
            )
            env = {
                "DEVICE": "marble",
                "ARCH": "arm64",
                "DEVICE_NAME_1": "marble",
                "SOURCE_KEY": "aosp",
                "SOURCE_DISPLAY": "AOSP",
                "FETCH": "git",
                "KERNEL_REPO": "owner/kernel",
                "KERNEL_REF": "main",
                "KERNEL_PATH": ".",
                "MANAGER": "kernelsu",
                "MANAGER_DISPLAY": "KernelSU",
                "MANAGER_REPO": "tiann/KernelSU",
                "MANAGER_REF": "main",
                "MANAGER_EFFECTIVE_REPO": "pershoot/KernelSU-Next",
                "MANAGER_EFFECTIVE_REF": "dev-susfs",
                "ENABLE_SUSFS": "false",
                "ENABLE_NOMOUNT": "false",
                "TOOLCHAIN": "llvm-23.1.5",
                "LTO": "thin",
                "BUILD_SCOPE": "image-only",
                "USE_CCACHE": "true",
            }
            with patch.dict(os.environ, env), patch("sys.argv", ["write_metadata.py", "--release-dir", str(release), "--zip-name", "sample.zip"]):
                metadata.main()
            result = json.loads((release / "build-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["source"]["commit"], "abc123")
            self.assertEqual(result["manager"]["commit"], "def456")
            self.assertEqual(result["manager"]["effective_repository"], "pershoot/KernelSU-Next")
            self.assertEqual(result["manager"]["effective_revision"], "dev-susfs")
            self.assertEqual(result["source"]["manifest_projects"][0]["path"], "kernel")
            info = (release / "build-info.txt").read_text(encoding="utf-8")
            self.assertIn("zip_sha256:", info)
            self.assertIn("build_manifest: build-manifest.json", info)


if __name__ == "__main__":
    unittest.main()
