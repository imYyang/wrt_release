"""Protect the package hook and upstream-sync integration against regressions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fix", ROOT / ".github/scripts/fix_upnp_fullcone.py")
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


class UpnpTests(unittest.TestCase):
    def test_relocates_only_dnat_hook_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            nft = package / "files/nftables.d"
            old = nft / "chain-post/dstnat/20-miniupnpd.nft"
            old.parent.mkdir(parents=True)
            rule = 'jump upnp_prerouting comment "Hook into miniupnpd prerouting chain";\n'
            old.write_text(rule)
            other = nft / "chain-post/forward/20-miniupnpd.nft"
            other.parent.mkdir(parents=True)
            other.write_text("jump upnp_forward;\n")
            fix.patch(package)
            fix.patch(package)
            self.assertFalse(old.exists())
            self.assertEqual((nft / "chain-pre/dstnat/20-miniupnpd.nft").read_text(), rule)
            self.assertEqual(other.read_text(), "jump upnp_forward;\n")

    def test_unknown_layout_fails_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                fix.patch(Path(directory))

    def test_hook_after_feed_replacement(self):
        source = (ROOT / "wrt_core/update.sh").read_text(encoding="utf-8")
        self.assertIn('    fix_miniupnpd\n    python3 "$BASE_PATH/../.github/scripts/fix_upnp_fullcone.py" "$BUILD_DIR"\n', source)


if __name__ == "__main__":
    unittest.main()
