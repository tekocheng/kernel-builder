#!/usr/bin/env python3
"""Validate repository configuration against the workflow's exposed choices."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ValidationError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Unable to read valid JSON from {path.relative_to(ROOT)}: {exc}") from exc
    require(isinstance(value, dict), f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        require(bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", key)), f"Invalid env key at {path.relative_to(ROOT)}:{number}")
        require(key not in values, f"Duplicate env key '{key}' at {path.relative_to(ROOT)}:{number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        require(not any(c in value for c in "\x00\n\r\t"), f"Control character in {key} at {path.relative_to(ROOT)}:{number}")
        values[key] = value
    return values


def workflow_choice_options(text: str, input_name: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^      {re.escape(input_name)}:\s*$", line):
            start = index
            break
    require(start is not None, f"Workflow is missing input '{input_name}'")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^      [A-Za-z0-9_-]+:\s*$", lines[index]):
            end = index
            break
    section = lines[start:end]
    type_choice = any(re.match(r"^        type:\s*choice\s*$", line) for line in section)
    if not type_choice:
        return []
    options_at = next((i for i, line in enumerate(section) if re.match(r"^        options:\s*$", line)), None)
    require(options_at is not None, f"Choice input '{input_name}' has no options list")
    result: list[str] = []
    for line in section[options_at + 1:]:
        match = re.match(r"^          -\s+([^\s#]+)\s*$", line)
        if match:
            result.append(match.group(1))
        elif line.strip() and not line.startswith("          "):
            break
    return result


def validate() -> list[str]:
    sources = read_json(ROOT / "config" / "sources.json")
    managers = read_json(ROOT / "config" / "managers.json")
    toolchains = read_json(ROOT / "config" / "toolchains.json")
    device_dir = ROOT / "config" / "devices"
    devices = {path.stem: read_env(path) for path in sorted(device_dir.glob("*.env"))}
    require(bool(devices), "No device .env files found")

    for key, source in sources.items():
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", key)), f"Invalid source key: {key}")
        require(source.get("fetch") in {"git", "manifest"}, f"Source '{key}' has invalid fetch method")
        require(bool(source.get("display")), f"Source '{key}' needs display")
        require(bool(source.get("rom")), f"Source '{key}' needs rom label")
        require(source.get("defconfig_mode", "auto") in {"auto", "single", "gki_fragments"}, f"Source '{key}' has invalid defconfig_mode")
        require(source.get("toolchain", "") in toolchains, f"Source '{key}' refers to unknown toolchain '{source.get('toolchain')}'")
        require(isinstance(source.get("builtin_nomount", False), bool), f"Source '{key}' builtin_nomount must be true or false")
        require(isinstance(source.get("uname_suffix", True), bool), f"Source '{key}' uname_suffix must be true or false")
        if source["fetch"] == "git":
            require(bool(source.get("repo")) and bool(source.get("ref")), f"Git source '{key}' needs repo and ref")
        else:
            for field in ("manifest_repo", "manifest_ref", "manifest_file", "kernel_path"):
                require(bool(source.get(field)), f"Manifest source '{key}' needs {field}")
        if source.get("defconfig_mode") == "single":
            require(bool(source.get("defconfig")), f"Single-defconfig source '{key}' needs defconfig")
        if source.get("modules_list"):
            require((ROOT / source["modules_list"]).is_file(), f"Source '{key}' modules_list does not exist: {source['modules_list']}")
        for item in source.get("extra", []):
            require(all(item.get(field) for field in ("repo", "ref", "dest")), f"Source '{key}' has an incomplete extra repository entry")
            require(not item["dest"].startswith("/") and "\\" not in item["dest"], f"Source '{key}' has unsafe extra destination '{item['dest']}'")

    for key, manager in managers.items():
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", key)), f"Invalid manager key: {key}")
        require(bool(manager.get("display")), f"Manager '{key}' needs display")
        if key == "none":
            continue
        for field in ("repo", "ref", "setup"):
            require(bool(manager.get(field)), f"Manager '{key}' needs {field}")

    for key, toolchain in toolchains.items():
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]*", key)), f"Invalid toolchain key: {key}")
        if toolchain.get("git"):
            require(str(toolchain["git"]).startswith("https://"), f"Toolchain '{key}' needs an HTTPS git URL")
            require(not toolchain.get("url"), f"Toolchain '{key}' must use either url or git, not both")
            require(bool(re.fullmatch(r"[A-Za-z0-9._-]+", str(toolchain.get("branch", "")))), f"Toolchain '{key}' needs a valid git branch")
            require(bool(re.fullmatch(r"[A-Za-z0-9._-]+", str(toolchain.get("dir", "")))), f"Toolchain '{key}' needs the clang directory name in 'dir'")
            require(not toolchain.get("sha256"), f"Toolchain '{key}' is a git toolchain, so sha256 does not apply")
        else:
            require(str(toolchain.get("url", "")).startswith("https://"), f"Toolchain '{key}' needs an HTTPS url (or git, branch and dir)")
        if "max_jobs" in toolchain:
            require(isinstance(toolchain["max_jobs"], int) and toolchain["max_jobs"] > 0, f"Toolchain '{key}' max_jobs must be a positive integer")
        if toolchain.get("sha256"):
            require(bool(re.fullmatch(r"[0-9a-fA-F]{64}", toolchain["sha256"])), f"Toolchain '{key}' sha256 must contain 64 hex characters")

    for key, device in devices.items():
        require(bool(device.get("ARCH")), f"Device '{key}' needs ARCH")
        require(bool(device.get("DEVICE_NAME_1")), f"Device '{key}' needs DEVICE_NAME_1")
        require(bool(device.get("DEFCONFIG_SINGLE") or device.get("GKI_FRAGMENTS")), f"Device '{key}' needs a defconfig or GKI fragments")
        for field in ("DEVICE_NAME_1", "DEVICE_NAME_2"):
            require(not any(c in device.get(field, "") for c in "\x00\n\r\t"), f"Device '{key}' has an invalid {field}")

    workflow_path = ROOT / ".github" / "workflows" / "build.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    advanced_workflow_path = ROOT / ".github" / "workflows" / "build-advanced.yml"
    advanced_workflow = advanced_workflow_path.read_text(encoding="utf-8")
    require("workflow_dispatch:" in workflow and "jobs:" in workflow, "build.yml must define workflow_dispatch and jobs")
    require("workflow_dispatch:" in advanced_workflow and "workflow_call:" in advanced_workflow and "jobs:" in advanced_workflow, "build-advanced.yml must define workflow_dispatch, workflow_call, and jobs")
    expected_choices = {
        "device": sorted(devices),
        "kernel_source": sorted([*sources.keys(), "custom"]),
        "toolchain": sorted(["auto", *toolchains.keys()]),
        "custom_fetch": ["git", "manifest"],
        "lto": ["full", "none", "thin"],
        "build_scope": ["full", "image-menu", "image-only"],
    }
    seen_names = {*managers.keys(), "all"}
    for key, entry in managers.items():
        for alias in entry.get("aliases", []):
            require(bool(re.fullmatch(r"[a-z0-9-]+", alias)), f"Manager '{key}' has a bad short name '{alias}'")
            require(alias not in seen_names, f"Short name '{alias}' of manager '{key}' is already used")
            seen_names.add(alias)
    for input_name, expected in expected_choices.items():
        actual = sorted(workflow_choice_options(advanced_workflow, input_name))
        require(actual == expected, f"Workflow choice '{input_name}' mismatch. Expected {expected}, found {actual}")

    # GitHub rejects a workflow_dispatch with more than 25 inputs, and the whole workflow then fails to load.
    dispatch_inputs = re.search(r"(?ms)^on:\n  workflow_dispatch:\n    inputs:\n(.*?)^(?=\S)", workflow)
    require(dispatch_inputs is not None, "Cannot find the workflow_dispatch inputs in build.yml")
    input_count = len(re.findall(r"(?m)^      [A-Za-z_][A-Za-z0-9_]*:\s*$", dispatch_inputs.group(1)))
    require(input_count <= 25, f"build.yml declares {input_count} workflow_dispatch inputs; GitHub allows at most 25")

    required_inputs = {
        "kernel_name", "all_sources", "source_ref", "custom_repo", "custom_ref", "custom_fetch",
        "custom_kernel_path", "manager_ref", "enable_susfs", "enable_nomount", "advanced_overrides",
        "lto", "build_scope", "ccache", "uname_hash", "uname_run_id", "draft_release",
    }
    for input_name in sorted(required_inputs):
        workflow_choice_options(advanced_workflow, input_name)

    anykernel = (ROOT / "ak3" / "anykernel.sh").read_text(encoding="utf-8")
    for placeholder in ("__KERNEL_STRING__", "__DEVICE_NAME_1__", "__DEVICE_NAME_2__"):
        require(anykernel.count(placeholder) == 1, f"AnyKernel template must contain exactly one {placeholder}")

    # Actions outside the "actions/" organisation run with sudo on the runner, so they must not float.
    for workflow_file in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for match in re.finditer(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)", workflow_file.read_text(encoding="utf-8")):
            reference = match.group(1)
            if reference.startswith(("actions/", "./")):
                continue
            require(
                re.fullmatch(r".+@[0-9a-f]{40}", reference) is not None,
                f"{workflow_file.name}: pin {reference} to a full commit SHA instead of a branch or tag",
            )

    patch_template = (ROOT / "ak3" / "anykernel-patch.sh").read_text(encoding="utf-8")
    for placeholder in ("__KERNEL_STRING__", "__DEVICE_NAME_1__", "__DEVICE_NAME_2__"):
        require(patch_template.count(placeholder) == 1, f"Patch-menu AnyKernel template must contain exactly one {placeholder}")
    for tool in ("hpatchz", "keycheck"):
        require((ROOT / "ak3" / "tools-extra" / tool).is_file(), f"Missing ak3/tools-extra/{tool}")

    for script in ("scripts/plan.py", "scripts/build.sh", "scripts/validate.py", "scripts/safe_extract.py", "scripts/write_metadata.py", "scripts/redact_plan.py", "scripts/render_ak3.py"):
        require((ROOT / script).is_file(), f"Missing required script: {script}")
    build_script = (ROOT / "scripts" / "build.sh").read_text(encoding="utf-8")
    require("trap redact_plan_artifact EXIT" in build_script, "build.sh must redact plan.env on every exit")

    return [
        f"Validated {len(sources)} kernel sources, {len(managers)} managers, {len(toolchains)} toolchains, and {len(devices)} device(s).",
        "Workflow dropdown choices match the configuration files.",
        "Source, manager, toolchain, device, and AnyKernel template checks passed.",
    ]


def main() -> None:
    try:
        messages = validate()
    except ValidationError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    for message in messages:
        print(f"OK: {message}")


if __name__ == "__main__":
    main()
