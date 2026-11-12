#!/usr/bin/env python3
"""Resolve builder inputs into a shell env file, a fetch list, or a Actions matrix.
Adding a kernel is a block in config/sources.json.
Adding a device is config/devices/<name>.env.
This file does not need a workflow edit.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCES = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
MANAGERS = json.loads((ROOT / "config" / "managers.json").read_text(encoding="utf-8"))


def die(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def load_device(name: str) -> dict[str, str]:
    path = ROOT / "config" / "devices" / f"{name}.env"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in (ROOT / "config" / "devices").glob("*.env")))
        die(f"Unknown device '{name}'. Known devices: {known}")

    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"')
    return env


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def source_entry(key: str, args: argparse.Namespace) -> dict:
    if key == "custom":
        repo = args.custom_repo.strip()
        ref = (args.source_ref or args.custom_ref).strip()
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
            "toolchain": "llvm-23.1.1",
            "kernel_path": args.custom_kernel_path.strip(),
            "manifest_skip": ["prebuilts/clang", "prebuilts-master", "gcc/linux-x86"],
        }
        if fetch == "git":
            entry["repo"] = repo
            entry["ref"] = ref
            entry["kernel_path"] = entry["kernel_path"] or "."
        else:
            entry["manifest_repo"] = repo
            entry["manifest_ref"] = ref
            entry["manifest_file"] = "default.xml"
            entry["kernel_path"] = entry["kernel_path"] or "kernel_platform/xiaomi/sm8450"
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

    ref = manager_ref.strip()
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


def fragments_for(entry: dict, device: dict[str, str]) -> str:
    if entry.get("config_fragments"):
        return " ".join(entry["config_fragments"])
    return device.get("GKI_FRAGMENTS", "")


def write_plan(args: argparse.Namespace) -> None:
    device = load_device(args.device)
    entry = source_entry(args.kernel_source, args)
    susfs = truthy(args.susfs)
    manager = resolve_manager(args.manager, susfs, args.manager_ref)

    mode = entry.get("defconfig_mode", "auto")
    toolchain = args.toolchain.strip() or "auto"
    if toolchain == "auto":
        toolchain = entry.get("toolchain") or "llvm-23.1.1"
    if toolchain not in {"android-r596125", "llvm-23.1.1"}:
        die(f"Unsupported toolchain '{toolchain}'. Use auto, android-r596125, or llvm-23.1.1")

    nomount = args.nomount.strip() or "off"
    if nomount not in {"off", "builtin", "lkm"}:
        die("nomount must be off, builtin, or lkm")

    if args.lto not in {"none", "thin", "full"}:
        die("lto must be none, thin, or full")

    if args.build_scope not in {"image-only", "full"}:
        die("build_scope must be image-only or full")

    kernel_ref = entry.get("ref", "")
    if entry.get("fetch") == "git" and args.source_ref.strip() and args.kernel_source != "custom":
        kernel_ref = args.source_ref.strip()

    values = {
        "DEVICE": args.device,
        "ARCH": device.get("ARCH", "arm64"),
        "DEVICE_NAME_1": device.get("DEVICE_NAME_1", args.device),
        "DEVICE_NAME_2": device.get("DEVICE_NAME_2", ""),
        "DEFCONFIG_SINGLE": entry.get("defconfig") or device.get("DEFCONFIG_SINGLE", ""),
        "GKI_FRAGMENTS": fragments_for(entry, device),
        "SOURCE_KEY": args.kernel_source,
        "SOURCE_DISPLAY": entry.get("display", args.kernel_source),
        "ROM_LABEL": entry.get("rom", ""),
        "FETCH": entry.get("fetch", "git"),
        "KERNEL_REPO": entry.get("repo", ""),
        "KERNEL_REF": kernel_ref,
        "KERNEL_PATH": entry.get("kernel_path", "."),
        "MANIFEST_REPO": entry.get("manifest_repo", ""),
        "MANIFEST_REF": entry.get("manifest_ref", ""),
        "MANIFEST_FILE": entry.get("manifest_file", "default.xml"),
        "MANIFEST_SKIP": " ".join(entry.get("manifest_skip", [])),
        "SOURCE_REF_OVERRIDE": args.source_ref.strip(),
        "DEFCONFIG_MODE": mode,
        "TOOLCHAIN": toolchain,
        "LTO": args.lto,
        "BUILD_SCOPE": args.build_scope,
        "MODULES_SRC": entry.get("modules_src", ""),
        "MODULES_LIST": entry.get("modules_list", ""),
        "SUSFS_REPO": device.get("SUSFS_REPO", "https://gitlab.com/simonpunk/susfs4ksu.git"),
        "SUSFS_BRANCH": args.susfs_branch.strip() or device.get("SUSFS_BRANCH", "gki-android12-5.10"),
        "SUSFS_REF": args.susfs_ref.strip(),
        "NOMOUNT": nomount,
        "NOMOUNT_REPO": device.get("NOMOUNT_REPO", "https://github.com/maxsteeel/nomount"),
        "NOMOUNT_REF": args.nomount_ref.strip() or device.get("NOMOUNT_REF", "dev"),
        "ANYKERNEL_REPO": device.get("ANYKERNEL_REPO", "https://github.com/osm0sis/AnyKernel3.git"),
        "ANYKERNEL_REF": device.get("ANYKERNEL_REF", "master"),
        "KBUILD_BUILD_USER": device.get("KBUILD_BUILD_USER", args.device),
        "KBUILD_BUILD_HOST": device.get("KBUILD_BUILD_HOST", "github-actions"),
        "USE_CCACHE": "true" if truthy(args.ccache) else "false",
    }

    # Manifest ref override moves the manifest checkout, not only the kernel project.
    # The kernel project revision is overridden separately via SOURCE_REF_OVERRIDE.
    if entry.get("fetch") == "manifest" and args.source_ref.strip() and args.kernel_source == "custom":
        values["MANIFEST_REF"] = args.source_ref.strip()

    values.update(manager)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={shlex.quote(str(value))}" for key, value in values.items()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    extra_path = out.parent / "extra.tsv"
    rows = []
    for item in entry.get("extra", []):
        dest = item.get("dest", "")
        repo = item.get("repo", "")
        ref = item.get("ref", "")
        if args.source_ref.strip() and args.kernel_source != "custom":
            # Keep extra repos on their preset refs. Override only the kernel ref.
            pass
        if not repo or not dest or not ref:
            die(f"extra repo entry for {args.kernel_source} needs repo, ref, and dest")
        rows.append(f"{repo}\t{ref}\t{dest}")
    extra_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

    print(f"Wrote {out}")


def parse_manifest(xml_path: Path, skip: list[str], kernel_path: str, kernel_ref: str) -> None:
    root = ET.parse(xml_path).getroot()
    remotes: dict[str, str] = {}
    default_remote = ""
    default_rev = ""
    seen_kernel = False

    for child in list(root):
        tag = child.tag.split("}", 1)[-1]
        if tag == "remote":
            remotes[child.get("name") or ""] = child.get("fetch") or ""
        elif tag == "default":
            default_remote = child.get("remote") or ""
            default_rev = child.get("revision") or ""
        elif tag == "project":
            name = child.get("name") or ""
            path = child.get("path") or name
            remote = child.get("remote") or default_remote
            rev = child.get("revision") or default_rev
            fetch = remotes.get(remote, "")

            if "github.com" not in fetch:
                continue

            blob = f"{path} {name}"
            if any(part and part in blob for part in skip):
                print(f"skip {path}", file=sys.stderr)
                continue

            if not fetch.endswith("/"):
                fetch += "/"
            url = fetch + name
            if not url.endswith(".git"):
                url += ".git"

            if kernel_path and path == kernel_path:
                seen_kernel = True
                if kernel_ref:
                    rev = kernel_ref

            if not rev:
                die(f"Manifest project {name} has no revision")

            print(f"{url}\t{rev}\t{path}")

    if kernel_path and not seen_kernel:
        die(f"Manifest has no GitHub project at path {kernel_path}")


def emit_matrix(args: argparse.Namespace) -> None:
    if truthy(args.all_sources):
        if args.kernel_source == "custom":
            die("all_sources cannot be combined with a custom repo. Add the source to config/sources.json first.")
        sources = list(SOURCES)
    else:
        source_entry(args.kernel_source, args)
        sources = [args.kernel_source]

    managers = list(MANAGERS) if args.manager == "all" else [args.manager]
    if args.manager != "all" and args.manager not in MANAGERS:
        die(f"Unknown manager '{args.manager}'. Known: {', '.join(MANAGERS)} or all")

    load_device(args.device)

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
    plan.add_argument("--nomount", default="off")
    plan.add_argument("--nomount-ref", default="")
    plan.add_argument("--toolchain", default="auto")
    plan.add_argument("--lto", default="thin")
    plan.add_argument("--build-scope", default="image-only")
    plan.add_argument("--ccache", default="true")
    plan.add_argument("--out", required=True)
    plan.set_defaults(func=write_plan)

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--xml", required=True)
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
    matrix.add_argument("--all-sources", default="false")
    matrix.add_argument("--github-output", default="")
    matrix.set_defaults(func=emit_matrix)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "manifest":
        parse_manifest(Path(args.xml), args.skip.split(), args.kernel_path, args.kernel_ref)
        return

    args.func(args)


if __name__ == "__main__":
    main()
