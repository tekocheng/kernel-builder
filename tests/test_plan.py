from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kernel_plan", ROOT / "scripts" / "plan.py")
assert SPEC and SPEC.loader
plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plan)


class PlanResolutionTests(unittest.TestCase):
    def test_custom_source_source_ref_takes_precedence(self) -> None:
        args = SimpleNamespace(
            custom_repo="owner/kernel",
            source_ref="override-sha",
            custom_ref="custom-branch",
            custom_fetch="git",
            custom_kernel_path="",
        )
        entry = plan.source_entry("custom", args)
        self.assertEqual(entry["repo"], "owner/kernel")
        self.assertEqual(entry["ref"], "override-sha")
        self.assertEqual(entry["kernel_path"], ".")

    def test_custom_repo_rejects_unsupported_http_url(self) -> None:
        args = SimpleNamespace(
            custom_repo="http://example.invalid/kernel.git",
            source_ref="",
            custom_ref="main",
            custom_fetch="git",
            custom_kernel_path="",
        )
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.source_entry("custom", args)

    def test_custom_manifest_default_path(self) -> None:
        args = SimpleNamespace(
            custom_repo="owner/manifest",
            source_ref="",
            custom_ref="manifest-branch",
            custom_fetch="manifest",
            custom_kernel_path="",
        )
        entry = plan.source_entry("custom", args)
        self.assertEqual(entry["manifest_ref"], "manifest-branch")
        self.assertEqual(entry["kernel_path"], "kernel_platform/xiaomi/sm8450")

    def test_manager_susfs_specific_ref(self) -> None:
        result = plan.resolve_manager("sukisu-ultra", True, "")
        self.assertEqual(result["MANAGER_REF"], "builtin")
        self.assertEqual(result["ENABLE_SUSFS"], "true")

    def test_toolchain_custom_url_hash_and_sha(self) -> None:
        name, entry = plan.resolve_toolchain(
            "auto",
            "https://example.invalid/clang.tar.xz",
            "a" * 64,
            {"toolchain": "llvm-23.1.5"},
        )
        self.assertTrue(name.startswith("custom-"))
        self.assertEqual(entry["sha256"], "a" * 64)

    def test_invalid_toolchain_sha_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.resolve_toolchain("auto", "https://example.invalid/clang.tar.xz", "bad", {})

    def test_toolchain_url_requires_valid_https_host(self) -> None:
        for url in ("https:///missing-host.tar.xz", "http://example.invalid/clang.tar.xz", "https://user:pass@example.invalid/clang.tar.xz", "https://example.invalid:bad/clang.tar.xz"):
            with self.subTest(url=url), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.resolve_toolchain("auto", url, "", {})

    def test_path_traversal_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.safe_relative_path("../../outside", "test path")


class ManifestParserTests(unittest.TestCase):
    def _manifest(self, root: Path) -> Path:
        (root / "parts").mkdir(parents=True)
        (root / "default.xml").write_text(
            """<manifest>
  <remote name="github" fetch="https://github.com/" />
  <default remote="github" revision="main" />
  <include name="parts/extra.xml" />
  <project name="vendor/kernel" path="kernel" revision="kernel-old" />
  <project name="vendor/remove-me" path="remove-me" />
  <extend-project name="vendor/kernel" path="kernel" revision="kernel-pinned" />
  <remove-project name="vendor/remove-me" />
</manifest>""",
            encoding="utf-8",
        )
        (root / "parts" / "extra.xml").write_text(
            """<manifest>
  <remote name="google" fetch="https://android.googlesource.com/" revision="refs/heads/main" />
  <project name="platform/build" path="build" remote="google" />
</manifest>""",
            encoding="utf-8",
        )
        return root / "default.xml"

    def test_include_extend_remove_and_non_github_remote(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = self._manifest(root)
            rows = plan.manifest_project_rows(xml, [], "kernel", "", root)
        self.assertEqual(
            rows,
            [
                ("https://android.googlesource.com/platform/build", "refs/heads/main", "build"),
                ("https://github.com/vendor/kernel.git", "kernel-pinned", "kernel"),
            ],
        )

    def test_kernel_revision_override_applies_only_to_kernel_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = self._manifest(root)
            rows = plan.manifest_project_rows(xml, [], "kernel", "fixed-kernel-sha", root)
        kernel = next(row for row in rows if row[2] == "kernel")
        self.assertEqual(kernel[1], "fixed-kernel-sha")

    def test_project_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = root / "default.xml"
            xml.write_text(
                '<manifest><remote name="r" fetch="https://github.com/" />'
                '<default remote="r" revision="main" />'
                '<project name="owner/kernel" path="../outside" /></manifest>',
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.manifest_project_rows(xml, [], "", "", root)

    def test_include_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = root / "default.xml"
            xml.write_text('<manifest><include name="../outside.xml" /></manifest>', encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.manifest_project_rows(xml, [], "", "", root)

    def test_include_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "default.xml").write_text('<manifest><include name="part.xml" /></manifest>', encoding="utf-8")
            (root / "part.xml").write_text('<manifest><include name="default.xml" /></manifest>', encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.manifest_project_rows(root / "default.xml", [], "", "", root)

    def test_overlapping_project_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            xml = root / "default.xml"
            xml.write_text(
                '<manifest><remote name="r" fetch="https://github.com/" />'
                '<default remote="r" revision="main" />'
                '<project name="owner/parent" path="kernel" />'
                '<project name="owner/child" path="kernel/subtree" /></manifest>',
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.manifest_project_rows(xml, [], "", "", root)


class MatrixTests(unittest.TestCase):
    def test_all_sources_and_managers_expand_cartesian_product(self) -> None:
        args = SimpleNamespace(
            all_sources="true",
            kernel_source="aospa",
            custom_repo="",
            custom_ref="",
            custom_fetch="git",
            manager="all",
            manager_ref="",
            toolchain="auto",
            toolchain_url="",
            toolchain_sha256="",
            device="marble",
            source_ref="",
            github_output="",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan.emit_matrix(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(len(payload["include"]), len(plan.SOURCES) * len(plan.MANAGERS))
        self.assertEqual(len(payload["include"]), 20)

    def test_warns_when_one_checksum_covers_different_auto_toolchains(self) -> None:
        args = SimpleNamespace(
            all_sources="true",
            kernel_source="aospa",
            custom_repo="",
            custom_ref="",
            custom_fetch="git",
            manager="kernelsu",
            manager_ref="",
            toolchain="auto",
            toolchain_url="",
            toolchain_sha256="a" * 64,
            device="marble",
            source_ref="",
            github_output="",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            plan.emit_matrix(args)
        self.assertIn("toolchain_sha256 is shared", stderr.getvalue())

    def test_matrix_rejects_invalid_toolchain_checksum_before_scheduling(self) -> None:
        args = SimpleNamespace(
            all_sources="false",
            kernel_source="aospa",
            custom_repo="",
            custom_ref="",
            custom_fetch="git",
            manager="kernelsu",
            manager_ref="",
            toolchain="auto",
            toolchain_url="",
            toolchain_sha256="not-a-sha256",
            device="marble",
            source_ref="",
            github_output="",
        )
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.emit_matrix(args)


if __name__ == "__main__":
    unittest.main()
