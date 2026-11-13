#!/usr/bin/env python3
"""Write machine-readable and human-readable build provenance files."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import urllib.parse
from pathlib import Path


def read_text(directory: Path, name: str, default: str = "") -> str:
    path = directory / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_commits(directory: Path) -> list[dict[str, str]]:
    path = directory / "project-commits.tsv"
    records: list[dict[str, str]] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        columns = line.split("\t")
        if len(columns) != 4:
            continue
        project_path, url, revision, commit = columns
        records.append({"path": project_path, "url": url, "requested_revision": revision, "commit": commit})
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--zip-name", required=True)
    args = parser.parse_args()
    release = args.release_dir.resolve()
    zip_path = release / args.zip_name
    if not zip_path.is_file():
        raise SystemExit(f"ZIP output not found: {zip_path}")

    env = os.environ
    device = {
        "key": env.get("DEVICE", ""),
        "architecture": env.get("ARCH", ""),
        "name1": env.get("DEVICE_NAME_1", ""),
        "name2": env.get("DEVICE_NAME_2", ""),
    }
    manifest_url = env.get("MANIFEST_REPO", "")
    toolchain_url = env.get("TOOLCHAIN_URL", "")
    if toolchain_url:
        parsed_toolchain_url = urllib.parse.urlsplit(toolchain_url)
        safe_netloc = parsed_toolchain_url.hostname or ""
        if parsed_toolchain_url.port:
            safe_netloc += f":{parsed_toolchain_url.port}"
        toolchain_url = urllib.parse.urlunsplit((parsed_toolchain_url.scheme, safe_netloc, parsed_toolchain_url.path, "", ""))
    source = {
        "key": env.get("SOURCE_KEY", ""),
        "display": env.get("SOURCE_DISPLAY", ""),
        "rom": env.get("ROM_LABEL", ""),
        "fetch_method": env.get("FETCH", ""),
        "repository": env.get("KERNEL_REPO", ""),
        "requested_revision": env.get("KERNEL_REF", ""),
        "manifest_repository": manifest_url,
        "manifest_revision": env.get("MANIFEST_REF", ""),
        "kernel_revision_override": env.get("SOURCE_REF_OVERRIDE", ""),
        "manifest_commit": read_text(release, "manifest-commit.txt", ""),
        "kernel_path": env.get("KERNEL_PATH", ""),
        "commit": read_text(release, "kernel-commit.txt", "unknown"),
        "manifest_projects": project_commits(release),
    }
    manager = {
        "key": env.get("MANAGER", ""),
        "display": env.get("MANAGER_DISPLAY", ""),
        "repository": env.get("MANAGER_REPO", ""),
        "requested_revision": env.get("MANAGER_REF", ""),
        "effective_repository": env.get("MANAGER_EFFECTIVE_REPO", env.get("MANAGER_REPO", "")),
        "effective_revision": env.get("MANAGER_EFFECTIVE_REF", env.get("MANAGER_REF", "")),
        "commit": read_text(release, "manager-commit.txt", "unknown"),
        "setup_script_sha256": read_text(release, "manager-setup.sha256", ""),
    }
    features = {
        "susfs": env.get("ENABLE_SUSFS", "false") == "true",
        "susfs_repository": env.get("SUSFS_REPO", ""),
        "susfs_branch": env.get("SUSFS_BRANCH", ""),
        "susfs_requested_revision": env.get("SUSFS_REF", "") or "branch tip",
        "susfs_commit": read_text(release, "susfs-commit.txt", ""),
        "susfs_version": read_text(release, "susfs-version.txt", ""),
        "nomount": env.get("ENABLE_NOMOUNT", "false") == "true",
        "nomount_repository": env.get("NOMOUNT_REPO", ""),
        "nomount_revision": env.get("NOMOUNT_REF", ""),
        "nomount_setup_sha256": read_text(release, "nomount-setup.sha256", ""),
    }
    compiler = {
        "name": env.get("TOOLCHAIN", ""),
        "url": toolchain_url,
        "expected_sha256": env.get("TOOLCHAIN_SHA256", ""),
        "archive_sha256": read_text(release, "toolchain-archive.sha256", ""),
        "version": read_text(release, "toolchain-version.txt", ""),
    }
    build = {
        "lto": env.get("LTO", ""),
        "scope": env.get("BUILD_SCOPE", ""),
        "defconfig_mode": env.get("DEFCONFIG_MODE", ""),
        "single_defconfig": env.get("DEFCONFIG_SINGLE", ""),
        "gki_fragments": env.get("GKI_FRAGMENTS", "").split(),
        "ccache": env.get("USE_CCACHE", "false") == "true",
        "build_user": env.get("KBUILD_BUILD_USER", ""),
        "build_host": env.get("KBUILD_BUILD_HOST", ""),
        "anykernel_commit": read_text(release, "anykernel-commit.txt", ""),
        "skipped_techpack": [line for line in read_text(release, "skipped-techpack.txt", "").splitlines() if line],
    }
    workflow = {
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_number": env.get("GITHUB_RUN_NUMBER", ""),
        "commit": env.get("GITHUB_SHA", ""),
        "ref": env.get("GITHUB_REF", ""),
    }
    artifacts = []
    for path in sorted(release.iterdir()):
        if not path.is_file() or path.name in {"build-manifest.json", "build-info.txt"}:
            continue
        if path.suffix in {".zip", ".gz", ".dtb", ".txt", ".sha256", ".tsv"} or path.name in {"Image", "Image.gz", "Image.gz-dtb"}:
            artifacts.append({"name": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path)})

    metadata = {
        "schema_version": 1,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "workflow": workflow,
        "device": device,
        "source": source,
        "manager": manager,
        "features": features,
        "toolchain": compiler,
        "build": build,
        "artifacts": artifacts,
    }
    (release / "build-manifest.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    kernel_repository = source["repository"] or source["manifest_repository"]
    kernel_revision = source["requested_revision"] or source["manifest_revision"]
    if source["kernel_revision_override"] and source["fetch_method"] == "manifest":
        kernel_revision += f" (kernel project override: {source['kernel_revision_override']})"
    lines = [
        f"device: {device['key']} ({device['name1']} {device['name2']})",
        f"architecture: {device['architecture']}",
        f"kernel_name: {env.get('KERNEL_NAME', '') or 'default'} ({build['build_user']}@{build['build_host']})",
        f"source: {source['display']} [{source['key']}] {source['rom']}",
        f"fetch: {source['fetch_method']}",
        f"kernel/manifest: {kernel_repository} @ {kernel_revision}",
        f"kernel_commit: {source['commit']}",
        f"manager: {manager['display']} {manager['repository']}@{manager['requested_revision']}",
        f"manager_effective: {manager['effective_repository']}@{manager['effective_revision']}",
        f"manager_commit: {manager['commit']}",
        f"manager_setup_sha256: {manager['setup_script_sha256'] or 'n/a'}",
        f"susfs: {features['susfs']} {features['susfs_branch']} {features['susfs_requested_revision']} {features['susfs_version']}",
        f"susfs_commit: {features['susfs_commit'] or 'n/a'}",
        f"nomount: {features['nomount']} {features['nomount_revision']}",
        f"nomount_setup_sha256: {features['nomount_setup_sha256'] or 'n/a'}",
        f"toolchain: {compiler['name']}",
        f"manifest_commit: {source['manifest_commit'] or 'n/a'}",
        f"anykernel_commit: {build['anykernel_commit'] or 'n/a'}",
        f"toolchain_archive_sha256: {compiler['archive_sha256'] or 'not recorded'}",
        f"lto: {build['lto']}",
        f"scope: {build['scope']}",
        f"skipped_techpack_count: {len(build['skipped_techpack'])}",
        f"zip: {args.zip_name}",
        f"zip_sha256: {sha256(zip_path)}",
        "build_manifest: build-manifest.json",
        "project_commits: project-commits.tsv",
    ]
    (release / "build-info.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
