#!/usr/bin/env python3
"""Resolve builder inputs into a shell env file, a fetch list, or an Actions matrix.

Adding a kernel is a block in config/sources.json. Adding a device is
config/devices/<name>.env. This file does not need a workflow edit.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
MANAGERS = json.loads((ROOT / "config" / "managers.json").read_text(encoding="utf-8"))
TOOLCHAINS = json.loads((ROOT / "config" / "toolchains.json").read_text(encoding="utf-8"))
MANAGER_ALIASES = {alias.lower(): key for key, entry in MANAGERS.items() for alias in entry.get("aliases", [])}


class PlanError(Exception):
    """An invalid build plan or unsupported manifest construct."""


def die(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def require_single_line(value: str, label: str) -> str:
    value = str(value)
    if any(char in value for char in ("\x00", "\n", "\r", "\t")):
        die(f"{label} must not contain NUL, newline, carriage return, or tab characters")
    return value



def validate_repo_target(value: str, label: str) -> str:
    """Accept owner/repo shorthand or an explicit HTTPS/SSH/Git URL."""
    value = require_single_line(value.strip(), label)
    if not value:
        die(f"{label} must not be empty")
    if "://" in value:
        try:
            parsed = urllib.parse.urlsplit(value)
            _ = parsed.port
        except ValueError as exc:
            die(f"Invalid {label}: {exc}")
        if parsed.scheme not in {"https", "ssh", "git"} or not parsed.hostname:
            die(f"{label} must be an owner/repository or a valid HTTPS, SSH, or git:// URL")
        return value
    if value.startswith("git@"):
        if not re.fullmatch(r"git@[^:/\s]+:.+", value):
            die(f"Invalid SSH repository target in {label}: {value!r}")
        return value
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", value):
        die(f"{label} must be owner/repository or a supported Git URL")
    return value

def safe_relative_path(value: str, label: str, *, allow_dot: bool = False) -> str:
    """Validate a POSIX path that will be used below a checked-out source tree."""
    value = require_single_line(value.strip(), label)
    if "\\" in value:
        die(f"{label} must use POSIX '/' separators, not backslashes")
    path = PurePosixPath(value or ".")
    if path.is_absolute() or any(part == ".." for part in path.parts):
        die(f"Unsafe {label}: {value!r}; absolute paths and '..' are not allowed")
    normalized = str(path)
    if normalized == "." and not allow_dot:
        die(f"{label} must be a non-empty relative path")
    return normalized


def load_device(name: str) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        die(f"Invalid device key '{name}'")
    path = ROOT / "config" / "devices" / f"{name}.env"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ROOT / "config" / "devices").glob("*.env")))
        die(f"Unknown device '{name}'. Known devices: {known}")
    env: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            die(f"Invalid key '{key}' in {path.relative_to(ROOT)}:{line_number}")
        if key in env:
            die(f"Duplicate key '{key}' in {path.relative_to(ROOT)}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        require_single_line(value, f"{key} in {path.relative_to(ROOT)}:{line_number}")
        env[key] = value
    return env


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def uname_suffix_enabled(entry: dict) -> bool:
    """A source can set "uname_suffix": false to keep the kernel release string untouched."""
    return entry.get("uname_suffix", True) is not False


UNAME_TEXT = re.compile(r"[A-Za-z0-9._-]{1,24}")


def normalize_run_id(value: str) -> str:
    """auto (-ab<run id>), off (also none or no), or a custom text. The old true and false values still work."""
    text = (value or "").strip()
    if text.lower() in ("", "auto", "true"):
        return "auto"
    if text.lower() in ("off", "false", "none", "no"):
        return "off"
    if not UNAME_TEXT.fullmatch(text):
        die("uname_run_id must be auto, off, none, or 1 to 24 characters from letters, digits, dot, underscore and dash.")
    return text


def resolve_uname_parts(hash_on: str, run_id: str, entry: dict) -> tuple[bool, str]:
    """The two workflow inputs decide; a source can still opt out of both with "uname_suffix": false."""
    if not uname_suffix_enabled(entry):
        return False, "off"
    return truthy(hash_on), normalize_run_id(run_id)


def builtin_nomount(entry: dict) -> bool:
    """A source can set "builtin_nomount": true when NoMount is already part of its kernel tree."""
    return entry.get("builtin_nomount", False) is True


def source_entry(key: str, args: argparse.Namespace) -> dict:
    if key not in SOURCES:
        die(f"Unknown kernel source '{key}'. Known: {', '.join(SOURCES)}")
    return SOURCES[key]


def canonical_manager(name: str) -> str:
    """A manager key or one of its short names (ksu, ksunext, sukisu, ...) as the manager key."""
    text = name.strip().lower()
    if text in MANAGERS:
        return text
    if text in MANAGER_ALIASES:
        return MANAGER_ALIASES[text]
    short = ", ".join(sorted(MANAGER_ALIASES))
    die(f"Unknown manager '{name.strip()}'. Known: {', '.join(MANAGERS)}; short names: {short}; or all")
    raise AssertionError("unreachable")


def parse_managers(text: str) -> tuple[list[str], bool]:
    """Managers from a comma or space separated list, in the order given, and whether 'all' was used."""
    parts = [part for part in re.split(r"[,;\s]+", (text or "").strip().lower()) if part]
    if not parts:
        parts = ["kernelsu"]
    if "all" in parts:
        return list(MANAGERS), True
    managers: list[str] = []
    for part in parts:
        key = canonical_manager(part)
        if key not in managers:
            managers.append(key)
    return managers, False


def resolve_manager(name: str, susfs: bool, manager_ref: str) -> dict[str, str]:
    name = canonical_manager(name)
    entry = MANAGERS[name]
    if name == "none":
        return {
            "MANAGER": "none",
            "MANAGER_DISPLAY": entry["display"],
            "MANAGER_REPO": "",
            "MANAGER_REF": "",
            "MANAGER_SETUP": "",
            "ENABLE_SUSFS": "false",
        }
    ref = require_single_line(manager_ref.strip(), "manager_ref")
    if not ref:
        ref = entry.get("susfs_ref") if susfs and entry.get("susfs_ref") else entry.get("ref", "")
    enabled = "true" if susfs and entry.get("susfs", False) else "false"
    if susfs and not entry.get("susfs", False):
        print(f"::warning::{entry['display']} has no SUSFS support; building without it", file=sys.stderr)
    return {
        "MANAGER": name,
        "MANAGER_DISPLAY": entry["display"],
        "MANAGER_REPO": entry.get("repo", ""),
        "MANAGER_REF": ref,
        "MANAGER_SETUP": entry.get("setup", ""),
        "ENABLE_SUSFS": enabled,
    }


def resolve_toolchain(name: str, source: dict) -> tuple[str, dict]:
    """Return (toolchain name, entry). auto uses the source preset, then the default in config/toolchains.json."""
    name = name.strip() or "auto"
    if name == "auto":
        defaults = [key for key, value in TOOLCHAINS.items() if value.get("default")]
        name = source.get("toolchain") or (defaults[0] if defaults else "")
    if name not in TOOLCHAINS:
        die(f"Unknown toolchain '{name}'. Known: auto, {', '.join(TOOLCHAINS)}. Add it to config/toolchains.json")
    return name, dict(TOOLCHAINS[name])


def fragments_for(entry: dict, device: dict[str, str]) -> str:
    if entry.get("config_fragments"):
        return " ".join(entry["config_fragments"])
    return device.get("GKI_FRAGMENTS", "")


def write_plan(args: argparse.Namespace) -> None:
    device = load_device(args.device)
    entry = source_entry(args.kernel_source, args)
    susfs = truthy(args.susfs)
    nomount = truthy(args.nomount)
    managers, picked_all = parse_managers(args.manager)
    if picked_all:
        die("manager=all is expanded by the matrix job. Pass one manager, or a list with build_scope=image-menu.")
    if len(managers) > 1 and args.build_scope != "image-menu":
        die("A manager list needs build_scope=image-menu. Otherwise every manager is its own job.")
    # Resolve all of them now, so a blocked or unknown one stops the run before any download.
    resolved = [resolve_manager(name, susfs, args.manager_ref) for name in managers]
    manager = resolved[0]
    mode = entry.get("defconfig_mode", "auto")
    toolchain, toolchain_entry = resolve_toolchain(args.toolchain, entry)
    if args.lto not in {"none", "thin", "full"}:
        die("lto must be none, thin, or full")
    if args.build_scope not in {"image-only", "full", "image-menu"}:
        die("build_scope must be image-only, full or image-menu")

    fetch = entry.get("fetch", "git")
    if fetch == "git":
        kernel_path = safe_relative_path(entry.get("kernel_path", "."), "kernel_path", allow_dot=True)
    elif fetch == "manifest":
        kernel_path = safe_relative_path(entry.get("kernel_path", ""), "manifest kernel_path")
    else:
        die(f"Unsupported fetch method '{fetch}' for {args.kernel_source}")

    kernel_ref = entry.get("ref", "")
    if fetch == "git" and args.source_ref.strip():
        kernel_ref = args.source_ref.strip()
    kernel_ref = require_single_line(kernel_ref, "kernel_ref")
    kernel_name = require_single_line(args.kernel_name.strip() or device.get("KERNEL_NAME", ""), "kernel_name")

    values = {
        "DEVICE": args.device,
        "ARCH": device.get("ARCH", "arm64"),
        "DEVICE_NAME_1": device.get("DEVICE_NAME_1", args.device),
        "DEVICE_NAME_2": device.get("DEVICE_NAME_2", ""),
        "KERNEL_NAME": kernel_name,
        "DEFCONFIG_SINGLE": entry.get("defconfig") or device.get("DEFCONFIG_SINGLE", ""),
        "GKI_FRAGMENTS": fragments_for(entry, device),
        "SOURCE_KEY": args.kernel_source,
        "SOURCE_DISPLAY": entry.get("display", args.kernel_source),
        "ROM_LABEL": entry.get("rom", ""),
        "FETCH": fetch,
        "KERNEL_REPO": entry.get("repo", ""),
        "KERNEL_REF": kernel_ref,
        "KERNEL_PATH": kernel_path,
        "MANIFEST_REPO": entry.get("manifest_repo", ""),
        "MANIFEST_REF": entry.get("manifest_ref", ""),
        "MANIFEST_FILE": entry.get("manifest_file", "default.xml"),
        "MANIFEST_SKIP": " ".join(entry.get("manifest_skip", [])),
        "SOURCE_REF_OVERRIDE": require_single_line(args.source_ref.strip(), "source_ref"),
        "DEFCONFIG_MODE": mode,
        "UNAME_HASH": "true" if resolve_uname_parts(getattr(args, "uname_hash", "true"), getattr(args, "uname_run_id", "true"), entry)[0] else "false",
        "UNAME_RUN_ID": resolve_uname_parts(getattr(args, "uname_hash", "true"), getattr(args, "uname_run_id", "auto"), entry)[1],
        "BUILTIN_NOMOUNT": "true" if builtin_nomount(entry) else "false",
        "TOOLCHAIN": toolchain,
        "TOOLCHAIN_URL": toolchain_entry.get("url", ""),
        "TOOLCHAIN_GIT": toolchain_entry.get("git", ""),
        "TOOLCHAIN_GIT_BRANCH": toolchain_entry.get("branch", ""),
        "TOOLCHAIN_GIT_DIR": toolchain_entry.get("dir", ""),
        "TOOLCHAIN_SHA256": toolchain_entry.get("sha256", ""),
        "TOOLCHAIN_MAX_JOBS": str(toolchain_entry.get("max_jobs", "")),
        "LTO": args.lto,
        "BUILD_SCOPE": args.build_scope,
        "MODULES_SRC": entry.get("modules_src", ""),
        "MODULES_LIST": entry.get("modules_list", ""),
        "SUSFS_REPO": device.get("SUSFS_REPO", "https://gitlab.com/simonpunk/susfs4ksu.git"),
        "SUSFS_BRANCH": args.susfs_branch.strip() or device.get("SUSFS_BRANCH", "gki-android12-5.10"),
        "SUSFS_REF": require_single_line(args.susfs_ref.strip(), "susfs_ref"),
        "ENABLE_NOMOUNT": "true" if nomount else "false",
        "NOMOUNT_REPO": device.get("NOMOUNT_REPO", "https://github.com/maxsteeel/nomount"),
        "NOMOUNT_REF": require_single_line(args.nomount_ref.strip() or device.get("NOMOUNT_REF", "dev"), "nomount_ref"),
        "ANYKERNEL_REPO": device.get("ANYKERNEL_REPO", "https://github.com/osm0sis/AnyKernel3.git"),
        "ANYKERNEL_REF": device.get("ANYKERNEL_REF", "master"),
        "KBUILD_BUILD_USER": device.get("KBUILD_BUILD_USER", args.device),
        "KBUILD_BUILD_HOST": device.get("KBUILD_BUILD_HOST", "github-actions"),
        "USE_CCACHE": "true" if truthy(args.ccache) else "false",
    }
    values.update(manager)
    values["MANAGER_LIST"] = " ".join(managers)
    values["SUSFS_REQUESTED"] = "true" if susfs else "false"
    for key, value in values.items():
        require_single_line(str(value), key)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={shlex.quote(str(value))}" for key, value in values.items()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    extra_path = out.parent / "extra.tsv"
    rows = []
    for item in entry.get("extra", []):
        dest = require_single_line(item.get("dest", ""), "extra repository destination")
        repo = require_single_line(item.get("repo", ""), "extra repository URL")
        ref = require_single_line(item.get("ref", ""), "extra repository ref")
        if not repo or not dest or not ref:
            die(f"extra repo entry for {args.kernel_source} needs repo, ref, and dest")
        if "\\" in dest or dest.startswith("/"):
            die(f"Unsafe extra repository destination: {dest!r}")
        rows.append(f"{repo}\t{ref}\t{dest}")
    extra_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    print(f"Wrote {out}")


def _tag(element: ET.Element) -> str:
    return element.tag.split("}", 1)[-1]


def _manifest_file(path_value: str, root_dir: Path, current_file: Path) -> Path:
    include_name = safe_relative_path(path_value, "manifest include")
    candidate = (root_dir / include_name).resolve()
    root_resolved = root_dir.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        die(f"Manifest include escapes manifest root: {path_value}")
    if not candidate.is_file():
        die(f"Manifest include not found: {candidate}")
    return candidate


def _expanded_manifest_elements(xml_path: Path, manifest_root: Path) -> list[ET.Element]:
    root_resolved = manifest_root.resolve()
    visited: set[Path] = set()
    active: set[Path] = set()
    expanded: list[ET.Element] = []

    def visit(path: Path) -> None:
        path = path.resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            die(f"Manifest file is outside manifest root: {path}")
        if path in active:
            die(f"Manifest include cycle detected at {path.relative_to(root_resolved)}")
        if path in visited:
            return
        if not path.is_file():
            die(f"Manifest XML not found: {path}")
        active.add(path)
        try:
            document = ET.parse(path).getroot()
        except ET.ParseError as exc:
            die(f"Invalid manifest XML {path}: {exc}")
        if _tag(document) != "manifest":
            die(f"Expected <manifest> root in {path}")
        for child in list(document):
            if _tag(child) == "include":
                name = child.get("name") or ""
                visit(_manifest_file(name, root_resolved, path))
            else:
                expanded.append(child)
        active.remove(path)
        visited.add(path)

    visit(xml_path)
    return expanded


def _join_remote(fetch: str, project_name: str) -> str:
    fetch = require_single_line(fetch.strip(), "manifest remote fetch")
    project_name = require_single_line(project_name.strip(), "manifest project name")
    if not project_name or project_name.startswith("/") or ".." in PurePosixPath(project_name).parts or "\\" in project_name:
        die(f"Unsafe manifest project name: {project_name!r}")
    if any(char.isspace() for char in fetch) or any(char.isspace() for char in project_name):
        die("Manifest remote fetch URL and project name must not contain whitespace")
    if fetch.startswith("git@") and fetch.endswith(":"):
        if not re.fullmatch(r"git@[^:/]+:", fetch):
            die(f"Unsupported SSH manifest remote fetch URL: {fetch!r}")
        url = fetch + project_name
    else:
        parsed = urllib.parse.urlsplit(fetch)
        if parsed.scheme not in {"https", "ssh", "git"} or not parsed.hostname:
            die(f"Unsupported manifest remote fetch URL: {fetch!r}; use HTTPS, SSH, or git://")
        url = fetch.rstrip("/") + "/" + project_name
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.hostname and parsed_url.hostname.lower() == "github.com" and not url.endswith(".git"):
        url += ".git"
    return url


def manifest_project_rows(xml_path: Path, skip: list[str], kernel_path: str, kernel_ref: str, manifest_root: Path | None = None) -> list[tuple[str, str, str]]:
    """Expand a practical subset of repo manifests and return (url, revision, path) rows.

    Supports nested <include>, <remote>, <default>, <project>, <extend-project>, and
    <remove-project>. Projects can use HTTPS, SSH, or git:// remotes. Unsupported
    structural constructs fail explicitly instead of silently producing a partial tree.
    """
    manifest_root = (manifest_root or xml_path.parent).resolve()
    kernel_path = safe_relative_path(kernel_path, "manifest kernel_path") if kernel_path else ""
    elements = _expanded_manifest_elements(xml_path.resolve(), manifest_root)
    remotes: dict[str, dict[str, str]] = {}
    default_remote = ""
    default_rev = ""
    projects: list[dict[str, str]] = []
    extends: list[ET.Element] = []
    removes: list[ET.Element] = []

    for child in elements:
        tag = _tag(child)
        if tag == "remote":
            name = child.get("name") or ""
            fetch = child.get("fetch") or ""
            if not name or not fetch:
                die("Manifest <remote> needs both name and fetch")
            remotes[name] = {"fetch": fetch, "revision": child.get("revision") or ""}
        elif tag == "default":
            default_remote = child.get("remote") or default_remote
            default_rev = child.get("revision") or default_rev
        elif tag == "project":
            name = child.get("name") or ""
            path = child.get("path") or name
            path = safe_relative_path(path, "manifest project path")
            remote = child.get("remote") or default_remote
            revision = child.get("revision") or ""
            if not revision and remote in remotes:
                revision = remotes[remote].get("revision", "")
            revision = revision or default_rev
            if not name or not remote:
                die(f"Manifest project at {path} needs a name and remote")
            projects.append({"name": name, "path": path, "remote": remote, "revision": revision})
            for nested in list(child):
                if _tag(nested) in {"copyfile", "linkfile"}:
                    print(f"::warning::Manifest {_tag(nested)} in project {name} is not applied by this builder", file=sys.stderr)
                elif _tag(nested) == "project":
                    die(f"Nested project entries are not supported (under {name})")
        elif tag == "extend-project":
            extends.append(child)
        elif tag == "remove-project":
            removes.append(child)
        elif tag == "submanifest":
            die("Manifest <submanifest> is not supported; flatten the manifest before using this builder")

    for extension in extends:
        name = extension.get("name") or ""
        match_path = extension.get("path") or ""
        matches = [p for p in projects if p["name"] == name and (not match_path or p["path"] == match_path)]
        if not matches and extension.get("optional", "false").lower() != "true":
            die(f"Manifest <extend-project> did not match project '{name}'")
        for project in matches:
            if extension.get("remote"):
                project["remote"] = extension.get("remote") or project["remote"]
            if extension.get("revision"):
                project["revision"] = extension.get("revision") or project["revision"]
            if extension.get("dest-path"):
                project["path"] = safe_relative_path(extension.get("dest-path") or "", "extend-project dest-path")

    for removal in removes:
        name = removal.get("name") or ""
        match_path = removal.get("path") or ""
        before = len(projects)
        projects = [p for p in projects if not (p["name"] == name and (not match_path or p["path"] == match_path))]
        if before == len(projects) and removal.get("optional", "false").lower() != "true":
            die(f"Manifest <remove-project> did not match project '{name}'")

    rows: list[tuple[str, str, str]] = []
    seen_paths: set[str] = set()
    seen_kernel = False
    for project in projects:
        name, path, remote = project["name"], project["path"], project["remote"]
        blob = f"{path} {name}"
        if any(part and part in blob for part in skip):
            print(f"skip {path}", file=sys.stderr)
            continue
        if path in seen_paths:
            die(f"Manifest contains duplicate project path '{path}'")
        for previous in seen_paths:
            if path.startswith(previous + "/") or previous.startswith(path + "/"):
                die(f"Overlapping manifest project paths '{previous}' and '{path}' are not supported")
        seen_paths.add(path)
        if remote not in remotes:
            die(f"Manifest project {name} references unknown remote '{remote}'")
        fetch = remotes[remote]["fetch"]
        revision = project["revision"] or remotes[remote].get("revision", "") or default_rev
        if not revision:
            die(f"Manifest project {name} at {path} has no revision")
        revision = require_single_line(revision, f"manifest revision for {name}")
        url = _join_remote(fetch, name)
        if kernel_path and path == kernel_path:
            seen_kernel = True
            if kernel_ref:
                revision = require_single_line(kernel_ref, "manifest kernel revision override")
        rows.append((url, revision, path))
    if kernel_path and not seen_kernel:
        die(f"Manifest has no project at kernel_path '{kernel_path}' (it may have been removed or skipped)")
    return rows


def parse_manifest(xml_path: Path, skip: list[str], kernel_path: str, kernel_ref: str, manifest_root: Path | None = None) -> None:
    for url, revision, path in manifest_project_rows(xml_path, skip, kernel_path, kernel_ref, manifest_root):
        print(f"{url}\t{revision}\t{path}")


def emit_matrix(args: argparse.Namespace) -> None:
    if truthy(args.all_sources):
        sources = list(SOURCES)
        selected_entries = [SOURCES[source] for source in sources]
    else:
        selected_entries = [source_entry(args.kernel_source, args)]
        sources = [args.kernel_source]
    managers, picked_all = parse_managers(args.manager)
    if getattr(args, "build_scope", "image-only") == "image-menu":
        # The menu ZIP needs a manager to patch in, so the "none" entry has nothing to build.
        if managers == ["none"]:
            die("build_scope=image-menu needs a root manager. Pick one or use manager=all.")
        if "none" in managers:
            if not picked_all:
                print("::warning::Leaving 'none' out of the matrix: build_scope=image-menu needs a root manager", file=sys.stderr)
            managers.remove("none")
    load_device(args.device)
    # Validate common build options once, before any matrix jobs are scheduled.
    for entry in selected_entries:
        resolve_toolchain(args.toolchain, entry)
    if len(sources) > 1 and args.source_ref.strip():
        print("::warning::source_ref is shared by every source in this matrix; verify that the ref exists in each selected source", file=sys.stderr)
    if len(managers) > 1 and args.manager_ref.strip():
        print("::warning::manager_ref is shared by every manager in this matrix; verify that the ref exists in each selected manager", file=sys.stderr)
    if getattr(args, "build_scope", "image-only") == "image-menu":
        # One runner builds every manager of a source and ships them in a single menu ZIP.
        include = [{"source": source, "manager": ",".join(managers)} for source in sources]
    else:
        include = [{"source": source, "manager": manager} for source in sources for manager in managers]
    payload = json.dumps({"include": include}, separators=(",", ":"))
    if args.github_output:
        delimiter = "MATRIX_JSON"
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"matrix<<{delimiter}\n{payload}\n{delimiter}\n")
    print(payload)


def write_manager_env(args: argparse.Namespace) -> None:
    values = resolve_manager(args.manager, truthy(args.susfs), args.manager_ref)
    for key, value in values.items():
        require_single_line(str(value), key)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items()) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve a kernel build plan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("write-plan")
    plan.add_argument("--device", default="marble")
    plan.add_argument("--kernel-name", default="")
    plan.add_argument("--kernel-source", default="aosp")
    plan.add_argument("--source-ref", default="")
    plan.add_argument("--manager", default="kernelsu")
    plan.add_argument("--manager-ref", default="")
    plan.add_argument("--susfs", default="true")
    plan.add_argument("--susfs-ref", default="")
    plan.add_argument("--susfs-branch", default="")
    plan.add_argument("--nomount", default="false")
    plan.add_argument("--nomount-ref", default="")
    plan.add_argument("--toolchain", default="auto")
    plan.add_argument("--lto", default="thin")
    plan.add_argument("--build-scope", default="image-only")
    plan.add_argument("--ccache", default="true")
    plan.add_argument("--uname-hash", default="true")
    plan.add_argument("--uname-run-id", default="auto")
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=write_plan)

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--xml", required=True)
    manifest.add_argument("--root", default="")
    manifest.add_argument("--skip", default="")
    manifest.add_argument("--kernel-path", default="")
    manifest.add_argument("--kernel-ref", default="")
    manifest.set_defaults(func=None)

    matrix = sub.add_parser("matrix")
    matrix.add_argument("--device", default="marble")
    matrix.add_argument("--kernel-source", default="aosp")
    matrix.add_argument("--source-ref", default="")
    matrix.add_argument("--manager", default="kernelsu")
    matrix.add_argument("--manager-ref", default="")
    matrix.add_argument("--toolchain", default="auto")
    matrix.add_argument("--all-sources", default="false")
    matrix.add_argument("--build-scope", default="image-only")
    matrix.add_argument("--github-output", default="")
    matrix.set_defaults(func=emit_matrix)

    manager_env = sub.add_parser("manager-env")
    manager_env.add_argument("--manager", required=True)
    manager_env.add_argument("--susfs", default="true")
    manager_env.add_argument("--manager-ref", default="")
    manager_env.add_argument("--out", required=True)
    manager_env.set_defaults(func=write_manager_env)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "manifest":
        root = Path(args.root).resolve() if args.root else None
        parse_manifest(Path(args.xml), args.skip.split(), args.kernel_path, args.kernel_ref, root)
        return
    args.func(args)


if __name__ == "__main__":
    main()
