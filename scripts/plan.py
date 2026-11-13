#!/usr/bin/env python3
"""Resolve builder inputs into a shell env file, a fetch list, or an Actions matrix.

Adding a kernel is a block in config/sources.json. Adding a device is
config/devices/<name>.env. This file does not need a workflow edit.
"""

from __future__ import annotations

import argparse
import hashlib
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


def source_entry(key: str, args: argparse.Namespace) -> dict:
    if key == "custom":
        repo = validate_repo_target(args.custom_repo, "custom_repo") if args.custom_repo.strip() else ""
        ref = require_single_line((args.source_ref or args.custom_ref).strip(), "custom_ref/source_ref")
        if not repo or not ref:
            die("custom source needs custom_repo and custom_ref (or source_ref)")
        fetch = args.custom_fetch.strip() or "git"
        if fetch not in {"git", "manifest"}:
            die("custom_fetch must be git or manifest")
        entry = {
            "display": "Custom",
            "rom": repo,
            "fetch": fetch,
            "defconfig_mode": "auto",
            "kernel_path": safe_relative_path(args.custom_kernel_path, "custom_kernel_path", allow_dot=(fetch == "git")) if args.custom_kernel_path.strip() else ("." if fetch == "git" else "kernel_platform/xiaomi/sm8450"),
            "manifest_skip": ["prebuilts/clang", "prebuilts-master", "gcc/linux-x86"],
        }
        if fetch == "git":
            entry["repo"] = repo
            entry["ref"] = ref
        else:
            entry["manifest_repo"] = repo
            entry["manifest_ref"] = ref
            entry["manifest_file"] = "default.xml"
        return entry
    if key not in SOURCES:
        die(f"Unknown kernel source '{key}'. Known: {', '.join(SOURCES)} or custom")
    return SOURCES[key]


def resolve_manager(name: str, susfs: bool, manager_ref: str) -> dict[str, str]:
    if name not in MANAGERS:
        die(f"Unknown manager '{name}'. Known: {', '.join(MANAGERS)} or all")
    entry = MANAGERS[name]
    if name == "none":
        return {
            "MANAGER": "none",
            "MANAGER_DISPLAY": entry["display"],
            "MANAGER_REPO": "",
            "MANAGER_REF": "",
            "MANAGER_SETUP": "",
            "MANAGER_SUSFS_FALLBACK_REPO": "",
            "MANAGER_SUSFS_FALLBACK_REF": "",
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
        "MANAGER_SUSFS_FALLBACK_REPO": entry.get("susfs_fallback_repo", "") if enabled == "true" else "",
        "MANAGER_SUSFS_FALLBACK_REF": entry.get("susfs_fallback_ref", "") if enabled == "true" else "",
        "ENABLE_SUSFS": enabled,
    }


def resolve_toolchain(name: str, url: str, sha256: str, source: dict) -> tuple[str, dict]:
    """Return (toolchain name, entry). A URL input wins over the name."""
    url = require_single_line(url.strip(), "toolchain_url")
    sha256 = require_single_line(sha256.strip().lower(), "toolchain_sha256")
    if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
        die("toolchain_sha256 must be exactly 64 hexadecimal characters")
    if url:
        try:
            parsed_url = urllib.parse.urlsplit(url)
            # Accessing .port also validates malformed port values.
            _ = parsed_url.port
        except ValueError as exc:
            die(f"Invalid toolchain_url: {exc}")
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            die("toolchain_url must be a valid HTTPS URL with a hostname")
        if parsed_url.username or parsed_url.password:
            die("toolchain_url must not embed username/password credentials; use an approved download URL")
        if any(char.isspace() for char in url):
            die("toolchain_url must not contain whitespace")
        return "custom-" + hashlib.sha1(url.encode()).hexdigest()[:8], {"url": url, "sha256": sha256}
    name = name.strip() or "auto"
    if name == "auto":
        defaults = [key for key, value in TOOLCHAINS.items() if value.get("default")]
        name = source.get("toolchain") or (defaults[0] if defaults else "")
    if name not in TOOLCHAINS:
        die(f"Unknown toolchain '{name}'. Known: auto, {', '.join(TOOLCHAINS)}. Add it to config/toolchains.json")
    entry = dict(TOOLCHAINS[name])
    if sha256:
        entry["sha256"] = sha256
    return name, entry


def fragments_for(entry: dict, device: dict[str, str]) -> str:
    if entry.get("config_fragments"):
        return " ".join(entry["config_fragments"])
    return device.get("GKI_FRAGMENTS", "")


