import base64
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))

from helper import Helper, HelperError, main
from paths import BOOT_UNIT, NFT, RUNUSER, SYSTEMCTL, TOR_UNIT, Paths
from state import read_json, write_json_atomic

CERT = base64.b64encode(bytes(range(52))).decode().rstrip('=')
LINE = f'obfs4 192.0.2.10:443 0123456789ABCDEF0123456789ABCDEF01234567 cert={CERT} iat-mode=0'


class FakeControl:
    def __init__(self, system):
        self.system = system

    def newnym(self):
        self.system.newnyms += 1


class FakeSystem:
    def __init__(self, paths):
        self.paths = paths
        self.calls, self.inputs, self.fail = [], {}, {}
        self.unit = 'inactive'
        self.clock = 0.0
        self.on_sleep = None
        self.bootstrap_progress = 100
        self.stale_bootstrap = False
        self.programs = True
        self.tor_user = True
        self.newnyms = 0

    def run(self, argv, input_text=None, timeout=120):
        self.calls.append(list(argv))
        if input_text is not None:
            self.inputs[argv[0]] = input_text
        code, out, err = self.fail.get(tuple(argv[:2]), (0, '', ''))
        if code == 0 and argv[0] == SYSTEMCTL and argv[1] in ('restart', 'start'):
            self.unit = 'active'
            self.paths.bootstrap.parent.mkdir(parents=True, exist_ok=True)
            if self.stale_bootstrap:
                # The watcher's last poll of the old Tor, written during the restart.
                write_json_atomic(self.paths.bootstrap, {'progress': 100, 'summary': 'old', 'updated': self.wall()})
            elif self.bootstrap_progress is not None:
                # The watcher's first poll of the new Tor, after the restart returned.
                write_json_atomic(self.paths.bootstrap, {'progress': self.bootstrap_progress, 'summary': 'x',
                                                         'updated': self.wall() + 1})
        if code == 0 and argv[0] == SYSTEMCTL and argv[1] == 'stop':
            self.unit = 'inactive'
        return subprocess.CompletedProcess(argv, code, out, err)

    def exists(self, path):
        return self.programs

    def tor_ids(self):
        if not self.tor_user:
            raise HelperError('System user _anonimo is missing')
        return os.getuid(), os.getgid()

    def unit_state(self, unit):
        return self.unit

    def control(self, paths):
        return FakeControl(self)

    def time(self):
        return self.clock

    def wall(self):
        return 1800000000.0 + self.clock

    def sleep(self, seconds):
        self.clock += seconds
        if self.on_sleep:
            self.on_sleep()

    def now_iso(self):
        return '2026-10-13T19:00:00+00:00'


class HelperTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = Paths.under(self.tmp.name)
        self.paths.etc.mkdir()
        self.paths.share.mkdir()
        shutil.copy(ROOT / 'packaging' / 'snowflake-bridges', self.paths.snowflake_bridges)
        self.system = FakeSystem(self.paths)
        self.out = io.StringIO()
        self.helper = Helper(self.system, self.paths, self.out)

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, **values):
        data = {'allow_lan': True, 'bridges': 'none', 'start_at_boot': False, 'close_apps': True}
        data.update(values)
        self.paths.settings.write_text(json.dumps(data))

    def main(self, action, text=None):
        stdin = io.StringIO(text) if text is not None else None
        return main([action], stdin=stdin, stdout=self.out, system=self.system, paths=self.paths)

    def unreadable_snowflake_file(self):
        """A directory in place of the bridge file: opening it raises IsADirectoryError."""
        self.paths.snowflake_bridges.unlink()
        self.paths.snowflake_bridges.mkdir()

    def events(self):
        return [json.loads(line) for line in self.out.getvalue().splitlines()]

    def mode(self):
        return read_json(self.paths.mode)

    def called(self, *prefix):
        return any(call[:len(prefix)] == list(prefix) for call in self.system.calls)

    def index(self, *prefix):
        return next(i for i, call in enumerate(self.system.calls) if call[:len(prefix)] == list(prefix))


