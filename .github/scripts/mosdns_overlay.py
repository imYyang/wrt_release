#!/usr/bin/env python3
"""Bundle matching IPKs for offline first-boot installation, outside squashfs packages."""
from pathlib import Path
import hashlib
import io
import re
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"mosdns", "luci-app-mosdns", "luci-i18n-mosdns-zh-cn"}


def fields(text):
    result = {}
    for line in text.splitlines():
        if ': ' in line and not line[0].isspace():
            key, value = line.split(': ', 1)
            result[key] = value
    return result


def control(path):
    data = path.read_bytes()
    if data.startswith(b'!<arch>\n'):
        offset = 8
        while offset + 60 <= len(data):
            header = data[offset:offset + 60]
            size = int(header[48:58])
            name = header[:16].decode().strip().rstrip('/')
            offset += 60
            if name.startswith('control.tar'):
                with tarfile.open(fileobj=io.BytesIO(data[offset:offset + size])) as archive:
                    return fields(archive.extractfile(next(m for m in archive if m.name.lstrip('./') == 'control')).read().decode())
            offset += size + size % 2
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as outer:
            member = next(m for m in outer if Path(m.name).name.startswith('control.tar'))
            with tarfile.open(fileobj=io.BytesIO(outer.extractfile(member).read())) as archive:
                return fields(archive.extractfile(next(m for m in archive if m.name.lstrip('./') == 'control')).read().decode())
    raise RuntimeError(f'No IPK control metadata: {path}')


def names(value):
    return [re.split(r'[ (]', part.strip(), maxsplit=1)[0] for part in value.split(',') if part.strip()]


def closure(records, installed, required):
    providers = {name: name for name in records}
    for name, record in records.items():
        for virtual in names(record.get('Provides', '')):
            # Prefer an already-installed provider over an optional package.
            if virtual not in providers or name in installed:
                providers[virtual] = name
    selected = set()

    def visit(name):
        if name in installed or name in selected:
            return
        if name not in records:
            name = providers.get(name, name)
        if name in installed or name in selected:
            return
        if name not in records:
            raise RuntimeError(f'Missing MosDNS dependency: {name}')
        selected.add(name)
        for dependency in names(records[name].get('Depends', '')):
            visit(dependency)

    for name in sorted(required):
        visit(name)
    return selected


def prepare(build):
    config = (build / '.config').read_text()
    if 'CONFIG_USE_APK=y' in config:
        raise RuntimeError('MosDNS overlay installer requires this fork\'s opkg configuration')
    for name in REQUIRED:
        if f'CONFIG_PACKAGE_{name}=m\n' not in config:
            raise RuntimeError(f'{name} must be compiled as a removable module (=m)')
    manifests = [p for p in (build / 'bin/targets').rglob('*.manifest') if p.name != 'Packages.manifest']
    if not manifests:
        raise RuntimeError('Firmware manifests not found')
    installed_sets = [{line.split()[0] for line in p.read_text().splitlines() if line.strip()} for p in manifests]
    if any(REQUIRED & packages for packages in installed_sets):
        raise RuntimeError('MosDNS must not be installed into the read-only image')
    installed = set.intersection(*installed_sets)
    if 'opkg' not in installed:
        raise RuntimeError('opkg is not included in the firmware')
    records, paths = {}, {}
    for path in sorted((build / 'bin').rglob('*.ipk')):
        record = control(path)
        name = record['Package']
        if name in paths and paths[name].read_bytes() != path.read_bytes():
            raise RuntimeError(f'Ambiguous package versions: {name}')
        records[name], paths[name] = record, path
    selected = closure(records, installed, REQUIRED)
    destination = build / 'files/usr/share/yangwrt/mosdns-packages'
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    hashes = []
    for name in sorted(selected):
        source = paths[name]
        shutil.copy2(source, destination / source.name)
        hashes.append(f'{hashlib.sha256(source.read_bytes()).hexdigest()}  {source.name}\n')
    (destination / 'SHA256SUMS').write_text(''.join(hashes))
    for source, target in (
        ('install_mosdns', 'usr/sbin/yangwrt-install-mosdns'),
        ('99_install_mosdns', 'etc/uci-defaults/99_install_mosdns'),
    ):
        output = build / 'files' / target
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / '.github/defaults' / source, output)
        output.chmod(0o755)
    output = ROOT / 'mosdns-offline.tar.gz'
    with tarfile.open(output, 'w:gz') as archive:
        archive.add(destination, arcname='mosdns-packages')
    # This list describes overlay packages, not the firmware's built-in manifest.
    (ROOT / 'mosdns-overlay-packages.txt').write_text(''.join(
        f'{name} - {records[name]["Version"]}\n' for name in sorted(selected)))
    print(f'Offline MosDNS bundle: {len(selected)} packages, {output.stat().st_size} bytes')
    print((ROOT / 'mosdns-overlay-packages.txt').read_text())


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
