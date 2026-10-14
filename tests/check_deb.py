"""Inspect a built syslinuxos-anonimo .deb: files, permissions, owners,
control fields and maintainer scripts. Test tool only. GPL-3.0-or-later."""

import gzip
import io
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
LIB = './usr/lib/syslinuxos-anonimo/'
EXECUTABLE = '-rwxr-xr-x'
REGULAR = '-rw-r--r--'


def expected_files():
    files = {LIB + path.name: REGULAR for path in (ROOT / 'source').glob('*.py')}
    files.update({
        LIB + 'VERSION': REGULAR,
        LIB + 'anonimo-helper': EXECUTABLE,
        LIB + 'anonimo-watch': EXECUTABLE,
        './usr/bin/anonimo': EXECUTABLE,
        './usr/bin/syslinuxos-anonimo': EXECUTABLE,
        './usr/share/polkit-1/actions/com.syslinuxos.anonimo.helper.policy': REGULAR,
        './usr/share/applications/syslinuxos-anonimo.desktop': REGULAR,
        './etc/xdg/menus/applications-merged/syslinuxos-anonimo.menu': REGULAR,
        './usr/share/icons/hicolor/scalable/apps/syslinuxos-anonimo.svg': REGULAR,
        './usr/share/syslinuxos-anonimo/snowflake-bridges': REGULAR,
        './usr/share/doc/syslinuxos-anonimo/README.md': REGULAR,
        './usr/share/doc/syslinuxos-anonimo/UPSTREAM.md': REGULAR,
        './usr/share/doc/syslinuxos-anonimo/copyright': REGULAR,
        './usr/share/doc/syslinuxos-anonimo/changelog.gz': REGULAR,
        './usr/share/man/man1/anonimo.1.gz': REGULAR,
    })
    for unit in ('tor', 'watch', 'boot'):
        files[f'./usr/lib/systemd/system/syslinuxos-anonimo-{unit}.service'] = REGULAR
    files['./usr/lib/systemd/system/nftables.service.d/syslinuxos-anonimo.conf'] = REGULAR
    for state in ('off', 'connecting', 'protected', 'error'):
        files[f'./usr/share/syslinuxos-anonimo/icons/anonimo-{state}.svg'] = REGULAR
    return files


def dpkg(*args):
    return subprocess.run(['dpkg-deb', *args], capture_output=True, text=True, check=True).stdout


def member_text(deb, path):
    """Text of a gzip-compressed file inside the package."""
    data = subprocess.run(['dpkg-deb', '--fsys-tarfile', deb], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return gzip.decompress(archive.extractfile(path).read()).decode('utf-8')


def version_problems(version, man_page, changelog):
    """source/VERSION is the single source of truth; the man page header and
    the changelog repeat it."""
    result = []
    header = (man_page.splitlines() or [''])[0]
    if not header.startswith('.TH ') or f'"syslinuxos-anonimo {version}"' not in header:
        result.append(f'man page header does not name {version}: {header}')
    first = (changelog.splitlines() or [''])[0]
    if not first.startswith(f'syslinuxos-anonimo ({version}) '):
        result.append(f'changelog does not start with {version}: {first}')
    return result


def problems(deb):
    found = {}
    for line in dpkg('-c', deb).splitlines():
        parts = line.split()
        found[parts[5]] = (parts[0], parts[1])
    result = []
    for path, mode in expected_files().items():
        if path not in found:
            result.append(f'missing {path}')
        elif found[path][0] != mode:
            result.append(f'{path}: {found[path][0]} instead of {mode}')
    for path, (mode, owner) in found.items():
        if owner != 'root/root':
            result.append(f'{path}: owner {owner}')
        if mode[0] == '-' and 'w' in mode[5] + mode[8]:
            result.append(f'{path}: writable by group or others')
    version = (ROOT / 'source' / 'VERSION').read_text().strip()
    fields = {key: dpkg('-f', deb, key).strip() for key in ('Package', 'Version', 'Architecture', 'Depends')}
    if fields != {'Package': 'syslinuxos-anonimo', 'Version': version, 'Architecture': 'all',
                  'Depends': fields['Depends']}:
        result.append(f'control fields: {fields}')
    result += version_problems(version, member_text(deb, './usr/share/man/man1/anonimo.1.gz'),
                               member_text(deb, './usr/share/doc/syslinuxos-anonimo/changelog.gz'))
    for dependency in ('python3-pyqt5', 'libqt5svg5', 'tor', 'nftables', 'pkexec', 'adduser'):
        if dependency not in fields['Depends']:
            result.append(f'Depends lacks {dependency}')
    info = dpkg('-I', deb)
    for script in ('postinst', 'prerm', 'postrm', 'conffiles'):
        if script not in info:
            result.append(f'control member {script} missing')
    conffiles = dpkg('-I', deb, 'conffiles').split()
    if conffiles != ['/etc/xdg/menus/applications-merged/syslinuxos-anonimo.menu']:
        result.append(f'conffiles: {conffiles}')
    return result


if __name__ == '__main__':
    issues = problems(sys.argv[1])
    for issue in issues:
        print('PACKAGE CHECK FAILED:', issue, file=sys.stderr)
    if not issues:
        print('Package check passed:', sys.argv[1])
    sys.exit(1 if issues else 0)