class StartStopTests(HelperTestCase):
    def test_start_loads_firewall_then_starts_tor_and_waits(self):
        self.settings()
        self.assertEqual(self.helper.start(), 0)
        self.assertLess(self.index(RUNUSER, '-u', '_anonimo'), self.index(NFT, '-f'))
        self.assertLess(self.index(NFT, '-f'), self.index(SYSTEMCTL, 'restart', TOR_UNIT))
        rules = self.system.inputs[NFT]
        self.assertIn(f'meta skuid {os.getuid()} return', rules)
        self.assertIn('ip daddr @lan4 return', rules)
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertIsNone(self.mode()['error'])
        self.assertEqual(self.paths.torrc.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'protected'})

    def test_start_with_invalid_settings_changes_nothing(self):
        self.paths.settings.write_text('{broken')
        self.assertEqual(self.main('start'), 1)
        self.assertFalse(self.called(NFT))
        self.assertIsNone(self.mode())
        self.assertEqual(self.events()[-1], {'event': 'error', 'message': 'Cannot read settings'})

    def test_start_with_unreadable_bridge_file_reports_error(self):
        self.settings(bridges='snowflake')
        self.unreadable_snowflake_file()
        self.assertEqual(self.main('start'), 1)
        self.assertFalse(self.called(NFT))
        self.assertIsNone(self.mode())
        self.assertEqual(self.events()[-1]['event'], 'error')
        self.assertTrue(self.events()[-1]['message'])

    def test_start_rejected_config_changes_nothing(self):
        self.settings()
        self.system.fail[(RUNUSER, '-u')] = (1, '[warn] Failed to parse/validate config', '')
        self.assertEqual(self.main('start'), 1)
        self.assertFalse(self.called(NFT))
        self.assertIn('Tor rejected the configuration', self.events()[-1]['message'])

    def test_bridges_obfs4_without_program_changes_nothing(self):
        self.settings(bridges='obfs4')
        self.paths.obfs4_bridges.write_text(LINE + '\n')
        self.system.programs = False
        self.assertEqual(self.main('start'), 1)
        self.assertFalse(self.called(NFT))
        self.assertEqual(self.events()[-1]['message'], 'The obfs4 bridge program is not installed')

    def test_start_timeout_fails_closed(self):
        self.settings()
        self.system.bootstrap_progress = 40
        self.assertEqual(self.helper.start(), 2)
        self.assertEqual(self.mode()['error'], 'Tor did not connect in time')
        self.assertFalse(self.called(NFT, 'delete'))
        self.assertGreaterEqual(self.system.clock, 90)

    def test_stale_bootstrap_of_the_old_tor_is_ignored(self):
        # The old Tor's 100 % lands after the unlink: it must not count as connected.
        self.settings()
        self.system.stale_bootstrap = True
        self.assertEqual(self.helper.start(), 2)
        self.assertEqual(self.mode()['error'], 'Tor did not connect in time')
        self.assertNotIn({'event': 'done', 'state': 'protected'}, self.events())

    def test_tor_unit_failure_fails_closed(self):
        self.settings()
        self.system.bootstrap_progress = 10
        self.system.on_sleep = lambda: setattr(self.system, 'unit', 'failed')
        self.assertEqual(self.helper.start(), 2)
        self.assertEqual(self.mode()['error'], 'Tor stopped with an error')
        self.assertFalse(self.called(NFT, 'delete'))

    def test_tor_unit_inactive_fails_at_once(self):
        # Tor exited cleanly or was stopped by hand: do not wait for the timeout.
        self.settings()
        self.system.bootstrap_progress = 10
        self.system.on_sleep = lambda: setattr(self.system, 'unit', 'inactive')
        self.assertEqual(self.helper.start(), 2)
        self.assertEqual(self.mode()['error'], 'Tor is not running')
        self.assertFalse(self.called(NFT, 'delete'))
        self.assertLess(self.system.clock, 5)

    def test_off_between_mode_and_unit_checks_is_not_an_error(self):
        self.settings()
        self.system.bootstrap_progress = 10
        stopper = Helper(self.system, self.paths, io.StringIO())

        def unit_state(unit):
            del self.system.unit_state          # once: back to the class method
            stopper.stop()
            return self.system.unit

        self.system.unit_state = unit_state
        self.assertEqual(self.helper.start(), 3)
        self.assertEqual(self.events()[-1], {'event': 'stopped'})
        self.assertEqual((self.mode()['mode'], self.mode()['error']), ('off', None))

    def test_systemctl_failure_keeps_firewall_loaded(self):
        self.settings()
        self.system.fail[(SYSTEMCTL, 'restart')] = (1, '', 'Job failed')
        self.assertEqual(self.main('start'), 1)
        self.assertTrue(self.called(NFT, '-f'))
        self.assertEqual(self.mode()['error'], 'Cannot start Tor')

    def test_stop_while_waiting_for_bootstrap(self):
        self.settings()
        self.system.bootstrap_progress = 40
        stopper = Helper(self.system, self.paths, io.StringIO())
        results = []
        self.system.on_sleep = lambda: results or results.append(stopper.stop())
        self.assertEqual(self.helper.start(), 3)
        self.assertEqual(results, [0])
        self.assertEqual(self.mode()['mode'], 'off')
        self.assertIsNone(self.mode()['error'])
        self.assertTrue(self.called(NFT, 'delete'))
        self.assertEqual(self.events()[-1], {'event': 'stopped'})

    def test_stop_is_idempotent_and_needs_no_settings(self):
        self.paths.settings.write_text('{broken')
        self.system.fail[(NFT, 'delete')] = (1, '', 'Error: Could not process rule: No such file or directory')
        for _ in range(2):
            self.assertEqual(self.main('stop'), 0)
        self.assertEqual(self.mode()['mode'], 'off')
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'off'})

    def test_stop_writes_off_before_stopping_tor(self):
        # Readers must not see "protected" while Tor stops and traffic is already clear.
        self.settings()
        self.helper.start()
        seen, real_run = {}, self.system.run

        def run(argv, input_text=None, timeout=120):
            if argv[:2] == [SYSTEMCTL, 'stop']:
                seen.update(mode=self.mode()['mode'], table_deleted=self.called(NFT, 'delete'))
            return real_run(argv, input_text, timeout)

        self.system.run = run
        self.assertEqual(self.helper.stop(), 0)
        self.assertEqual(seen, {'mode': 'off', 'table_deleted': True})

    def test_stop_leaves_no_torrc_behind(self):
        self.settings()
        self.helper.start()
        self.assertTrue(self.paths.torrc.exists())
        self.assertEqual(self.helper.stop(), 0)
        self.assertFalse(self.paths.torrc.exists())

    def test_stop_reports_real_nft_error(self):
        self.system.fail[(NFT, 'delete')] = (1, '', 'Error: Operation not permitted')
        self.assertEqual(self.main('stop'), 1)
        self.assertIn('Cannot remove the firewall rules', self.events()[-1]['message'])


