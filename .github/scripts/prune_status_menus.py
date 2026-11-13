#!/usr/bin/env python3
"""Remove optional status entries without disabling networking protocols."""
import json
from pathlib import Path
import sys


def prune(root):
    for filename, entry in (
        ("luci-mod-status.json", "admin/status/channel_analysis"),
        ("luci-proto-wireguard.json", "admin/status/wireguard"),
    ):
        paths = list(root.rglob(filename))
        if not paths:
            raise RuntimeError(f"Missing LuCI menu source: {filename}")
        for path in paths:
            menu = json.loads(path.read_text(encoding="utf-8"))
            if entry in menu:
                del menu[entry]
                path.write_text(json.dumps(menu, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8", newline="\n")
                print(f"Removed {entry} from {path}")


if __name__ == "__main__":
    prune(Path(sys.argv[1]))
