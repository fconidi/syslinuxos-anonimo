import io
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from PyQt5 import sip
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtNetwork import QLocalServer
from PyQt5.QtWidgets import QApplication, QDialog, QSystemTrayIcon

import app
from app import Controller, MainWindow, Tray, acquire_instance

SETTINGS = {'allow_lan': True, 'bridges': 'none', 'start_at_boot': False, 'close_apps': False}


def status(state='off', **extra):
    data = {'state': state, 'progress': 0, 'summary': '', 'error': None, 'clock_problem': False,
            'settings': dict(SETTINGS), 'unit': 'inactive'}
    data.update(extra)
    return data


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LANG': 'C.UTF-8', 'QT_QPA_PLATFORM': 'offscreen',
                                           'HOME': self.tmp.name, 'XDG_CONFIG_HOME': self.tmp.name},
                              clear=True)
        self.env.start()
        self.current = status()
        self.controller = Controller(reader=lambda: self.current, helper_path='/nonexistent/helper')
        self.controller.timer.stop()
        self.runs = []
        self.controller.run = lambda action, input_text=None: self.runs.append((action, input_text)) or True
        self.prepared = []
        self.controller.prepare_and_run = lambda action, close: self.prepared.append((action, close))
        self.checks = []
        self.controller.check = lambda: self.checks.append(True)   # never reach the network in tests
        self.window = MainWindow(self.controller)
        # Safety net: no test can reach the real helper, pkexec, BleachBit or find real processes.
        self.helper_calls = []
        for patcher in (patch('client.helper_argv', side_effect=self.harmless_argv),
                        patch('app.appclose.find_targets', return_value=[]),
                        patch('app.appclose.close_apps'),
                        patch('app.appclose.run_bleachbit')):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self.window.tray = None
        self.window.close()
        self.env.stop()
        self.tmp.cleanup()

    def harmless_argv(self, action, gui=False):
        self.helper_calls.append(action)
        return ['/bin/sh', '-c', 'sleep 1']

    def real_controller(self):
        """A Controller with its real run() and prepare_and_run(); the helper is harmless."""
        controller = Controller(reader=lambda: self.current, helper_path=__file__)
        controller.timer.stop()
        controller.check = lambda: None                            # never reach the network
        self.addCleanup(self.wait_idle, controller)
        return controller

    def wait_until(self, condition, timeout=5):
        deadline = time.time() + timeout
        while not condition() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        return bool(condition())

    def wait_idle(self, controller):
        self.assertTrue(self.wait_until(lambda: not controller.busy()), 'controller stayed busy')

    def show(self, **values):
        self.current = status(**values)
        self.controller.refresh()
        self.app.processEvents()

    def test_states(self):
        self.show(state='off')
        self.assertEqual(self.window.toggle_button.text(), 'Switch on')
        self.assertTrue(self.window.progress.isHidden())
        self.show(state='connecting', progress=40)
        self.assertFalse(self.window.progress.isHidden())
        self.assertEqual(self.window.progress.value(), 40)
        self.assertEqual(self.window.toggle_button.text(), 'Switch off')
        self.show(state='error', error='Tor did not connect in time', clock_problem=True)
        self.assertIn('date and time', self.window.state_label.text())
        self.show(state='protected')
        self.assertTrue(self.window.identity_button.isEnabled())

    def test_toggle_without_closing_apps(self):
        self.show(state='off')
        self.window.toggle()
        self.assertEqual(self.runs, [('start', None)])
        self.show(state='protected')
        self.window.toggle()
        self.assertEqual(self.runs[-1], ('stop', None))

    def test_toggle_with_closing_apps(self):
        self.current = status(settings=dict(SETTINGS, close_apps=True))
        self.controller.refresh()
        with patch('app.appclose.find_targets', return_value=[(5, 'firefox')]):
            self.window.ask_close = lambda names: None
            self.window.toggle()
            self.assertEqual((self.runs, self.prepared), ([], []))
            self.window.ask_close = lambda names: False
            self.window.toggle()
            self.assertEqual(self.runs, [('start', None)])
            self.window.ask_close = lambda names: True
            self.window.toggle()
            self.assertEqual(self.prepared, [('start', True)])
        with patch('app.appclose.find_targets', return_value=[]):
            self.window.toggle()
            self.assertEqual(self.prepared[-1], ('start', True))

    def test_setting_change_sends_all_settings(self):
        self.show(state='off')
        self.window.lan.setChecked(False)
        action, text = self.runs[-1]
        self.assertEqual(action, 'set-settings')
        self.assertIn('"allow_lan": false', text)
        self.assertIn('"bridges": "none"', text)

    def test_login_checkbox_writes_autostart(self):
        self.window.login.setChecked(True)
        self.assertTrue((Path(self.tmp.name) / 'autostart' / 'syslinuxos-anonimo.desktop').is_file())

    def test_identity_cooldown(self):
        self.show(state='protected')
        self.window.new_identity()
        self.assertEqual(self.runs[-1], ('identity', None))
        self.assertFalse(self.window.identity_button.isEnabled())
        self.window.end_cooldown()
        self.assertTrue(self.window.identity_button.isEnabled())

    def test_real_run_without_helper_reports(self):
        controller = Controller(reader=lambda: self.current, helper_path='/nonexistent/helper')
        controller.timer.stop()
        messages = []
        controller.message.connect(messages.append)
        self.assertFalse(controller.run('start'))
        self.assertIn('Install the syslinuxos-anonimo package', messages[0])

    def test_pkexec_that_cannot_start_does_not_wedge_controller(self):
        controller = Controller(reader=lambda: self.current, helper_path=__file__)
        controller.timer.stop()
        messages = []
        controller.message.connect(messages.append)
        # A nonexistent program: the real pkexec and the helper are never started.
        with patch('client.helper_argv', return_value=['/nonexistent/pkexec', 'start']):
            controller.run('start')
        deadline = time.time() + 3
        while controller.busy() and time.time() < deadline:
            self.app.processEvents()
        self.assertFalse(controller.busy())
        self.assertEqual(messages, ['Authorization cancelled or failed.'])

    def test_tray_notifies_only_on_transitions(self):
        tray = Tray(self.window, self.controller)
        shown = []
        tray.showMessage = lambda *args: shown.append(args[1])
        self.show(state='connecting', progress=10)
        self.show(state='protected')
        self.show(state='protected')
        self.assertEqual(shown, ['Protected'])
        self.assertEqual(tray.toggle_action.text(), 'Switch off')
        self.assertIn('Protected', tray.toolTip())

    def test_not_tor_check_result_is_an_error(self):
        tray = Tray(self.window, self.controller)
        shown = []
        tray.showMessage = lambda *args: shown.append((args[1], args[2]))
        self.show(state='protected')
        self.controller.check_done.emit({'is_tor': False, 'ip': '198.51.100.7'})
        self.assertTrue(self.window.state_label.text().startswith('Error: Traffic does not go through Tor.'),
                        self.window.state_label.text())
        self.assertIn(app.STATE_COLORS['error'], self.window.state_label.styleSheet())
        self.assertIn('NOT', self.window.detail.text())
        self.assertEqual(tray.last, 'error')
        self.assertTrue(shown[-1][0].startswith('Error: Traffic does not go through Tor.'))
        self.assertEqual(shown[-1][1], QSystemTrayIcon.Warning)
        self.show(state='protected')                     # the next reading keeps the error
        self.assertEqual(self.controller.status['state'], 'error')
        self.controller.check_done.emit({'is_tor': True, 'ip': '185.220.101.1'})
        self.assertEqual(self.window.state_label.text(), 'Protected')
        self.controller.check_done.emit({'is_tor': False, 'ip': '198.51.100.7'})
        self.show(state='off')                           # Off clears it
        self.show(state='protected')
        self.assertEqual(self.window.state_label.text(), 'Protected')

    def test_failed_check_is_not_an_error_state(self):
        self.show(state='protected')
        self.controller.check_done.emit({'error': 'Cannot reach check.torproject.org'})
        self.assertEqual(self.window.state_label.text(), 'Protected')

    def test_bridges_dialog_is_deleted_and_disconnected_when_closed(self):
        receivers = self.controller.receivers(self.controller.bridges_loaded)
        dialog = app.BridgesDialog(self.controller, self.window)
        self.assertEqual(self.runs[-1], ('get-bridges', None))
        self.assertEqual(self.controller.receivers(self.controller.bridges_loaded), receivers + 1)
        self.assertTrue(dialog.testAttribute(Qt.WA_DeleteOnClose))
        dialog.done(QDialog.Rejected)
        self.assertEqual(self.controller.receivers(self.controller.bridges_loaded), receivers)
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(sip.isdeleted(dialog))

    def test_second_instance_shows_first_window(self):
        name = f'anonimo-test-{uuid.uuid4().hex}'
        server = acquire_instance(name)
        self.assertIsNotNone(server)
        connections = []
        server.newConnection.connect(lambda: connections.append(server.nextPendingConnection()))
        self.assertIsNone(acquire_instance(name))
        deadline = time.time() + 3
        while not connections and time.time() < deadline:
            self.app.processEvents()
        self.assertTrue(connections)
        server.close()

    def test_instance_name_is_in_the_runtime_directory(self):
        self.assertEqual(app.instance_name({'XDG_RUNTIME_DIR': '/run/user/1000'}),
                         '/run/user/1000/syslinuxos-anonimo.socket')
        for environ in ({}, {'XDG_RUNTIME_DIR': ''}, {'XDG_RUNTIME_DIR': 'relative'}):
            with self.subTest(environ=environ):
                self.assertEqual(app.instance_name(environ), f'syslinuxos-anonimo-{os.getuid()}')

    def test_stale_socket_is_replaced_and_only_the_user_may_connect(self):
        path = os.path.join(self.tmp.name, 'syslinuxos-anonimo.socket')
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(path)
        stale.close()                                   # a crashed instance's socket file
        server = acquire_instance(path)
        self.addCleanup(server.close)
        self.assertTrue(server.isListening())
        self.assertTrue(int(server.socketOptions()) & int(QLocalServer.UserAccessOption))
        self.assertEqual(os.stat(path).st_mode & 0o077, 0)

    def test_failed_listen_keeps_the_gui_running(self):
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            server = acquire_instance(os.path.join(self.tmp.name, 'missing', 'syslinuxos-anonimo.socket'))
        self.assertIsNotNone(server)
        self.assertFalse(server.isListening())
        self.assertIn('no single-instance check', stderr.getvalue())

    def test_run_refused_while_preparing_then_action_dispatched(self):
        release, cleaned = threading.Event(), threading.Event()

        def slow_targets():
            release.wait(5)
            return []

        controller = self.real_controller()
        with patch('app.appclose.find_targets', side_effect=slow_targets), \
                patch('app.appclose.run_bleachbit', side_effect=lambda: cleaned.set()):
            controller.prepare_and_run('stop', True)
            try:
                self.assertTrue(controller.busy())
                self.assertFalse(controller.run('start'))
                self.assertEqual(self.helper_calls, [])
            finally:
                release.set()
                cleaned.wait(5)
                self.wait_until(lambda: self.helper_calls)
        self.assertEqual(self.helper_calls, ['stop'])

    def test_worker_exception_still_dispatches_the_action(self):
        controller = self.real_controller()
        excepthook = Mock()
        with patch('app.appclose.find_targets', side_effect=RuntimeError('boom')), \
                patch('threading.excepthook', excepthook):
            controller.prepare_and_run('stop', True)
            self.assertTrue(self.wait_until(lambda: excepthook.called and self.helper_calls))
        self.assertEqual(self.helper_calls, ['stop'])
        self.assertIs(excepthook.call_args[0][0].exc_type, RuntimeError)
        self.assertFalse(controller.preparing)

    def test_toggle_and_new_identity_ignored_while_busy(self):
        controller = self.real_controller()
        window = MainWindow(controller)
        self.addCleanup(window.close)
        self.current = status(state='protected')
        controller.refresh()
        self.assertTrue(controller.run('identity'))        # a helper process: the controller is busy
        calls = []
        controller.run = lambda action, input_text=None: calls.append(action) or False
        window.toggle()
        window.new_identity()
        self.assertEqual(calls, [])

    def test_tray_actions_disabled_while_busy(self):
        controller = self.real_controller()
        window = MainWindow(controller)
        self.addCleanup(window.close)
        tray = Tray(window, controller)
        self.current = status(state='protected')
        controller.refresh()
        self.assertTrue(tray.toggle_action.isEnabled())
        self.assertTrue(tray.identity_action.isEnabled())
        self.assertTrue(controller.run('identity'))
        self.assertFalse(tray.toggle_action.isEnabled())
        self.assertFalse(tray.identity_action.isEnabled())
        self.wait_idle(controller)
        self.assertTrue(tray.toggle_action.isEnabled())
        self.assertTrue(tray.identity_action.isEnabled())
        self.current = status(state='off')
        controller.refresh()
        self.assertFalse(tray.identity_action.isEnabled())
        self.assertEqual(tray.toggle_action.text(), 'Switch on')

    def test_tray_actions_disabled_while_preparing(self):
        release, cleaned = threading.Event(), threading.Event()

        def slow_targets():
            release.wait(5)
            return []

        controller = self.real_controller()
        window = MainWindow(controller)
        self.addCleanup(window.close)
        tray = Tray(window, controller)
        with patch('app.appclose.find_targets', side_effect=slow_targets), \
                patch('app.appclose.run_bleachbit', side_effect=lambda: cleaned.set()):
            controller.prepare_and_run('stop', True)
            try:
                self.assertFalse(tray.toggle_action.isEnabled())
                self.assertFalse(tray.identity_action.isEnabled())
            finally:
                release.set()
                cleaned.wait(5)
                self.wait_until(lambda: self.helper_calls)

    def fake_helper(self, flag, authorized=None):
        """Like the real helper: start waits for Tor until an Off (the flag) and
        then reports "stopped"; it gives up after 5 s so a test cannot hang.
        Its first event ("progress") comes at once, or, with `authorized`, only
        once that file exists (until then pkexec is still asking)."""
        def argv(action, gui=False):
            self.helper_calls.append(action)
            if action == 'start':
                gate = (f'i=0; while [ ! -e "{authorized}" ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done; '
                        if authorized else '')
                script = (gate + 'echo \'{"event": "progress", "progress": 0, "summary": ""}\'; '
                          f'i=0; while [ ! -e "{flag}" ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done; '
                          'echo \'{"event": "stopped"}\'; exit 3')
            elif action == 'stop':
                script = f'touch "{flag}"; echo \'{{"event": "done", "state": "off"}}\''
            else:
                script = 'true'
            return ['/bin/sh', '-c', script]
        return argv

    def off_while_connecting(self, switch_off):
        flag = Path(self.tmp.name) / 'switched-off'
        controller = self.real_controller()
        window = MainWindow(controller)
        self.addCleanup(window.close)
        tray = Tray(window, controller)
        messages = []
        controller.message.connect(messages.append)
        with patch('client.helper_argv', side_effect=self.fake_helper(flag)), patch('app.QMessageBox') as box:
            self.assertTrue(controller.run('start'))
            self.assertTrue(self.wait_until(controller.can_stop), 'the start helper never reported')
            self.current = status('connecting', progress=10)
            controller.refresh()
            # Off stays available while the start waits for Tor; nothing else does.
            self.assertTrue(window.toggle_button.isEnabled())
            self.assertEqual(window.toggle_button.text(), 'Switch off')
            self.assertTrue(tray.toggle_action.isEnabled())
            self.assertEqual(tray.toggle_action.text(), 'Switch off')
            self.assertFalse(window.lan.isEnabled())
            self.assertFalse(tray.identity_action.isEnabled())
            self.assertFalse(controller.run('set-settings', '{}'))
            switch_off(window, tray)
            self.assertEqual(self.helper_calls, ['start', 'stop'])
            self.assertFalse(window.toggle_button.isEnabled())      # one Off is enough
            self.assertFalse(controller.run('stop'))
            self.current = status('off')
            self.wait_idle(controller)
            box.assert_not_called()
        self.assertEqual(self.helper_calls, ['start', 'stop'])
        self.assertEqual(window.state_label.text(), 'Off')
        self.assertEqual(window.toggle_button.text(), 'Switch on')
        self.assertTrue(window.toggle_button.isEnabled())
        self.assertEqual(tray.toggle_action.text(), 'Switch on')
        self.assertIn('Off: normal network restored.', messages)
        self.assertIn('anonimo was switched off.', messages)
        self.assertEqual([m for m in messages if m.startswith('Error') or 'Authorization' in m], [])

    def test_off_waits_for_the_start_helper_to_report(self):
        """Until the start helper's first event (pkexec is still asking) Off is
        not offered; a double click on "Switch on" must not send start + stop."""
        flag, authorized = Path(self.tmp.name) / 'switched-off', Path(self.tmp.name) / 'authorized'
        controller = self.real_controller()
        window = MainWindow(controller)
        self.addCleanup(window.close)
        tray = Tray(window, controller)
        with patch('client.helper_argv', side_effect=self.fake_helper(flag, authorized)):
            self.assertTrue(controller.run('start'))
            self.app.processEvents()
            self.assertFalse(controller.can_stop())
            self.assertFalse(window.toggle_button.isEnabled())
            self.assertEqual(window.toggle_button.text(), 'Switch on')       # the state is still Off
            self.assertFalse(tray.toggle_action.isEnabled())
            self.assertEqual(tray.toggle_action.text(), 'Switch on')
            window.toggle_button.click()                                      # the second click of a double click
            window.toggle()
            self.assertFalse(controller.run('stop'))
            self.assertEqual(self.helper_calls, ['start'])
            authorized.touch()                                                # pkexec said yes: first event
            self.assertTrue(self.wait_until(controller.can_stop), 'the start helper never reported')
            self.assertTrue(window.toggle_button.isEnabled())
            self.assertEqual(window.toggle_button.text(), 'Switch off')
            self.assertTrue(tray.toggle_action.isEnabled())
            self.assertEqual(tray.toggle_action.text(), 'Switch off')
            window.toggle_button.click()
            self.assertEqual(self.helper_calls, ['start', 'stop'])
            self.current = status('off')
            self.wait_idle(controller)
        self.assertEqual(window.toggle_button.text(), 'Switch on')
        self.assertTrue(window.toggle_button.isEnabled())

    def test_off_while_connecting_from_the_window(self):
        self.off_while_connecting(lambda window, tray: window.toggle_button.click())

    def test_off_while_connecting_from_the_tray(self):
        self.off_while_connecting(lambda window, tray: tray.toggle_action.trigger())

    def test_identity_cooldown_blocks_window_and_tray(self):
        self.show(state='protected')
        tray = Tray(self.window, self.controller)
        self.window.tray = tray
        self.window.new_identity()
        self.assertEqual(self.runs, [('identity', None)])
        self.assertFalse(tray.identity_action.isEnabled())
        self.window.new_identity()
        self.assertEqual(self.runs, [('identity', None)])
        self.window.end_cooldown()
        self.assertTrue(tray.identity_action.isEnabled())
        self.assertEqual(self.runs, [('identity', None)])


if __name__ == '__main__':
    unittest.main()
