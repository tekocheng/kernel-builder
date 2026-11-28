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

    def test_uname_parts_are_independent_for_every_source(self) -> None:
        for key, entry in plan.SOURCES.items():
            self.assertEqual(plan.resolve_uname_parts("true", "auto", entry), (True, "auto"), key)
            self.assertEqual(plan.resolve_uname_parts("true", "off", entry), (True, "off"), key)
            self.assertEqual(plan.resolve_uname_parts("false", "auto", entry), (False, "auto"), key)
            self.assertEqual(plan.resolve_uname_parts("false", "off", entry), (False, "off"), key)

    def test_uname_run_id_accepts_custom_text_and_old_values(self) -> None:
        self.assertEqual(plan.normalize_run_id("r35"), "r35")
        self.assertEqual(plan.normalize_run_id(" vertex.1 "), "vertex.1")
        self.assertEqual(plan.normalize_run_id("true"), "auto")
        self.assertEqual(plan.normalize_run_id("false"), "off")
        for word in ("off", "none", "None", " NO "):
            self.assertEqual(plan.normalize_run_id(word), "off", word)
        self.assertEqual(plan.normalize_run_id(""), "auto")
        for bad in ("a b", "x;y", "a" * 25, "$(id)"):
            with self.subTest(value=bad), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                plan.normalize_run_id(bad)

    def test_a_source_can_still_opt_out_of_both_uname_parts(self) -> None:
        self.assertEqual(plan.resolve_uname_parts("true", "r35", {"uname_suffix": False}), (False, "off"))

    def test_shinkai_uses_its_own_fragments(self) -> None:
        device = plan.load_device("marble")
        self.assertIn("vendor/xiaomi_GKI.config", plan.fragments_for(plan.SOURCES["lineage"], device))
        shinkai = plan.fragments_for(plan.SOURCES["shinkai"], device).split()
        self.assertNotIn("vendor/xiaomi_GKI.config", shinkai)
        self.assertEqual(shinkai[-1], "vendor/extra.config")

    def test_builtin_nomount_is_opt_in_per_source(self) -> None:
        self.assertFalse(plan.builtin_nomount({}))
        self.assertFalse(plan.builtin_nomount(plan.SOURCES["infinityx"]))
        self.assertTrue(plan.builtin_nomount(plan.SOURCES["shinkai"]))

    def test_renamed_managers_keep_their_upstream_config(self) -> None:
        nova = plan.resolve_manager("sukisu-nova", True, "")
        self.assertEqual(nova["MANAGER_DISPLAY"], "SukiSU Nova")
        self.assertEqual(nova["MANAGER_REPO"], "SukiSU-Nova/SukiSU-Nova")
        self.assertEqual(nova["MANAGER_REF"], "builtin")
        self.assertEqual(nova["ENABLE_SUSFS"], "true")

        baka = plan.resolve_manager("bakasu", True, "")
        self.assertEqual(baka["MANAGER_DISPLAY"], "BakaSU")
        self.assertEqual(baka["MANAGER_REPO"], "Baka-SU/BakaSU")
        self.assertEqual(baka["MANAGER_REF"], "main")
        self.assertEqual(baka["ENABLE_SUSFS"], "true")

    def test_parse_managers_takes_a_list_with_short_names(self) -> None:
        self.assertEqual(plan.parse_managers("kernelsu,kernelsu-next,sukisu-nova"), (["kernelsu", "kernelsu-next", "sukisu-nova"], False))
        self.assertEqual(plan.parse_managers(" KSU, ksunext  sukisu ")[0], ["kernelsu", "kernelsu-next", "sukisu-nova"])
        self.assertEqual(plan.parse_managers("ksu,kernelsu,ksu")[0], ["kernelsu"])
        self.assertEqual(plan.parse_managers("next;suki")[0], ["kernelsu-next", "sukisu-nova"])

    def test_parse_managers_default_all_and_unknown(self) -> None:
        self.assertEqual(plan.parse_managers(""), (["kernelsu"], False))
        managers, picked_all = plan.parse_managers("ksu, all")
        self.assertTrue(picked_all)
        self.assertEqual(managers, list(plan.MANAGERS))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            plan.parse_managers("ksu,nope")
        self.assertIn("Unknown manager 'nope'", stderr.getvalue())

    def test_resolve_manager_accepts_a_short_name(self) -> None:
        self.assertEqual(plan.resolve_manager("ksunext", False, "")["MANAGER"], "kernelsu-next")

    def test_write_plan_takes_a_list_only_for_image_menu(self) -> None:
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = ["python3", str(Path(plan.__file__)), "write-plan", "--device", "marble", "--kernel-source", "aospa",
                    "--manager", "ksu,ksunext,sukisu", "--lto", "thin", "--out", f"{tmp}/plan.env"]
            refused = subprocess.run(base + ["--build-scope", "image-only"], capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("needs build_scope=image-menu", refused.stderr)
            accepted = subprocess.run(base + ["--build-scope", "image-menu"], capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            text = (Path(tmp) / "plan.env").read_text()
            self.assertIn("MANAGER=kernelsu\n", text)
            self.assertIn("MANAGER_LIST='kernelsu kernelsu-next sukisu-nova'", text)
            self.assertIn("SUSFS_REQUESTED=true", text)

    def test_manager_env_describes_one_manager(self) -> None:
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "m.env"
            result = subprocess.run(
                ["python3", str(Path(plan.__file__)), "manager-env", "--manager", "next", "--susfs", "true", "--out", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text()
            self.assertIn("MANAGER=kernelsu-next", text)
            self.assertIn("ENABLE_SUSFS=true", text)

    def test_android_toolchain_is_the_official_google_git_checkout(self) -> None:
        name, entry = plan.resolve_toolchain("android-r596125", "", "", {})
        self.assertEqual(name, "android-r596125")
        self.assertEqual(entry["git"], "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86")
        self.assertEqual(entry["branch"], "main-kernel")
        self.assertEqual(entry["dir"], "clang-r596125")
        self.assertNotIn("url", entry)

    def test_git_toolchain_rejects_an_archive_checksum(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.resolve_toolchain("android-r596125", "", "a" * 64, {})

    def test_git_toolchain_picked_by_a_source_ignores_a_shared_checksum(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            name, entry = plan.resolve_toolchain("auto", "", "a" * 64, {"toolchain": "android-r596125"})
        self.assertEqual(name, "android-r596125")
        self.assertNotIn("sha256", entry)
        self.assertIn("ignored for the git toolchain", stderr.getvalue())

    def test_toolchain_url_still_wins_over_a_git_toolchain(self) -> None:
        name, entry = plan.resolve_toolchain("android-r596125", "https://example.invalid/clang.tar.xz", "", {})
        self.assertTrue(name.startswith("custom-"))
        self.assertEqual(entry["url"], "https://example.invalid/clang.tar.xz")
        self.assertNotIn("git", entry)

    def test_toolchain_custom_url_hash_and_sha(self) -> None:
        name, entry = plan.resolve_toolchain(
            "auto",
            "https://example.invalid/clang.tar.xz",
            "a" * 64,
            {"toolchain": "llvm-slim-23.1.6"},
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
                plan.manifest_project_rows(xml, [], "kernel", "", root)

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
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            plan.emit_matrix(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(len(payload["include"]), len(plan.SOURCES) * len(plan.MANAGERS))
        self.assertEqual(len(plan.SOURCES) * len(plan.MANAGERS), 35)

    def matrix_args(self, **overrides) -> SimpleNamespace:
        values = dict(
            all_sources="false",
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
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_image_menu_skips_the_none_manager(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan.emit_matrix(self.matrix_args(build_scope="image-menu"))
        rows = json.loads(output.getvalue())["include"]
        self.assertEqual(len(rows), 1)
        managers = rows[0]["manager"].split(",")
        self.assertNotIn("none", managers)
        expected = sorted(m for m in plan.MANAGERS if m != "none")
        self.assertEqual(sorted(managers), expected)

    def test_image_menu_rejects_manager_none(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            plan.emit_matrix(self.matrix_args(manager="none", build_scope="image-menu"))

    def test_a_manager_list_expands_to_those_managers_only(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan.emit_matrix(self.matrix_args(manager="ksu,ksunext,sukisu"))
        rows = json.loads(output.getvalue())["include"]
        self.assertEqual([row["manager"] for row in rows], ["kernelsu", "kernelsu-next", "sukisu-nova"])

    def test_image_menu_leaves_none_out_of_a_list(self) -> None:
        output, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(stderr):
            plan.emit_matrix(self.matrix_args(manager="none,ksu", build_scope="image-menu"))
        self.assertEqual([row["manager"] for row in json.loads(output.getvalue())["include"]], ["kernelsu"])
        self.assertIn("Leaving 'none' out", stderr.getvalue())

    def test_image_menu_is_one_job_per_source_with_every_manager(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan.emit_matrix(self.matrix_args(manager="ksu,ksunext,sukisu", build_scope="image-menu"))
        self.assertEqual(
            json.loads(output.getvalue())["include"],
            [{"source": "aospa", "manager": "kernelsu,kernelsu-next,sukisu-nova"}],
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan.emit_matrix(self.matrix_args(manager="ksu,ksunext", all_sources="true", build_scope="image-menu"))
        rows = json.loads(output.getvalue())["include"]
        self.assertEqual(len(rows), len(plan.SOURCES))
        self.assertTrue(all(row["manager"] == "kernelsu,kernelsu-next" for row in rows))

    def test_other_scopes_keep_the_none_manager(self) -> None:
        for scope in ("image-only", "full"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                plan.emit_matrix(self.matrix_args(build_scope=scope))
            managers = [row["manager"] for row in json.loads(output.getvalue())["include"]]
            self.assertIn("none", managers, scope)

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
