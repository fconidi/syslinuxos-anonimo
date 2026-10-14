import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

import client
from cli import main

SETTINGS = {'allow_lan': True, 'bridges': 'none', 'start_at_boot': False, 'close_apps': True}


def status(state='off', **extra):
    data = {'state': state, 'progress': 0, 'summary': '', 'error': None, 'clock_problem': False,
            'settings': dict(SETTINGS), 'unit': 'inactive'}
    data.update(extra)
    return data


class TTY(io.StringIO):
    def isatty(self):
        return True


class CliTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LANG': 'C.UTF-8'}, clear=True)
        self.env.start()
        self.out = io.StringIO()
        self.calls, self.closed, self.cleaned = [], [], []
        self.code, self.events, self.targets, self.current = 0, [], [], status()

        def run_helper(action, input_text, on_event):
            self.calls.append((action, input_text))
            for event in self.events:
                on_event(event)
            return self.code

        self.deps = SimpleNamespace(
            run_helper=run_helper, read_status=lambda: self.current,
            tor_check=lambda: {'is_tor': True, 'ip': '185.220.101.1'}, helper_exists=lambda: True,
            find_targets=lambda: list(self.targets), close_apps=self.closed.append,
            run_bleachbit=lambda: self.cleaned.append(True))

    def tearDown(self):
        self.env.stop()

    def run_cli(self, *argv, stdin=None):
        return main(list(argv), stdin=stdin or io.StringIO(), stdout=self.out, deps=self.deps)

    def test_status_exit_codes_and_json(self):
        for state, code in (('off', 3), ('protected', 0), ('connecting', 2), ('error', 1)):
            self.current = status(state)
            self.assertEqual(self.run_cli('status', '--json'), code)
        self.current = status('protected')
        self.out = io.StringIO()
        self.run_cli('status', '--json', '--check')
        data = json.loads(self.out.getvalue())
        self.assertEqual(data['check'], {'is_tor': True, 'ip': '185.220.101.1'})

    def test_status_text(self):
        self.current = status('connecting', progress=60)
        self.run_cli('status', '--check')
        self.assertEqual(self.out.getvalue().splitlines(),
                         ['Connecting · 60%', 'Traffic goes through Tor. Exit address: 185.220.101.1'])

    def test_status_error_tells_how_to_restore_the_network(self):
        self.current = status('error', error='Tor did not connect in time')
        self.assertEqual(self.run_cli('status'), 1)
        self.assertEqual(self.out.getvalue().splitlines(),
                         ['Error: Tor did not connect in time. Run "anonimo stop" to restore the normal network.'])

    def test_needs_installed_helper(self):
        self.deps.helper_exists = lambda: False
        self.assertEqual(self.run_cli('start'), 1)
        self.assertEqual(self.calls, [])
        self.assertIn('Install the syslinuxos-anonimo package', self.out.getvalue())

    def test_start_without_terminal_does_not_close_apps(self):
        self.targets = [(10, 'firefox')]
        self.events = [{'event': 'progress', 'progress': 50}, {'event': 'done', 'state': 'protected'}]
        self.assertEqual(self.run_cli('start'), 0)
        self.assertEqual(self.calls, [('start', None)])
        self.assertEqual(self.closed, [])
        self.assertEqual(self.out.getvalue().splitlines(),
                         ['Connecting to Tor… 50%', 'Protected: traffic goes through Tor.',
                          'Traffic goes through Tor. Exit address: 185.220.101.1'])

    def test_start_reports_traffic_outside_tor(self):
        self.events = [{'event': 'done', 'state': 'protected'}]
        self.deps.tor_check = lambda: {'is_tor': False, 'ip': '198.51.100.7'}
        self.assertEqual(self.run_cli('start', '--no-close-apps'), 1)
        self.assertEqual(self.out.getvalue().splitlines()[1:], [
            'Warning: traffic does NOT go through Tor. Address: 198.51.100.7',
            'Run "anonimo stop" to restore the normal network.'])

    def test_start_with_failed_check_warns_but_succeeds(self):
        self.events = [{'event': 'done', 'state': 'protected'}]

        def offline():
            raise client.CheckError('Cannot reach check.torproject.org')

        self.deps.tor_check = offline
        self.assertEqual(self.run_cli('start', '--no-close-apps'), 0)
        self.assertEqual(self.out.getvalue().splitlines()[1:], [
            'Tor check failed: Cannot reach check.torproject.org',
            'Run "anonimo stop" to restore the normal network.'])

    def test_no_check_when_start_does_not_reach_protected(self):
        checks = []
        self.deps.tor_check = lambda: checks.append(True) or {'is_tor': True, 'ip': 'x'}
        self.events = [{'event': 'error', 'message': 'Tor did not connect in time'}]
        self.code = 2
        self.assertEqual(self.run_cli('start', '--no-close-apps'), 2)
        self.assertEqual(checks, [])
        self.run_cli('stop', '--no-close-apps')
        self.assertEqual(checks, [])

    def test_start_that_ends_in_error_tells_how_to_restore_the_network(self):
        self.events = [{'event': 'progress', 'progress': 30},
                       {'event': 'error', 'message': 'Tor did not connect in time'}]
        self.code = 2
        self.assertEqual(self.run_cli('start', '--no-close-apps'), 2)
        self.assertEqual(self.out.getvalue().splitlines(), [
            'Connecting to Tor… 30%', 'Error: Tor did not connect in time',
            'Run "anonimo stop" to restore the normal network.'])

    def test_start_switched_off_meanwhile_prints_no_recovery_hint(self):
        self.events = [{'event': 'stopped'}]
        self.code = 3
        self.assertEqual(self.run_cli('start', '--no-close-apps'), 3)
        self.assertEqual(self.out.getvalue().splitlines(), ['anonimo was switched off.'])

    def test_explicit_close_apps(self):
        self.targets = [(10, 'firefox'), (11, 'firefox')]
        self.run_cli('stop', '--close-apps')
        self.assertEqual(self.closed, [[10, 11]])
        self.assertEqual(self.cleaned, [True])
        self.assertEqual(self.calls, [('stop', None)])

    def test_terminal_prompt(self):
        self.targets = [(10, 'thunderbird')]
        self.run_cli('start', stdin=TTY('n\n'))
        self.assertEqual(self.closed, [])
        self.assertIn('Close these applications first? thunderbird [y/N]', self.out.getvalue())
        self.run_cli('start', stdin=TTY('y\n'))
        self.assertEqual(self.closed, [[10]])

    def test_no_close_apps_flag(self):
        self.targets = [(10, 'firefox')]
        self.run_cli('start', '--no-close-apps', stdin=TTY('y\n'))
        self.assertEqual(self.closed, [])

    def test_settings_show_and_change(self):
        self.assertEqual(self.run_cli('settings'), 0)
        self.assertEqual(json.loads(self.out.getvalue()), SETTINGS)
        self.run_cli('settings', '--lan', 'off', '--boot', 'on', '--bridges', 'snowflake')
        action, text = self.calls[-1]
        self.assertEqual(action, 'set-settings')
        self.assertEqual(json.loads(text), {'allow_lan': False, 'bridges': 'snowflake',
                                            'start_at_boot': True, 'close_apps': True})

    def test_bridges(self):
        self.run_cli('bridges', '--set', '-', stdin=io.StringIO('obfs4 line\n'))
        self.assertEqual(self.calls[-1], ('set-bridges', 'obfs4 line\n'))
        self.events = [{'event': 'bridges', 'lines': ['obfs4 a', 'obfs4 b']}]
        self.out = io.StringIO()
        self.run_cli('bridges')
        self.assertEqual(self.calls[-1], ('get-bridges', None))
        self.assertEqual(self.out.getvalue().splitlines(), ['obfs4 a', 'obfs4 b'])

    def test_unreadable_bridge_file_reports_without_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'binary'
            binary.write_bytes(b'\xff\xfe obfs4 line\n')
            for path in ('/nonexistent/file', folder, str(binary)):
                with self.subTest(path=path):
                    self.out = io.StringIO()
                    self.calls.clear()
                    self.assertEqual(self.run_cli('bridges', '--set', path), 1)
                    self.assertEqual(self.calls, [])
                    self.assertEqual(self.out.getvalue().splitlines(),
                                     [f'Cannot read the bridge file: {path}'])

    def test_non_utf8_standard_input_reports_without_traceback(self):
        stdin = io.TextIOWrapper(io.BytesIO(b'\xff\xfe obfs4 line\n'), encoding='utf-8')
        self.assertEqual(self.run_cli('bridges', '--set', '-', stdin=stdin), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.out.getvalue().splitlines(), ['Cannot read the bridge file: -'])

    def test_authorization_failure(self):
        self.code = 126
        self.assertEqual(self.run_cli('identity'), 126)
        self.assertIn('Authorization cancelled or failed.', self.out.getvalue())


if __name__ == '__main__':
    unittest.main()
