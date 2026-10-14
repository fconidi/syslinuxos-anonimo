import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / 'packaging'
sys.path.insert(0, str(ROOT / 'source'))

sys.path.insert(0, str(ROOT / 'tests'))

import check_deb
from helper import ACTIONS
from paths import DEFAULT, HELPER
from settings import DEFAULT_SETTINGS


def text(name):
    return (PACKAGING / name).read_text(encoding='utf-8')


def case_branch(script, label):
    match = re.search(rf'^\s*{re.escape(label)}\)\n(.*?)^\s*;;', script, re.S | re.M)
    return match.group(1) if match else ''


def index_mode(path):
    """Mode recorded in the git index, or None when the file is not tracked."""
    try:
        result = subprocess.run(['git', 'ls-files', '-s', '--', str(path.relative_to(ROOT))],
                                cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.split()[0]


class PackagingTests(unittest.TestCase):
    def test_tor_unit(self):
        unit = text('syslinuxos-anonimo-tor.service')
        for line in ('User=_anonimo', 'Type=notify',
                     f'ExecStart=/usr/bin/tor --defaults-torrc /dev/null -f {DEFAULT.torrc} --RunAsDaemon 0',
                     'RuntimeDirectory=syslinuxos-anonimo/tor', 'StateDirectory=syslinuxos-anonimo/tor',
                     'Wants=syslinuxos-anonimo-watch.service', 'Restart=on-failure'):
            self.assertIn(line + '\n', unit)
        self.assertNotIn('[Install]', unit)
        self.assertEqual(DEFAULT.tor_run, Path('/run/syslinuxos-anonimo/tor'))
        self.assertEqual(DEFAULT.data_dir, Path('/var/lib/syslinuxos-anonimo/tor'))

    def test_watch_and_boot_units(self):
        watch = text('syslinuxos-anonimo-watch.service')
        for line in ('BindsTo=syslinuxos-anonimo-tor.service', 'User=_anonimo',
                     'RuntimeDirectory=syslinuxos-anonimo/status', 'RuntimeDirectoryMode=0755',
                     'ExecStart=/usr/lib/syslinuxos-anonimo/anonimo-watch'):
            self.assertIn(line + '\n', watch)
        boot = text('syslinuxos-anonimo-boot.service')
        for line in ('After=nftables.service', 'Before=network-pre.target shutdown.target',
                     'Wants=network-pre.target', f'ExecStart={HELPER} boot', 'WantedBy=multi-user.target'):
            self.assertIn(line + '\n', boot)

    def test_nftables_drop_in_reapplies_the_table(self):
        drop_in = text('nftables-syslinuxos-anonimo.conf')
        self.assertIn('[Service]\n', drop_in)
        for key in ('ExecStartPost', 'ExecReload', 'ExecStopPost'):
            self.assertIn(f'{key}=-{HELPER} reapply\n', drop_in)
        # Appended only: an empty ExecReload= would drop Debian's own reload.
        self.assertNotRegex(drop_in, r'(?m)^\s*Exec\w*=\s*$')
        self.assertIn('reapply', ACTIONS)
        build = (ROOT / 'build-deb.sh').read_text(encoding='utf-8')
        self.assertIn('packaging/nftables-syslinuxos-anonimo.conf', build)
        self.assertIn('usr/lib/systemd/system/nftables.service.d/$PKG_NAME.conf', build)
        self.assertIn('systemctl daemon-reload', case_branch(text('postinst'), 'configure'))
        self.assertIn('systemctl daemon-reload', case_branch(text('postrm'), 'remove'))

    def test_root_and_watcher_python_write_no_bytecode(self):
        # Root running the helper must not leave __pycache__ under /usr/lib, or
        # dpkg cannot remove the directory.
        for name in ('anonimo-helper', 'anonimo-watch'):
            with self.subTest(script=name):
                first = (ROOT / 'source' / name).read_text(encoding='utf-8').splitlines()[0]
                self.assertEqual(first, '#!/usr/bin/python3 -IB')

    def test_polkit_policy(self):
        root = ET.parse(PACKAGING / 'com.syslinuxos.anonimo.helper.policy').getroot()
        action = root.find('action')
        self.assertEqual(action.get('id'), 'com.syslinuxos.anonimo.helper')
        self.assertEqual(action.find('defaults/allow_active').text, 'auth_admin_keep')
        self.assertEqual(action.find('defaults/allow_any').text, 'no')
        self.assertEqual(action.find("annotate[@key='org.freedesktop.policykit.exec.path']").text, HELPER)
        languages = {m.get('{http://www.w3.org/XML/1998/namespace}lang') for m in action.findall('message')}
        self.assertEqual(languages, {None, 'it', 'fr', 'de', 'es'})

    def test_shell_scripts_parse(self):
        for name in ('postinst', 'prerm', 'postrm', 'anonimo', 'syslinuxos-anonimo'):
            with self.subTest(script=name):
                self.assertEqual(subprocess.run(['sh', '-n', str(PACKAGING / name)]).returncode, 0)
                # The git index holds the mode; Nextcloud sync may strip the working-tree bit.
                mode = index_mode(PACKAGING / name)
                if mode is not None:
                    self.assertTrue(mode.startswith('100755'), f'{name} is {mode} in the git index')

    def test_postinst_defaults_match_settings(self):
        script = text('postinst')
        default = re.search(r"printf '%s\\n' '(\{.*?\})'", script).group(1)
        self.assertEqual(json.loads(default), DEFAULT_SETTINGS)
        configure = case_branch(script, 'configure')
        self.assertIn('adduser --system --group', configure)
        self.assertIn('install -d -m 0700 -o _anonimo -g _anonimo "$LIB/tor"', configure)
        self.assertIn('disable_default_tor', configure)

    def test_postinst_enables_the_boot_unit_from_the_settings(self):
        # apt remove disables the unit but keeps settings.json: a reinstall must
        # enable it again when "start at boot" is on.
        script = text('postinst')
        configure = case_branch(script, 'configure')
        self.assertRegex(configure, r'if boot_wanted; then\n\s*systemctl enable syslinuxos-anonimo-boot\.service')
        self.assertNotRegex(configure, r'(grep|sed|awk|cut)[^\n]*settings\.json')   # no JSON parsing in sh
        code = re.search(r"^boot_wanted\(\) \{\n.*?<<'PY'[^\n]*\n(.*?)^PY$", script, re.S | re.M).group(1)
        self.assertIn('python3 -IB -', re.search(r'^boot_wanted\(\) \{\n(.*?)\n', script, re.M).group(1))
        self.assertIn("load_settings('/etc/syslinuxos-anonimo/settings.json')", code)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            code = (code.replace('/usr/lib/syslinuxos-anonimo', str(ROOT / 'source'))
                    .replace('/etc/syslinuxos-anonimo/settings.json', str(path)))
            for content, wanted in ((json.dumps(dict(DEFAULT_SETTINGS, start_at_boot=True)), True),
                                    (json.dumps(DEFAULT_SETTINGS), False), ('{broken', False), (None, False)):
                with self.subTest(content=content):
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_text(content)
                    result = subprocess.run([sys.executable, '-IB', '-c', code], capture_output=True)
                    self.assertEqual(result.returncode == 0, wanted, result.stderr)

    def test_postinst_upgrade_restarts_tor_and_watcher(self):
        configure = case_branch(text('postinst'), 'configure')
        upgrade = configure[configure.index('elif [ -d /run/systemd/system ]'):]
        restart = 'systemctl try-restart syslinuxos-anonimo-tor.service syslinuxos-anonimo-watch.service'
        self.assertIn(restart, upgrade)
        self.assertLess(upgrade.index(f'rm -f {DEFAULT.bootstrap}'), upgrade.index(restart))

    def test_prerm_stops_only_on_remove(self):
        script = text('prerm')
        self.assertIn(f'{HELPER} stop', case_branch(script, 'remove|deconfigure'))
        self.assertEqual(script.count(f'{HELPER} stop'), 1)
        self.assertNotIn('upgrade)', script)

    def test_postrm_remove_leaves_no_runtime_files(self):
        self.assertIn(f'rm -rf {DEFAULT.run}', case_branch(text('postrm'), 'remove'))

    def test_postrm_purge(self):
        purge = case_branch(text('postrm'), 'purge')
        self.assertIn('systemctl enable tor.service', purge)
        self.assertIn('rm -rf /etc/syslinuxos-anonimo /var/lib/syslinuxos-anonimo', purge)

    def test_man_page_and_changelog_carry_the_version(self):
        version = (ROOT / 'source' / 'VERSION').read_text(encoding='utf-8').strip()
        self.assertEqual(check_deb.version_problems(version, text('anonimo.1'), text('changelog')), [])
        self.assertEqual(len(check_deb.version_problems('2099.1.1', text('anonimo.1'), text('changelog'))), 2)

    def test_desktop_entry(self):
        desktop = text('syslinuxos-anonimo.desktop')
        self.assertIn('Exec=syslinuxos-anonimo\n', desktop)
        self.assertIn('X-SysLinuxOS-Tools;', desktop)
        for language in ('it', 'fr', 'de', 'es'):
            self.assertIn(f'Comment[{language}]=', desktop)

    def test_icons(self):
        for state in ('off', 'connecting', 'protected', 'error'):
            ET.parse(PACKAGING / 'icons' / f'anonimo-{state}.svg')
        ET.parse(PACKAGING / 'syslinuxos-anonimo.svg')


if __name__ == '__main__':
    unittest.main()
