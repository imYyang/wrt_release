"""Run the first-boot script with isolated UCI/service doubles, never host UCI."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
SOURCE = ROOT / ".github/defaults/9999_yangwrt_defaults"

MOCK_UCI = r'''
import json, os, sys
from pathlib import Path
p = Path(os.environ['MOCK_STATE'])
state = json.loads(p.read_text()) if p.exists() else {}
args = [a for a in sys.argv[1:] if a != '-q']
op, key = args[:2]
if op == 'get':
    if key not in state: sys.exit(1)
    print(state[key])
elif op == 'set':
    key, value = key.split('=', 1)
    state[key] = value
elif op == 'add_list':
    key, value = key.split('=', 1)
    state.setdefault(key, []).append(value)
elif op == 'delete':
    if key not in state: sys.exit(1)
    del state[key]
elif op != 'commit':
    raise AssertionError(op)
p.write_text(json.dumps(state))
'''

MOCK_FUNCTIONS = '''
uci() { "$TEST_PYTHON" "$MOCK_UCI" "$@"; }
config_load() { :; }
config_foreach() {
    case "$2" in
        system) "$1" cfg01 ;;
        wifi-device) "$1" radio0; "$1" radio1 ;;
        wifi-iface) "$1" default_radio0; "$1" default_radio1 ;;
        *) return 1 ;;
    esac
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix="yangwrt-defaults-") as directory:
        temp = Path(directory)
        mock = temp / "uci.py"
        mock.write_text(MOCK_UCI, encoding="utf-8")
        wireless = temp / "wireless"
        enabled = temp / "miniupnpd-enabled"
        script = SOURCE.read_text(encoding="utf-8")
        script = MOCK_FUNCTIONS + script.replace(". /lib/functions.sh", "")
        script = script.replace("/etc/config/wireless", shlex.quote(wireless.as_posix()))
        script = script.replace("/etc/config/yangwrt", shlex.quote((temp / "yangwrt").as_posix()))
        script = script.replace("/etc/init.d/miniupnpd enable", "touch " + shlex.quote(enabled.as_posix()))
        state_file = temp / "state.json"
        env = {**os.environ, "TEST_PYTHON": Path(sys.executable).as_posix(),
               "MOCK_UCI": mock.as_posix(), "MOCK_STATE": str(state_file)}

        # A missing wireless config must not mark partial initialization done.
        result = subprocess.run([BASH, "-s"], input=script, text=True, env=env, capture_output=True)
        assert result.returncode != 0
        assert "yangwrt.defaults.applied" not in json.loads(state_file.read_text())
        wireless.write_text("config wifi-device radio0\n", encoding="utf-8")
        subprocess.run([BASH, "-s"], input=script, text=True, env=env, check=True)
        state = json.loads(state_file.read_text())
        expected = {
            "network.lan.ipaddr": "10.10.10.1", "network.lan.netmask": "255.255.255.0",
            "system.cfg01.hostname": "YangHome-Gateway",
            "upnpd.config.enabled": "1", "upnpd.config.enable_upnp": "1",
            "rpcd.yangwrt_admin.username": "admin",
            "rpcd.yangwrt_admin.read": ["*"], "rpcd.yangwrt_admin.write": ["*"],
            "yangwrt.defaults.applied": "1",
        }
        for key, value in expected.items():
            assert state[key] == value, key
        for radio in ("radio0", "radio1"):
            assert state[f"wireless.{radio}.disabled"] == "1"
            assert state[f"wireless.default_{radio}.ssid"] == "YangWrt"
        assert enabled.exists()
        openssl = shutil.which("openssl") or r"C:\Program Files\Git\usr\bin\openssl.exe"
        password_hash = subprocess.check_output(
            [openssl, "passwd", "-6", "-salt", "YangWrt", "admin"], text=True).strip()
        assert state["rpcd.yangwrt_admin.password"] == password_hash

        # A saved configuration must survive a later sysupgrade/boot unchanged.
        state.update({"network.lan.ipaddr": "10.20.30.1", "wireless.radio0.disabled": "0",
                      "rpcd.yangwrt_admin.password": "user-changed-password-hash"})
        state_file.write_text(json.dumps(state))
        subprocess.run([BASH, "-s"], input=script, text=True, env=env, check=True)
        assert json.loads(state_file.read_text()) == state
    print("PASS factory defaults, admin password hash, incomplete setup retry and saved-config preservation")


if __name__ == "__main__":
    main()
