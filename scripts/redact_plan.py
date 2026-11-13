#!/usr/bin/env python3
"""Remove URL credentials and query strings from the plan copied to artifacts."""

from __future__ import annotations

import shlex
import sys
import urllib.parse
from pathlib import Path


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname += f":{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: redact_plan.py PLAN_ENV")
    path = Path(sys.argv[1])
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    for line in lines:
        key, separator, encoded_value = line.partition("=")
        if separator and key == "TOOLCHAIN_URL":
            values = shlex.split(encoded_value, posix=True)
            if len(values) != 1:
                raise SystemExit("Invalid TOOLCHAIN_URL entry in plan.env")
            line = f"{key}={shlex.quote(redact_url(values[0]))}"
        output.append(line)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
