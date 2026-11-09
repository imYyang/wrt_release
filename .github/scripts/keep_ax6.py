#!/usr/bin/env python3
"""Reapply this fork's device policy after importing upstream build sources."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DEVICES = {"redmi_ax6_immwrt", "redmi_ax6_libwrt"}


def main():
    core = ROOT / "wrt_core"
    for device in DEVICES:
        for directory, suffix in (("compilecfg", ".ini"), ("deconfig", ".config")):
            path = core / directory / (device + suffix)
            if not path.is_file():
                raise RuntimeError(f"Upstream no longer supplies required AX6 configuration: {path}")

    wifi = core / "patches/992_set-wifi-uci.sh"
    source = wifi.read_text(encoding="utf-8")
    functions = []
    for name in ("configure_wifi", "redmi_ax6_wifi_cfg"):
        matches = re.findall(rf"^{name}\(\) \{{\n.*?^\}}", source, re.M | re.S)
        if len(matches) != 1:
            raise RuntimeError(f"Unexpected upstream Wi-Fi layout: {name}")
        functions.append(matches[0])

    # Do not let new upstream devices reappear in the local build menu.
    for path in (core / "compilecfg").glob("*.ini"):
        if path.stem not in DEVICES:
            path.unlink()
    for path in (core / "deconfig").glob("*.config"):
        if path.stem not in DEVICES | {"compile_base"}:
            path.unlink()

    wifi.write_text(
        '#!/bin/sh\n\nboard_name=$(cat /tmp/sysinfo/board_name)\n\n'
        + "\n\n".join(functions)
        + '\n\ncase "${board_name}" in\n'
        + 'redmi,ax6 | \\\n\tredmi,ax6-stock)\n\tredmi_ax6_wifi_cfg\n\t;;\n'
        + '*)\n\texit 0\n\t;;\nesac\n\n'
        + 'uci commit wireless\n/etc/init.d/network restart\n',
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