class BootTests(HelperTestCase):
    def test_boot_loads_firewall_without_waiting(self):
        self.settings()
        self.assertEqual(self.helper.boot(), 0)
        self.assertTrue(self.called(SYSTEMCTL, 'start', '--no-block', TOR_UNIT))
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertEqual(self.system.clock, 0)
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'connecting'})

    def test_boot_with_broken_settings_still_fails_closed(self):
        self.paths.settings.write_text('{broken')
        self.assertEqual(self.main('boot'), 1)
        self.assertIn('ip daddr @lan4 return', self.system.inputs[NFT])
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertEqual(self.mode()['error'], 'Cannot read settings')
        self.assertFalse(self.called(SYSTEMCTL, 'start'))


    def test_boot_without_tor_user_blocks_everything(self):
        # The only boot path that loaded nothing: now a table without the Tor exemption.
        self.settings()
        self.system.tor_user = False
        self.assertEqual(self.main('boot'), 1)
        rules = self.system.inputs[NFT]
        self.assertNotIn('skuid', rules)
        self.assertIn('policy drop', rules)
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertEqual(self.mode()['error'], 'System user _anonimo is missing')
        self.assertFalse(self.called(SYSTEMCTL, 'start'))
        self.assertEqual(self.events()[-1], {'event': 'error', 'message': 'System user _anonimo is missing'})

    def test_boot_with_unreadable_bridge_file_still_fails_closed(self):
        self.settings(bridges='snowflake')
        self.unreadable_snowflake_file()
        self.assertEqual(self.main('boot'), 1)
        self.assertIn('ip daddr @lan4 return', self.system.inputs[NFT])
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertTrue(self.mode()['error'])
        self.assertFalse(self.called(SYSTEMCTL, 'start'))
        self.assertEqual(self.events()[-1]['event'], 'error')


