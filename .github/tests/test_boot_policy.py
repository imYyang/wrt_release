"""Guard first-boot ordering and wizard removal across upstream imports."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
spec = importlib.util.spec_from_file_location("policy", ROOT / ".github/scripts/keep_ax6.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class BootPolicyTests(unittest.TestCase):
    def test_wifi_defaults_do_not_start_network_before_dnsmasq(self):
        # Run the actual default script, intercepting all host UCI/service calls.
        source = (ROOT / "wrt_core/patches/992_set-wifi-uci.sh").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            calls = temp / "calls"
            service = temp / "network"
            service.write_text('#!/bin/sh\necho premature-network-start >> "$CALLS"\n', encoding="utf-8", newline="\n")
            service.chmod(0o755)
            source = source.replace("$(cat /tmp/sysinfo/board_name)", '"$TEST_BOARD"')
            source = source.replace("/etc/init.d/network", shlex.quote(service.as_posix()))
            mock = '''
uci() {
    case "$*" in
        get*) printf '%s' "$ENCRYPTION" ;;
        '-q batch') cat >> "$CALLS" ;;
        'commit wireless') echo commit-wireless >> "$CALLS" ;;
        *) return 1 ;;
    esac
}
'''
            for board in ("redmi,ax6", "redmi,ax6-stock", "other,board"):
                for encryption in ("none", "psk2+ccmp"):
                    calls.write_text("")
                    env = {**os.environ, "CALLS": calls.as_posix(), "TEST_BOARD": board,
                           "ENCRYPTION": encryption}
                    subprocess.run([BASH, "-s"], input=mock + source, text=True, env=env, check=True)
                    result = calls.read_text()
                    self.assertNotIn("premature-network-start", result)
                    if board == "other,board":
                        self.assertEqual(result, "")
                    else:
                        self.assertIn("commit-wireless", result)
                        if encryption == "none":
                            self.assertIn("set wireless.radio0.disabled='1'", result)
                            self.assertIn('set wireless.default_radio1.ssid="YangWrt"', result)
                        else:
                            self.assertNotIn("set wireless.", result)

    def test_sync_removes_upstream_wizard_and_keeps_boot_fix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "wrt_core", root / "wrt_core")
            shutil.copytree(ROOT / ".github/defaults", root / ".github/defaults")
            shutil.copy2(ROOT / "build.sh", root / "build.sh")
            core = root / "wrt_core"
            # Model an upstream import reintroducing the wizard and early restart.
            with (core / "deconfig/compile_base.config").open("a") as stream:
                stream.write("\nCONFIG_PACKAGE_luci-app-netwiz=y\nCONFIG_PACKAGE_luci-i18n-netwiz-zh-cn=y\n")
            with (core / "patches/992_set-wifi-uci.sh").open("a") as stream:
                stream.write("/etc/init.d/network restart\n")
            (core / "modules/custom_feed.sh").write_text('''required=(luci-app-netwiz luci-app-mosdns)
sources=(
    "huchd0/luci-app-netwiz|https://github.com/huchd0/luci-app-netwiz.git|master|luci-app-netwiz"
)
''')
            (core / "modules/verify.sh").write_text("required=(luci-app-netwiz luci-app-mosdns)\n")
            with (core / "modules/feed_source_fixes.sh").open("a") as stream:
                stream.write("\nfix_netwiz_permissions() {\n    return 0\n}\n")
            with (core / "update.sh").open("a") as stream:
                stream.write("    fix_netwiz_permissions\n")
            original = policy.ROOT
            try:
                policy.ROOT = root
                for _ in range(2):
                    policy.main()
                    config = (core / "deconfig/compile_base.config").read_text()
                    for name in ("luci-app-netwiz", "luci-i18n-netwiz-zh-cn"):
                        self.assertIn(f"CONFIG_PACKAGE_{name}=n", config)
                        self.assertNotIn(f"CONFIG_PACKAGE_{name}=y", config)
                    for path in (core / "modules").glob("*.sh"):
                        self.assertNotIn("netwiz", path.read_text(encoding="utf-8"), path.name)
                    self.assertNotIn("fix_netwiz_permissions", (core / "update.sh").read_text(encoding="utf-8"))
                    self.assertNotIn("/etc/init.d/network", (core / "patches/992_set-wifi-uci.sh").read_text(encoding="utf-8"))
            finally:
                policy.ROOT = original


if __name__ == "__main__":
    unittest.main()
