"""SysLinuxOS Anonimo: tray icon and window. Copyright 2026 Franco Conidi.
GPL-3.0-or-later."""

import argparse
import json
import os
from pathlib import Path
import sys
import threading

from PyQt5.QtCore import QObject, QProcess, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QGroupBox,
                             QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                             QProgressBar, QPushButton, QRadioButton, QSystemTrayIcon, QVBoxLayout,
                             QWidget)

import appclose
import client
from i18n import tr
from paths import HELPER
from torrc import transport_available

ICON_DIRS = (Path('/usr/share/syslinuxos-anonimo/icons'),
             Path(__file__).resolve().parents[1] / 'packaging' / 'icons')
VERSION_FILE = Path(__file__).resolve().with_name('VERSION')
STATE_COLORS = {'off': '#7a7a7a', 'connecting': '#9a7210', 'protected': '#2e8b3e', 'error': '#c0392b'}
IDENTITY_COOLDOWN_MS = 10000


def state_icon(state):
    for directory in ICON_DIRS:
        path = directory / f'anonimo-{state}.svg'
        if path.is_file():
            return QIcon(str(path))
    return QIcon.fromTheme('network-vpn')


def toggle_text(controller):
    starting = controller.starting()
    return tr('Switch on') if controller.status['state'] == 'off' and not starting else tr('Switch off')


class Controller(QObject):
    status_changed = pyqtSignal(dict)
    busy_changed = pyqtSignal(bool)
    message = pyqtSignal(str)
    bridges_loaded = pyqtSignal(list)
    check_done = pyqtSignal(dict)
    prepared = pyqtSignal(str)

    def __init__(self, reader=client.read_status, helper_path=HELPER, parent=None):
        super().__init__(parent)
        self.reader = reader
        self.helper_path = helper_path
        self.status = reader()
        self.process = None
        self.action = None
        # Off while a start waits for Tor: the helper's lock lets it through.
        self.stop_process = None
        # The current process has sent an event: for a start, pkexec said yes.
        self.heard = False
        self.preparing = False
        # The last Tor check answered IsTor: false; cleared by Off or a good check.
        self.not_tor = False
        self.prepared.connect(self._dispatch_prepared)
        self.check_done.connect(self._checked)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)

    def refresh(self):
        status = self.reader()
        if status['state'] == 'off':
            self.not_tor = False
        elif self.not_tor:
            status = client.not_tor_status(status)
        self.status = status
        self.status_changed.emit(status)

    def _checked(self, result):
        if 'is_tor' in result:
            self.not_tor = not result['is_tor']
            self.refresh()

    def busy(self):
        return self.process is not None or self.stop_process is not None or self.preparing

    def starting(self):
        """A start is running and its helper has reported, so the pkexec
        authorization is over. Before that a click would only queue a second
        prompt, and a double click on "Switch on" would send start + stop."""
        return self.process is not None and self.action == 'start' and self.heard

    def can_stop(self):
        """Off works while a start waits for Tor, from its first event on."""
        return self.starting() and self.stop_process is None

    def run(self, action, input_text=None):
        stop_now = action == 'stop' and self.can_stop()
        if self.busy() and not stop_now:
            return False
        if not Path(self.helper_path).is_file():
            self.message.emit(tr('Install the syslinuxos-anonimo package to use this command.'))
            self.busy_changed.emit(self.busy())
            return False
        argv = client.helper_argv(action, gui=True)
        process = QProcess(self)
        if stop_now:
            self.stop_process = process
        else:
            self.process, self.action, self.heard = process, action, False
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.finished.connect(lambda code, _status: self._finished(process, code))
        process.errorOccurred.connect(lambda error: self._failed_to_start(process, error))
        process.start(argv[0], argv[1:])
        if input_text is not None:
            process.write(input_text.encode('utf-8'))
        process.closeWriteChannel()
        self.busy_changed.emit(self.busy())
        return True

    def prepare_and_run(self, action, close_apps):
        """Close apps and clean caches off the GUI thread, then run the helper."""
        if self.busy():
            return
        if not close_apps:
            self.run(action)
            return
        self.preparing = True
        self.busy_changed.emit(True)

        def work():
            try:
                appclose.close_apps([pid for pid, _ in appclose.find_targets()])
                appclose.run_bleachbit()
            finally:
                # Dispatch even if the cleanup fails, so the requested action still happens.
                self.prepared.emit(action)

        threading.Thread(target=work, daemon=True).start()

    def _dispatch_prepared(self, action):
        self.preparing = False
        self.run(action)

    def _read(self, process):
        while process.canReadLine():
            event = client.parse_event(bytes(process.readLine()).decode('utf-8', 'replace'))
            if event is None:
                continue
            if process is self.process and not self.heard:
                self.heard = True
                self.busy_changed.emit(self.busy())      # Off may be offered now
            if event['event'] == 'bridges':
                self.bridges_loaded.emit([str(line) for line in event.get('lines', [])])
                continue
            text = client.event_text(event)
            if text:
                self.message.emit(text)
            if event['event'] == 'progress':
                self.refresh()

    def _release(self, process):
        if process is self.process:
            self.process, self.action, self.heard = None, None, False
        elif process is self.stop_process:
            self.stop_process = None
        else:
            return False
        process.deleteLater()
        return True

    def _finished(self, process, code):
        self._read(process)
        if not self._release(process):
            return
        if code in client.AUTH_FAILED:
            self.message.emit(tr('Authorization cancelled or failed.'))
        self.busy_changed.emit(self.busy())
        self.refresh()

    def _failed_to_start(self, process, error):
        # pkexec could not be started: finished() is never emitted for that.
        if error != QProcess.FailedToStart or not self._release(process):
            return
        self.message.emit(tr('Authorization cancelled or failed.'))
        self.busy_changed.emit(self.busy())

    def check(self):
        def work():
            try:
                result = client.tor_check()
            except client.CheckError as error:
                result = {'error': str(error)}
            self.check_done.emit(result)

        threading.Thread(target=work, daemon=True).start()


class BridgesDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        # One dialog per opening: do not pile up under the window.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(tr('obfs4 bridges'))
        layout = QVBoxLayout(self)
        info = QLabel(tr('Paste the bridge lines from https://bridges.torproject.org, one per line. '
                         'Saving replaces the current list.'))
        info.setWordWrap(True)
        layout.addWidget(info)
        self.text = QPlainTextEdit()
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        controller.bridges_loaded.connect(self.fill)
        controller.run('get-bridges')

    def fill(self, lines):
        self.text.setPlainText('\n'.join(lines))

    def done(self, result):
        try:
            self.controller.bridges_loaded.disconnect(self.fill)
        except TypeError:
            pass                                    # already disconnected
        super().done(result)

    def save(self):
        if self.controller.run('set-bridges', self.text.toPlainText() + '\n'):
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.tray = None
        self.identity_cooldown = False
        self.last_state = None
        self.bridge_available = {kind: transport_available(kind) for kind in ('none', 'obfs4', 'snowflake')}
        self.setWindowTitle('SysLinuxOS Anonimo')
        self.setWindowIcon(QIcon.fromTheme('syslinuxos-anonimo', state_icon('protected')))
        central = QWidget()
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(64, 64)
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(15)
        font.setBold(True)
        self.state_label.setFont(font)
        top.addWidget(self.icon)
        top.addWidget(self.state_label, 1)
        layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)

        buttons = QHBoxLayout()
        self.toggle_button = QPushButton()
        self.toggle_button.clicked.connect(self.toggle)
        self.identity_button = QPushButton(tr('New identity'))
        self.identity_button.clicked.connect(self.new_identity)
        self.check_button = QPushButton(tr('Check Tor'))
        self.check_button.clicked.connect(self.check)
        for button in (self.toggle_button, self.identity_button, self.check_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        group = QGroupBox(tr('Settings'))
        settings = QVBoxLayout(group)
        self.lan = QCheckBox(tr('Reach the local network directly (printers, NAS)'))
        self.boot = QCheckBox(tr('Switch on automatically at boot'))
        self.close_apps = QCheckBox(tr('Close network applications and clean caches on start and stop'))
        self.login = QCheckBox(tr('Show the icon at login'))
        for box in (self.lan, self.boot, self.close_apps, self.login):
            settings.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Bridges:')))
        self.bridge_buttons = {'none': QRadioButton(tr('None')), 'obfs4': QRadioButton('obfs4'),
                               'snowflake': QRadioButton('snowflake')}
        for kind, button in self.bridge_buttons.items():
            row.addWidget(button)
            button.toggled.connect(lambda checked, kind=kind: checked and self.change_setting('bridges', kind))
            if not self.bridge_available[kind]:
                button.setToolTip(tr('The bridge program is not installed'))
        self.edit_bridges = QPushButton(tr('Edit obfs4 bridges…'))
        self.edit_bridges.clicked.connect(self.open_bridges)
        row.addWidget(self.edit_bridges)
        row.addStretch(1)
        settings.addLayout(row)
        layout.addWidget(group)
        self.lan.toggled.connect(lambda value: self.change_setting('allow_lan', value))
        self.boot.toggled.connect(self.boot_toggled)
        self.close_apps.toggled.connect(lambda value: self.change_setting('close_apps', value))
        self.login.toggled.connect(lambda value: client.set_autostart(value))

        footer = QHBoxLayout()
        self.message = QLabel()
        self.message.setWordWrap(True)
        footer.addWidget(self.message, 1)
        about = QPushButton(tr('About'))
        about.clicked.connect(self.about)
        footer.addWidget(about)
        layout.addLayout(footer)
        self.setCentralWidget(central)

        controller.status_changed.connect(self.show_status)
        controller.busy_changed.connect(self.set_busy)
        controller.message.connect(self.message.setText)
        controller.check_done.connect(lambda result: self.detail.setText(client.check_text(result)))
        self.show_status(controller.status)
        self.set_busy(controller.busy())

    def show_status(self, status):
        state = status['state']
        self.icon.setPixmap(state_icon(state).pixmap(64, 64))
        self.state_label.setText(client.describe(status))
        self.state_label.setStyleSheet(f'color: {STATE_COLORS[state]}')
        self.progress.setVisible(state == 'connecting')
        self.progress.setValue(status['progress'])
        settings = status['settings']
        for box, value in ((self.lan, settings['allow_lan']), (self.boot, settings['start_at_boot']),
                           (self.close_apps, settings['close_apps']), (self.login, client.autostart_enabled())):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        for kind, button in self.bridge_buttons.items():
            button.blockSignals(True)
            button.setChecked(settings['bridges'] == kind)
            button.blockSignals(False)
        if state == 'protected' and self.last_state not in (None, 'protected'):
            self.detail.setText(tr('Checking…'))
            self.controller.check()
        if state == 'off':
            self.detail.clear()
        self.last_state = state
        self.set_busy(self.controller.busy())

    def set_busy(self, busy):
        state = self.controller.status['state']
        self.toggle_button.setText(toggle_text(self.controller))
        self.toggle_button.setEnabled(not busy or self.controller.can_stop())
        for box in (self.lan, self.boot, self.close_apps):
            box.setEnabled(not busy)
        for kind, button in self.bridge_buttons.items():
            button.setEnabled(not busy and self.bridge_available[kind])
        self.edit_bridges.setEnabled(not busy and self.bridge_available['obfs4'])
        self.identity_button.setEnabled(not busy and state == 'protected' and not self.identity_cooldown)
        self.check_button.setEnabled(not busy and state != 'off')

    def toggle(self):
        if self.controller.can_stop():
            # A start is waiting for Tor: switch off at once. No app closing:
            # nothing reached the Internet through Tor yet.
            self.controller.run('stop')
            return
        if self.controller.busy():
            return
        action = 'start' if self.controller.status['state'] == 'off' else 'stop'
        if not self.controller.status['settings']['close_apps']:
            self.controller.run(action)
            return
        targets = appclose.find_targets()
        close = True
        if targets:
            close = self.ask_close(sorted({name for _, name in targets}))
            if close is None:
                return
        if close:
            self.controller.prepare_and_run(action, True)
        else:
            self.controller.run(action)

    def ask_close(self, names):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle('SysLinuxOS Anonimo')
        box.setText(tr('These applications will be closed: {names}', names=', '.join(names)))
        close = box.addButton(tr('Close and continue'), QMessageBox.AcceptRole)
        keep = box.addButton(tr('Continue without closing'), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        return True if clicked is close else False if clicked is keep else None

    def change_setting(self, key, value):
        settings = dict(self.controller.status['settings'])
        settings[key] = value
        self.controller.run('set-settings', json.dumps(settings, sort_keys=True))

    def boot_toggled(self, value):
        self.change_setting('start_at_boot', value)
        if value and QSystemTrayIcon.isSystemTrayAvailable():
            client.set_autostart(True)

    def new_identity(self):
        if self.identity_cooldown or self.controller.busy():
            return
        if self.controller.run('identity'):
            self.identity_cooldown = True
            self.identity_button.setEnabled(False)
            self.refresh_tray()
            QTimer.singleShot(IDENTITY_COOLDOWN_MS, self.end_cooldown)

    def end_cooldown(self):
        self.identity_cooldown = False
        self.set_busy(self.controller.busy())
        self.refresh_tray()

    def refresh_tray(self):
        if self.tray is not None:
            self.tray.refresh_actions()

    def check(self):
        self.detail.setText(tr('Checking…'))
        self.controller.check()

    def open_bridges(self):
        BridgesDialog(self.controller, self).exec_()

    def about(self):
        version = VERSION_FILE.read_text().strip() if VERSION_FILE.is_file() else ''
        QMessageBox.about(self, tr('About'), '<br>'.join([
            f'<b>SysLinuxOS Anonimo</b> {version}',
            tr('Route all traffic of this computer through Tor.'),
            'Copyright 2026 Franco Conidi · GPL-3.0-or-later',
            tr('Inspired by AnonSurf by the Parrot Security team. No AnonSurf code is used.'),
            tr('Tor is a trademark of The Tor Project, Inc.'),
        ]))

    def show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray is not None and self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()


class Tray(QSystemTrayIcon):
    def __init__(self, window, controller):
        super().__init__(state_icon('off'))
        self.window = window
        self.controller = controller
        self.last = None
        self.menu = QMenu()
        self.state_action = self.menu.addAction('')
        self.state_action.setEnabled(False)
        self.menu.addSeparator()
        self.toggle_action = self.menu.addAction('')
        self.toggle_action.triggered.connect(window.toggle)
        self.identity_action = self.menu.addAction(tr('New identity'))
        self.identity_action.triggered.connect(window.new_identity)
        self.menu.addAction(tr('Open window')).triggered.connect(window.show_window)
        self.menu.addSeparator()
        self.menu.addAction(tr('Quit')).triggered.connect(QApplication.quit)
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)
        controller.status_changed.connect(self.show_status)
        controller.busy_changed.connect(self.refresh_actions)
        self.show_status(controller.status)

    def on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.window.show_window()

    def show_status(self, status):
        state = status['state']
        text = client.describe(status)
        self.setIcon(state_icon(state))
        self.setToolTip(f'SysLinuxOS Anonimo · {text}')
        self.state_action.setText(text)
        self.refresh_actions()
        if self.last is not None and state != self.last and state in ('protected', 'error'):
            icon = QSystemTrayIcon.Information if state == 'protected' else QSystemTrayIcon.Warning
            self.showMessage('SysLinuxOS Anonimo', text, icon, 5000)
        self.last = state

    def refresh_actions(self, *_):
        busy = self.controller.busy()
        protected = self.controller.status['state'] == 'protected'
        self.toggle_action.setText(toggle_text(self.controller))
        self.toggle_action.setEnabled(not busy or self.controller.can_stop())
        self.identity_action.setEnabled(not busy and protected and not self.window.identity_cooldown)


def instance_name(environ=None):
    """The single-instance socket: an absolute path in the user's own runtime
    directory, where no other user can create it first. Without
    XDG_RUNTIME_DIR, Qt's name in the temporary directory as before."""
    env = os.environ if environ is None else environ
    runtime = env.get('XDG_RUNTIME_DIR', '')
    if os.path.isabs(runtime):
        return os.path.join(runtime, 'syslinuxos-anonimo.socket')
    return f'syslinuxos-anonimo-{os.getuid()}'


def acquire_instance(name):
    """The server of the first instance, or None after asking it to show its
    window. When the name cannot be taken the GUI still runs, without the
    single-instance check."""
    probe = QLocalSocket()
    probe.connectToServer(name)
    if probe.waitForConnected(300):
        probe.write(b'show')
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(name):
        # Most likely a socket left by an instance that crashed: remove it once.
        QLocalServer.removeServer(name)
        if not server.listen(name):
            print(f'syslinuxos-anonimo: no single-instance check: {server.errorString()}', file=sys.stderr)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog='syslinuxos-anonimo')
    parser.add_argument('--tray', action='store_true', help='start in the notification area')
    args = parser.parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName('syslinuxos-anonimo')
    application.setDesktopFileName('syslinuxos-anonimo')
    server = acquire_instance(instance_name())
    if server is None:
        return 0
    controller = Controller()
    window = MainWindow(controller)

    def show_from_other_instance():
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
        window.show_window()

    server.newConnection.connect(show_from_other_instance)
    if QSystemTrayIcon.isSystemTrayAvailable():
        window.tray = Tray(window, controller)
        window.tray.show()
        application.setQuitOnLastWindowClosed(False)
    if not (args.tray and window.tray is not None):
        window.show_window()
    return application.exec_()


if __name__ == '__main__':
    sys.exit(main())
