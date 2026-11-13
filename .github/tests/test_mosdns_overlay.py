#!/usr/bin/env python3
"""Exercise package metadata parsing and dependency bundling without an SDK."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('overlay', ROOT / '.github/scripts/mosdns_overlay.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def tar_bytes(name, content):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w:gz') as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return out.getvalue()


class OverlayTests(unittest.TestCase):
    def test_reads_tar_and_ar_ipk_control(self):
        content = b'Package: mosdns\nVersion: 5.3.4-r1\nDepends: ca-bundle, libc (>= 1.2)\n'
        control = tar_bytes('./control', content)
        header = f'{"control.tar.gz/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(control):<10}`\n'.encode()
        ar = b'!<arch>\n' + header + control + (b'\n' if len(control) % 2 else b'')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'package.ipk'
            for data in (tar_bytes('./control.tar.gz', control), ar):
                path.write_bytes(data)
                self.assertEqual(m.control(path)['Package'], 'mosdns')
                self.assertEqual(m.names(m.control(path)['Depends']), ['ca-bundle', 'libc'])

    def test_bundles_transitive_dependencies_and_uses_installed_provider(self):
        records = {
            'mosdns': {'Depends': 'geo2txt, virtual-tls (>= 1), libc'},
            'geo2txt': {'Depends': 'libc'},
            'libc': {},
            'tls-installed': {'Provides': 'virtual-tls'},
            'tls-optional': {'Provides': 'virtual-tls'},
        }
        self.assertEqual(m.closure(records, {'libc', 'tls-installed'}, {'mosdns'}), {'mosdns', 'geo2txt'})

    def test_missing_dependency_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing MosDNS dependency: rules'):
            m.closure({'mosdns': {'Depends': 'rules'}}, set(), {'mosdns'})

    def test_offline_bundle_contains_only_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build = root / 'sdk'
            packages = build / 'bin/packages/base'
            packages.mkdir(parents=True)
            targets = build / 'bin/targets/qualcommax/ipq807x'
            targets.mkdir(parents=True)
            (targets / 'firmware.manifest').write_text('opkg - 1\nlibc - 1\n')
            (build / '.config').write_text('CONFIG_USE_APK=n\n' + ''.join(
                f'CONFIG_PACKAGE_{name}=m\n' for name in sorted(m.REQUIRED)))
            records = {
                'mosdns': 'libc, geo2txt', 'geo2txt': 'libc',
                'luci-app-mosdns': 'mosdns', 'luci-i18n-mosdns-zh-cn': 'luci-app-mosdns',
            }
            for name, deps in records.items():
                content = f'Package: {name}\nVersion: 1-r1\nDepends: {deps}\n'.encode()
                (packages / f'{name}_1-r1_all.ipk').write_bytes(
                    tar_bytes('control.tar.gz', tar_bytes('control', content)))
            defaults = root / '.github/defaults'
            defaults.mkdir(parents=True)
            for name in ('install_mosdns', '99_install_mosdns'):
                (defaults / name).write_bytes((ROOT / '.github/defaults' / name).read_bytes())
            original_root = m.ROOT
            try:
                m.ROOT = root
                m.prepare(build)
                bundle = build / 'files/usr/share/yangwrt/mosdns-packages'
                self.assertEqual(len(list(bundle.glob('*.ipk'))), 4)
                self.assertTrue((root / 'mosdns-offline.tar.gz').is_file())
                self.assertTrue((build / 'files/etc/uci-defaults/99_install_mosdns').is_file())
                (targets / 'firmware.manifest').write_text('opkg - 1\nmosdns - 1\n')
                with self.assertRaisesRegex(RuntimeError, 'must not be installed'):
                    m.prepare(build)
            finally:
                m.ROOT = original_root

    def test_dependency_cycle_terminates(self):
        self.assertEqual(m.closure({'a': {'Depends': 'b'}, 'b': {'Depends': 'a'}}, set(), {'a'}), {'a', 'b'})


if __name__ == '__main__':
    unittest.main()
