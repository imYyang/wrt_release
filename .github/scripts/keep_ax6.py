#!/usr/bin/env python3
"""Reapply this fork's device policy after importing upstream build sources."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
DEVICES = {"redmi_ax6_immwrt", "redmi_ax6_libwrt"}
EXCLUDED_PACKAGES = {
    "easytier", "lucky", "oaf", "open-app-filter", "kmod-oaf",
    "luci-app-easytier", "luci-app-lucky", "luci-app-oaf", "luci-app-passwall",
    "luci-i18n-easytier-zh-cn", "luci-i18n-lucky-zh-cn",
    "luci-i18n-oaf-zh-cn", "luci-i18n-passwall-zh-cn",
}


def apply_package_policy(core):
    # Remove upstream selections and plugin-specific build options everywhere,
    # then explicitly disable the applications and their service packages.
    for path in (core / "deconfig").rglob("*.config"):
        lines = path.read_text(encoding="utf-8").splitlines()
        filtered = []
        for line in lines:
            match = re.match(r"(?:# )?CONFIG_PACKAGE_([^= ]+)", line)
            if match and any(
                match[1] == package or match[1].startswith(package + "_")
                for package in EXCLUDED_PACKAGES
            ):
                continue
            if line.startswith("CONFIG_EASYTIER_"):
                continue
            filtered.append(line)
        path.write_text("\n".join(filtered) + "\n", encoding="utf-8", newline="\n")

    base = core / "deconfig/compile_base.config"
    source = base.read_text(encoding="utf-8").rstrip()
    marker = "# Fork policy: excluded applications"
    if source.endswith(marker):
        source = source[:-len(marker)].rstrip()
    source += "\n\n" + marker + "\n"
    source += "".join(f"CONFIG_PACKAGE_{package}=n\n" for package in sorted(EXCLUDED_PACKAGES))
    base.write_text(source, encoding="utf-8", newline="\n")

    (core / "deconfig/fragments/proxy.config").unlink(missing_ok=True)
    for path in (core / "compilecfg").glob("*.ini"):
        source = path.read_text(encoding="utf-8")
        source = re.sub(
            r"^CONFIG_FRAGMENTS=(.*)$",
            lambda match: "CONFIG_FRAGMENTS=" + ",".join(
                part.strip() for part in match[1].split(",")
                if part.strip() and part.strip() != "proxy"
            ),
            source, flags=re.M,
        )
        path.write_text(source, encoding="utf-8", newline="\n")


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

    apply_package_policy(core)

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
