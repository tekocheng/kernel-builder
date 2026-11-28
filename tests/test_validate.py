import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def load_validate(root: Path):
    spec = importlib.util.spec_from_file_location("validate_under_test", REPO / "scripts" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = root
    return module


class WorkflowConsistencyTests(unittest.TestCase):
    """validate.py has to notice when build.yml (the simple menu) drifts from
    build-advanced.yml or from config/, because nothing else compares them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo"
        shutil.copytree(REPO, self.root, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.validate = load_validate(self.root)
        self.simple = self.root / ".github" / "workflows" / "build.yml"

    def change_simple(self, old: str, new: str):
        text = self.simple.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1, f"{old!r} must appear exactly once in build.yml")
        self.simple.write_text(text.replace(old, new), encoding="utf-8")

    def assert_rejected(self, fragment: str):
        with self.assertRaises(self.validate.ValidationError) as caught:
            self.validate.validate()
        self.assertIn(fragment, str(caught.exception))

    def test_the_repository_as_shipped_is_valid(self):
        self.assertTrue(self.validate.validate())

    def test_a_source_missing_from_the_simple_menu_is_rejected(self):
        self.change_simple("          - melt\n", "")
        self.assert_rejected("build.yml choice 'kernel_source'")

    def test_a_scope_missing_from_the_simple_menu_is_rejected(self):
        self.change_simple("          - image-menu\n", "")
        self.assert_rejected("build.yml choice 'build_scope'")

    def test_the_simple_menu_must_not_offer_a_custom_source(self):
        self.change_simple("          - melt\n", "          - melt\n          - custom\n")
        self.assert_rejected("build.yml choice 'kernel_source'")

    def test_an_input_that_is_not_forwarded_is_rejected(self):
        self.change_simple("      build_bakasu: ${{ inputs.build_bakasu }}\n", "")
        self.assert_rejected("never forwarded")

    def test_forwarding_an_undeclared_input_is_rejected(self):
        self.change_simple("${{ inputs.draft_release }}", "${{ inputs.no_such_input }}")
        self.assert_rejected("forwards inputs it does not declare")

    def test_passing_an_input_the_called_workflow_lacks_is_rejected(self):
        self.change_simple("      ccache: true\n", "      ccache: true\n      no_such_input: 1\n")
        self.assert_rejected("does not declare for workflow_call")

    def test_more_than_25_dispatch_inputs_are_rejected(self):
        # More than the limit no matter how many inputs build.yml declares today.
        extra = "".join(
            f"      extra_{n}:\n        type: boolean\n        default: false\n" for n in range(26)
        )
        self.change_simple("\npermissions:\n", extra + "\npermissions:\n")
        self.assert_rejected("allows at most 25")

    def test_a_manager_field_nothing_reads_is_rejected(self):
        path = self.root / "config" / "managers.json"
        managers = json.loads(path.read_text(encoding="utf-8"))
        managers["kernelsu-next"]["susfs_fallback_repo"] = "owner/repo"
        path.write_text(json.dumps(managers), encoding="utf-8")
        self.assert_rejected("unknown fields ['susfs_fallback_repo']")


if __name__ == "__main__":
    unittest.main()