def write_plan(args: argparse.Namespace) -> None:
    device = load_device(args.device)
    entry = source_entry(args.kernel_source, args)
    susfs = truthy(args.susfs)
    nomount = truthy(args.nomount)
    manager = resolve_manager(args.manager, susfs, args.manager_ref)
    mode = entry.get("defconfig_mode", "auto")
    toolchain, toolchain_entry = resolve_toolchain(args.toolchain, args.toolchain_url, args.toolchain_sha256, entry)
    if args.lto not in {"none", "thin", "full"}:
        die("lto must be none, thin, or full")
    if args.build_scope not in {"image-only", "full"}:
        die("build_scope must be image-only or full")

    fetch = entry.get("fetch", "git")
    if fetch == "git":
        kernel_path = safe_relative_path(entry.get("kernel_path", "."), "kernel_path", allow_dot=True)
    elif fetch == "manifest":
        kernel_path = safe_relative_path(entry.get("kernel_path", ""), "manifest kernel_path")
    else:
        die(f"Unsupported fetch method '{fetch}' for {args.kernel_source}")

    kernel_ref = entry.get("ref", "")
    if fetch == "git" and args.source_ref.strip() and args.kernel_source != "custom":
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
        "TOOLCHAIN": toolchain,
        "TOOLCHAIN_URL": toolchain_entry["url"],
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
    if fetch == "manifest" and args.source_ref.strip() and args.kernel_source == "custom":
        values["MANIFEST_REF"] = args.source_ref.strip()
    values.update(manager)
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
        if args.kernel_source == "custom":
            die("all_sources cannot be combined with a custom repo. Add the source to config/sources.json first.")
        sources = list(SOURCES)
        selected_entries = [SOURCES[source] for source in sources]
    else:
        selected_entries = [source_entry(args.kernel_source, args)]
        sources = [args.kernel_source]
    managers = list(MANAGERS) if args.manager == "all" else [args.manager]
    if args.manager != "all" and args.manager not in MANAGERS:
        die(f"Unknown manager '{args.manager}'. Known: {', '.join(MANAGERS)} or all")
    load_device(args.device)
    # Validate common build options once, before any matrix jobs are scheduled.
    for entry in selected_entries:
        resolve_toolchain(args.toolchain, args.toolchain_url, args.toolchain_sha256, entry)
    if len(sources) > 1 and args.source_ref.strip():
        print("::warning::source_ref is shared by every source in this matrix; verify that the ref exists in each selected source", file=sys.stderr)
    if len(managers) > 1 and args.manager_ref.strip():
        print("::warning::manager_ref is shared by every manager in this matrix; verify that the ref exists in each selected manager", file=sys.stderr)
    if len(sources) > 1 and args.toolchain_sha256.strip() and not args.toolchain_url.strip() and args.toolchain.strip() == "auto":
        defaults = [key for key, value in TOOLCHAINS.items() if value.get("default")]
        global_default = defaults[0] if defaults else ""
        selected = {entry.get("toolchain") or global_default for entry in selected_entries}
        if len(selected) > 1:
            print("::warning::toolchain_sha256 is shared by all source builds while toolchain=auto selects different source-specific compilers; use one toolchain_url/fixed toolchain or leave the shared checksum empty", file=sys.stderr)
    include = [{"source": source, "manager": manager} for source in sources for manager in managers]
    payload = json.dumps({"include": include}, separators=(",", ":"))
    if args.github_output:
        delimiter = "MATRIX_JSON"
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"matrix<<{delimiter}\n{payload}\n{delimiter}\n")
    print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve a kernel build plan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("write-plan")
    plan.add_argument("--device", default="marble")
    plan.add_argument("--kernel-name", default="")
    plan.add_argument("--kernel-source", default="aosp")
    plan.add_argument("--source-ref", default="")
    plan.add_argument("--custom-repo", default="")
    plan.add_argument("--custom-ref", default="")
    plan.add_argument("--custom-fetch", default="git")
    plan.add_argument("--custom-kernel-path", default="")
    plan.add_argument("--manager", default="kernelsu")
    plan.add_argument("--manager-ref", default="")
    plan.add_argument("--susfs", default="true")
    plan.add_argument("--susfs-ref", default="")
    plan.add_argument("--susfs-branch", default="")
    plan.add_argument("--nomount", default="false")
    plan.add_argument("--nomount-ref", default="")
    plan.add_argument("--toolchain", default="auto")
    plan.add_argument("--toolchain-url", default="")
    plan.add_argument("--toolchain-sha256", default="")
    plan.add_argument("--lto", default="thin")
    plan.add_argument("--build-scope", default="image-only")
    plan.add_argument("--ccache", default="true")
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
    matrix.add_argument("--custom-repo", default="")
    matrix.add_argument("--custom-ref", default="")
    matrix.add_argument("--source-ref", default="")
    matrix.add_argument("--custom-fetch", default="git")
    matrix.add_argument("--manager", default="kernelsu")
    matrix.add_argument("--manager-ref", default="")
    matrix.add_argument("--toolchain", default="auto")
    matrix.add_argument("--toolchain-url", default="")
    matrix.add_argument("--toolchain-sha256", default="")
    matrix.add_argument("--all-sources", default="false")
    matrix.add_argument("--github-output", default="")
    matrix.set_defaults(func=emit_matrix)
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
