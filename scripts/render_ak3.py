#!/usr/bin/env python3
"""Fill the __PLACEHOLDER__ values of an AnyKernel3 template from AK_* variables."""
import os
import pathlib
import re
import sys


def shell_single_quoted_value(value: str) -> str:
    # The AnyKernel properties block is a shell single-quoted string.
    return value.replace("'", "'\\''")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: render_ak3.py <template> <destination>")
    source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    values = {
        "__KERNEL_STRING__": shell_single_quoted_value(os.environ["AK_KERNEL_STRING"]),
        "__DEVICE_NAME_1__": shell_single_quoted_value(os.environ["AK_DEVICE_NAME_1"]),
        "__DEVICE_NAME_2__": shell_single_quoted_value(os.environ["AK_DEVICE_NAME_2"]),
    }
    pattern = re.compile("|".join(re.escape(key) for key in values))
    source = pattern.sub(lambda match: values[match.group(0)], source)
    if re.search(r"__[A-Z_0-9]+__", source):
        raise SystemExit("Unexpanded AnyKernel template placeholder remains")
    pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")


if __name__ == "__main__":
    main()
