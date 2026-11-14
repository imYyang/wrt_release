#!/usr/bin/env python3
"""Run after miniupnpd feed synchronization, before packaging."""
from pathlib import Path
import sys


def patch(package):
    nft = package / "files/nftables.d"
    old = nft / "chain-post/dstnat/20-miniupnpd.nft"
    new = nft / "chain-pre/dstnat/20-miniupnpd.nft"
    source = old if old.exists() else new
    if not source.is_file() or "jump upnp_prerouting" not in source.read_text():
        raise RuntimeError("Unsupported miniupnpd nftables layout; refusing an unpatched build")
    if old.exists():
        if new.exists() and new.read_bytes() != old.read_bytes():
            raise RuntimeError("Conflicting miniupnpd prerouting hooks")
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_bytes(old.read_bytes())
        old.unlink()
    # The package copies files/nftables.d recursively. Keep other hooks intact.
    print("miniupnpd: UPnP DNAT now runs before WAN Full Cone NAT")


if __name__ == "__main__":
    patch(Path(sys.argv[1]) / "feeds/packages/net/miniupnpd")