class ReapplyTests(HelperTestCase):
    """nftables.service flushes the whole ruleset; its drop-in runs reapply."""

    def test_does_nothing_when_off(self):
        self.assertEqual(self.main('reapply'), 0)
        self.assertEqual(self.system.calls, [])
        self.assertFalse(self.paths.run.exists())      # early boot: not even the lock file
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'off'})

    def test_reloads_the_table_when_on(self):
        self.settings(allow_lan=False)
        self.helper.start()
        mode = self.mode()
        self.system.calls.clear()
        self.assertEqual(self.main('reapply'), 0)
        self.assertEqual([call[:2] for call in self.system.calls], [[NFT, '-f'], [NFT, '-f']])
        self.assertIn(f'meta skuid {os.getuid()} return', self.system.inputs[NFT])
        self.assertNotIn('@lan4', self.system.inputs[NFT])
        self.assertEqual(self.mode(), mode)
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'reapplied'})

    def test_broken_settings_reload_the_defaults(self):
        self.settings()
        self.helper.start()
        self.paths.settings.write_text('{broken')
        self.system.inputs.clear()
        self.assertEqual(self.main('reapply'), 0)
        self.assertIn('ip daddr @lan4 return', self.system.inputs[NFT])

    def test_missing_tor_user_still_loads_a_table(self):
        self.settings()
        self.helper.start()
        self.system.tor_user = False
        self.system.inputs.clear()
        self.assertEqual(self.main('reapply'), 0)
        self.assertNotIn('skuid', self.system.inputs[NFT])

    def test_busy_lock_still_loads_the_table(self):
        self.settings()
        self.helper.start()
        self.system.calls.clear()
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(self.main('reapply'), 0)
        finally:
            os.close(fd)
        self.assertTrue(self.called(NFT, '-f'))
        self.assertFalse(self.called(NFT, 'delete'))

    def test_off_that_ran_meanwhile_wins(self):
        self.settings()
        self.helper.start()
        self.system.calls.clear()
        stopper, real_run = Helper(self.system, self.paths, io.StringIO()), self.system.run

        def run(argv, input_text=None, timeout=120):
            result = real_run(argv, input_text, timeout)
            if argv[:2] == [NFT, '-f'] and self.system.run is run:
                self.system.run = real_run
                stopper.stop()                  # Off between the first load and the lock
            return result

        self.system.run = run
        self.assertEqual(self.main('reapply'), 0)
        self.assertEqual(self.mode()['mode'], 'off')
        self.assertEqual(self.system.calls[-1][:2], [NFT, 'delete'])


    def test_off_with_a_run_directory_does_not_load_a_table(self):
        self.settings()
        self.helper.start()
        Helper(self.system, self.paths, io.StringIO()).stop()
        self.system.calls.clear()
        self.assertEqual(self.main('reapply'), 0)
        self.assertEqual(self.system.calls, [])
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'off'})

    def test_busy_lock_after_an_off_read_looks_at_the_mode_again(self):
        self.settings()
        self.helper.start()
        Helper(self.system, self.paths, io.StringIO()).stop()
        self.system.calls.clear()
        self.system.on_sleep = lambda: self.helper._write_mode('on')       # a start() finishes meanwhile
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(self.main('reapply'), 0)
        finally:
            os.close(fd)
        self.assertEqual([call[:2] for call in self.system.calls], [[NFT, '-f']])
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'reapplied'})

    def test_start_that_a_flush_overtakes_ends_with_the_table_loaded(self):
        """nftables.service flushes the ruleset after start() loaded its table
        but before start() wrote mode=on; reapply's first read sees "off". The
        table has to be back once both are done."""
        self.settings()
        table = {'loaded': False}
        flushed, first_read, real_run = threading.Event(), threading.Event(), self.system.run
        failures = []

        def run(argv, input_text=None, timeout=120):
            result = real_run(argv, input_text, timeout)
            if argv[:2] == [NFT, '-f']:
                table['loaded'] = True
                if not flushed.is_set():
                    table['loaded'] = False                 # the flush, right after start's load
                    flushed.set()
                    first_read.wait(5)                      # start() is held up inside its window
            elif argv[:2] == [NFT, 'delete']:
                table['loaded'] = False
            return result

        self.system.run = run

        class RealClock:
            """The shared fake system, with a real clock so the lock wait really waits."""
            def __init__(self, system):
                self.system = system

            def __getattr__(self, name):
                return getattr(self.system, name)

            def time(self):
                return time.monotonic()

            def sleep(self, seconds):
                time.sleep(0.01)

        reapplier = Helper(RealClock(self.system), self.paths, io.StringIO())
        real_is_on = reapplier._is_on

        def is_on():
            result = real_is_on()
            first_read.set()
            return result

        reapplier._is_on = is_on

        def guarded(action):
            try:
                action()
            except BaseException as error:               # reported through the assertion below
                failures.append(error)

        def reapply_after_the_flush():
            flushed.wait(5)
            reapplier.reapply()

        threads = [threading.Thread(target=guarded, args=(self.helper.start,)),
                   threading.Thread(target=guarded, args=(reapply_after_the_flush,))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(failures, [])
        self.assertEqual(self.mode()['mode'], 'on')
        self.assertTrue(table['loaded'], 'mode is on but no anonimo table is loaded')


class SettingsActionTests(HelperTestCase):
    def test_set_settings_writes_and_enables_boot(self):
        self.settings()
        new = {'allow_lan': True, 'bridges': 'none', 'start_at_boot': True, 'close_apps': False}
        self.assertEqual(self.main('set-settings', json.dumps(new)), 0)
        self.assertEqual(json.loads(self.paths.settings.read_text()), new)
        self.assertTrue(self.called(SYSTEMCTL, 'enable', BOOT_UNIT))
        self.assertFalse(self.called(NFT))

    def test_lan_change_reloads_firewall_when_on(self):
        self.settings()
        self.helper.start()
        self.system.calls.clear()
        new = {'allow_lan': False, 'bridges': 'none', 'start_at_boot': False, 'close_apps': True}
        self.assertEqual(self.main('set-settings', json.dumps(new)), 0)
        self.assertNotIn('@lan4', self.system.inputs[NFT])
        self.assertFalse(self.called(SYSTEMCTL, 'restart'))
        self.assertFalse(self.mode()['settings']['allow_lan'])

    def test_bridge_change_restarts_tor_when_on(self):
        self.settings()
        self.helper.start()
        self.system.calls.clear()
        new = {'allow_lan': True, 'bridges': 'snowflake', 'start_at_boot': False, 'close_apps': True}
        self.assertEqual(self.main('set-settings', json.dumps(new)), 0)
        self.assertTrue(self.called(SYSTEMCTL, 'restart', TOR_UNIT))
        self.assertIn('ClientTransportPlugin snowflake', self.paths.torrc.read_text())

    def test_obfs4_needs_lines(self):
        self.settings()
        new = {'allow_lan': True, 'bridges': 'obfs4', 'start_at_boot': False, 'close_apps': True}
        self.assertEqual(self.main('set-settings', json.dumps(new)), 1)
        self.assertEqual(self.events()[-1]['message'], 'Add at least one obfs4 bridge line first')

    def test_rejects_bad_input(self):
        self.assertEqual(self.main('set-settings', '{bad'), 1)
        self.assertEqual(self.events()[-1]['message'], 'Invalid settings input')
        self.assertEqual(self.main('set-settings', json.dumps({'allow_lan': 'yes'})), 1)
        self.assertEqual(self.events()[-1]['message'], 'Invalid setting value')
        self.assertEqual(self.main('set-settings', 'x' * 70000), 1)
        self.assertEqual(self.events()[-1]['message'], 'Input too large')

    def test_rejects_deeply_nested_input(self):
        # Under the size cap, but deep enough to exhaust the JSON parser's recursion.
        self.assertEqual(self.main('set-settings', '[' * 60000), 1)
        self.assertEqual(self.events()[-1], {'event': 'error', 'message': 'Invalid settings input'})

    def test_set_bridges_private_file_and_restart_when_obfs4_on(self):
        self.paths.obfs4_bridges.write_text(LINE + '\n')
        self.settings(bridges='obfs4')
        self.helper.start()
        self.system.calls.clear()
        self.assertEqual(self.main('set-bridges', f'Bridge {LINE}\n'), 0)
        self.assertEqual(self.paths.obfs4_bridges.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.paths.obfs4_bridges.read_text(), LINE + '\n')
        self.assertTrue(self.called(SYSTEMCTL, 'restart', TOR_UNIT))
        self.assertEqual(self.events()[-1], {'count': 1, 'event': 'done', 'state': 'bridges'})

    def test_set_bridges_rejects_invalid_line(self):
        self.assertEqual(self.main('set-bridges', 'obfs4 nonsense\n'), 1)
        self.assertEqual(self.events()[-1]['message'], 'Invalid obfs4 bridge line')

    def test_get_bridges(self):
        self.paths.obfs4_bridges.write_text(LINE + '\n')
        self.assertEqual(self.main('get-bridges'), 0)
        self.assertEqual(self.events()[-1], {'event': 'bridges', 'lines': [LINE]})

    def test_busy_lock(self):
        self.settings()
        self.paths.run.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(self.main('set-settings', '{}'), 1)
            self.assertEqual(self.events()[-1]['message'], 'anonimo is busy: try again in a moment')
        finally:
            os.close(fd)


class IdentityAndMainTests(HelperTestCase):
    def test_identity_requires_running_tor(self):
        self.assertEqual(self.main('identity'), 1)
        self.assertEqual(self.events()[-1]['message'], 'Tor is not running')

    def test_identity_sends_newnym(self):
        self.system.unit = 'active'
        self.assertEqual(self.main('identity'), 0)
        self.assertEqual(self.system.newnyms, 1)
        self.assertEqual(self.events()[-1], {'event': 'done', 'state': 'identity'})

    def test_invalid_command(self):
        for argv in ([], ['format-disk'], ['start', 'extra']):
            with self.subTest(argv=argv):
                self.assertEqual(main(argv, stdout=self.out, system=self.system, paths=self.paths), 64)


if __name__ == '__main__':
    unittest.main()
