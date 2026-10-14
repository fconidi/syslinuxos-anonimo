import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

import client
from i18n import TRANSLATIONS
from paths import Paths
from state import write_json_atomic


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeStdin:
    def __init__(self):
        self.text, self.closed = '', False

    def write(self, text):
        self.text += text

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, lines, code):
        self.stdin, self.stdout, self.code = FakeStdin(), iter(lines), code

    def wait(self):
        return self.code


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'LANG': 'C.UTF-8'}, clear=True)
        self.env.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = Paths.under(self.tmp.name)
        for directory in (self.paths.etc, self.paths.run, self.paths.bootstrap.parent):
            directory.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()
        self.env.stop()

    def test_read_status(self):
        self.assertEqual(client.read_status(self.paths, unit='inactive')['state'], 'off')
        write_json_atomic(self.paths.mode, {'mode': 'on', 'error': None})
        write_json_atomic(self.paths.bootstrap, {'progress': 45, 'summary': 'Loading'})
        status = client.read_status(self.paths, unit='active')
        self.assertEqual((status['state'], status['progress'], status['summary']), ('connecting', 45, 'Loading'))
        self.assertEqual(status['settings']['bridges'], 'none')
        failed = client.read_status(self.paths, unit='failed')
        self.assertEqual((failed['state'], failed['error']), ('error', 'Tor is not running'))
        self.paths.settings.write_text('{broken')
        self.assertTrue(client.read_status(self.paths, unit='active')['settings']['allow_lan'])

    def test_unit_state(self):
        run = lambda argv, **kw: subprocess.CompletedProcess(argv, 3, 'inactive\n', '')
        self.assertEqual(client.unit_state(run=run), 'inactive')
        def broken(argv, **kw):
            raise FileNotFoundError
        self.assertEqual(client.unit_state(run=broken), 'unknown')

    def test_describe(self):
        base = {'progress': 0, 'error': None, 'clock_problem': False}
        self.assertEqual(client.describe(dict(base, state='protected')), 'Protected')
        self.assertEqual(client.describe(dict(base, state='connecting', progress=40)), 'Connecting · 40%')
        text = client.describe(dict(base, state='error', error='Tor did not connect in time', clock_problem=True))
        self.assertEqual(text, 'Error: Tor did not connect in time. Check that the date and time of this computer '
                               'are correct. Switch anonimo off to restore the normal network.')
        punctuated = client.describe(dict(base, state='error', error='Stopped.', clock_problem=True))
        self.assertEqual(punctuated, 'Error: Stopped. Check that the date and time of this computer are correct. '
                                     'Switch anonimo off to restore the normal network.')
        self.assertEqual(client.describe(dict(base, state='error', error='Tor is not running')),
                         'Error: Tor is not running. Switch anonimo off to restore the normal network.')
        self.assertEqual(client.describe(dict(base, state='error', error='Tor is not running'), cli=True),
                         'Error: Tor is not running. Run "anonimo stop" to restore the normal network.')
        with patch.dict(os.environ, {'LANG': 'it_IT.UTF-8'}):
            self.assertEqual(client.describe(dict(base, state='error', error='Tor is not running')),
                             'Errore: Tor non è in esecuzione. Spegni anonimo per ripristinare la rete normale.')
            self.assertEqual(client.describe(dict(base, state='error', error='Tor is not running'), cli=True),
                             'Errore: Tor non è in esecuzione. Esegui "anonimo stop" per ripristinare la rete normale.')

    def test_not_tor_status(self):
        status = client.not_tor_status({'state': 'protected', 'progress': 100, 'error': None, 'clock_problem': False})
        self.assertEqual(status['state'], 'error')
        self.assertEqual(client.describe(status),
                         'Error: Traffic does not go through Tor. Switch anonimo off to restore the normal network.')
        self.assertIn(client.NOT_TOR, TRANSLATIONS)

    def test_state_labels_are_translated(self):
        for label in client.STATE_LABELS.values():
            self.assertIn(label, TRANSLATIONS)

    def test_helper_argv(self):
        self.assertEqual(client.helper_argv('start', gui=False),
                         ['/usr/bin/pkexec', '/usr/lib/syslinuxos-anonimo/anonimo-helper', 'start'])
        self.assertEqual(client.helper_argv('stop', gui=True)[:2], ['/usr/bin/pkexec', '--disable-internal-agent'])

    def test_events(self):
        self.assertIsNone(client.parse_event('not json'))
        self.assertIsNone(client.parse_event('[1]'))
        self.assertEqual(client.parse_event('{"event": "stopped"}'), {'event': 'stopped'})
        self.assertEqual(client.event_text({'event': 'progress', 'progress': 30}), 'Connecting to Tor… 30%')
        self.assertEqual(client.event_text({'event': 'done', 'state': 'protected'}), 'Protected: traffic goes through Tor.')
        self.assertEqual(client.event_text({'event': 'done', 'state': 'bridges', 'count': 2}), 'Bridges saved: 2')
        self.assertEqual(client.event_text({'event': 'error', 'message': 'raw {x}'}), 'Error: raw {x}')
        self.assertEqual(client.event_text({'event': 'unknown'}), '')

    def test_run_helper_streams_events_and_input(self):
        process = FakeProcess(['{"event": "progress", "progress": 5}\n', 'noise\n', '{"event": "done", "state": "settings"}\n'], 0)
        argv_seen, events = [], []

        def popen(argv, **kwargs):
            argv_seen.append(argv)
            return process

        code = client.run_helper('set-settings', '{"allow_lan": true}', events.append, popen=popen)
        self.assertEqual(code, 0)
        self.assertEqual(argv_seen[0][-1], 'set-settings')
        self.assertEqual(process.stdin.text, '{"allow_lan": true}')
        self.assertTrue(process.stdin.closed)
        self.assertEqual([e['event'] for e in events], ['progress', 'done'])

    def test_tor_check(self):
        ok = client.tor_check(urlopen=lambda url, timeout: Response(b'{"IsTor":true,"IP":"185.220.101.1"}'))
        self.assertEqual(ok, {'is_tor': True, 'ip': '185.220.101.1'})
        self.assertIn('185.220.101.1', client.check_text(ok))
        self.assertIn('NOT', client.check_text({'is_tor': False, 'ip': '1.2.3.4'}))
        with self.assertRaisesRegex(client.CheckError, 'Unexpected answer'):
            client.tor_check(urlopen=lambda url, timeout: Response(b'{"ip": 1}'))
        def offline(url, timeout):
            raise OSError('unreachable')
        with self.assertRaisesRegex(client.CheckError, 'Cannot reach'):
            client.tor_check(urlopen=offline)
        self.assertEqual(client.check_text({'error': 'Cannot reach check.torproject.org'}),
                         'Tor check failed: Cannot reach check.torproject.org')

    def test_autostart(self):
        env = {'XDG_CONFIG_HOME': os.path.join(self.tmp.name, 'config')}
        self.assertFalse(client.autostart_enabled(env))
        client.set_autostart(True, env)
        path = client.autostart_path(env)
        self.assertTrue(path.is_file())
        self.assertIn('Exec=syslinuxos-anonimo --tray', path.read_text())
        client.set_autostart(False, env)
        self.assertFalse(client.autostart_enabled(env))
        self.assertEqual(client.autostart_path({}, home='/home/x'),
                         Path('/home/x/.config/autostart/syslinuxos-anonimo.desktop'))


if __name__ == '__main__':
    unittest.main()
