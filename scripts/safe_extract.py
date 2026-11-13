#!/usr/bin/env python3
"""Safely extract a downloaded tar archive into a fresh directory."""

from __future__ import annotations

import sys
import tarfile
from pathlib import Path, PurePosixPath


def fail(message: str) -> "NoReturn":
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def main() -> None:
    if len(sys.argv) != 3:
        fail("Usage: safe_extract.py ARCHIVE DESTINATION")

    archive = Path(sys.argv[1])
    destination = Path(sys.argv[2]).resolve()
    if not archive.is_file():
        fail(f"Archive not found: {archive}")
    destination.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(archive, mode="r:*") as tar:
            members = tar.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                    fail(f"Unsafe archive path: {member.name!r}")
                target = (destination / Path(*name.parts)).resolve()
                if not within(destination, target):
                    fail(f"Archive member escapes destination: {member.name!r}")

                if member.issym():
                    link = PurePosixPath(member.linkname)
                    if link.is_absolute() or "\\" in member.linkname:
                        fail(f"Unsafe symlink target in archive: {member.name!r} -> {member.linkname!r}")
                    link_target = (target.parent / Path(*link.parts)).resolve()
                    if not within(destination, link_target):
                        fail(f"Archive symlink escapes destination: {member.name!r} -> {member.linkname!r}")
                elif member.islnk():
                    link = PurePosixPath(member.linkname)
                    if link.is_absolute() or ".." in link.parts or "\\" in member.linkname:
                        fail(f"Unsafe hardlink target in archive: {member.name!r} -> {member.linkname!r}")
                    link_target = (destination / Path(*link.parts)).resolve()
                    if not within(destination, link_target):
                        fail(f"Archive hardlink escapes destination: {member.name!r} -> {member.linkname!r}")
                elif not (member.isfile() or member.isdir()):
                    fail(f"Unsupported special file in archive: {member.name!r}")

            # Python's data filter additionally rejects privilege changes and unsafe links.
            tar.extractall(path=destination, members=members, filter="data")
    except (tarfile.TarError, OSError, ValueError) as exc:
        fail(f"Unable to safely extract {archive}: {exc}")


if __name__ == "__main__":
    main()
