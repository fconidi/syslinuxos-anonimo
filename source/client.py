"""Shared by the CLI and the GUI: state, helper calls, texts, Tor check and
login autostart. Runs as the desktop user. GPL-3.0-or-later."""

import http.client
import json
import os
from pathlib import Path
import subprocess
import urllib.request

from i18n import helper_message, tr
from paths import CHECK_URL, DEFAULT, HELPER, PKEXEC, SYSTEMCTL, TOR_UNIT
from settings import DEFAULT_SETTINGS, SettingsError, load_settings
from state import clock_problem, compute_state, read_json

EXIT_CODES = {'protected': 0, 'error': 1, 'connecting': 2, 'off': 3}
STATE_LABELS = {'off': 'Off', 'connecting': 'Connecting', 'protected': 'Protected', 'error': 'Error'}
AUTH_FAILED = (126, 127)
NOT_TOR = 'Traffic does not go through Tor'
AUTOSTART_NAME = 'syslinuxos-anonimo.desktop'
AUTOSTART_TEXT = ('[Desktop Entry]\nType=Application\nName=SysLinuxOS Anonimo\n'
                  'Exec=syslinuxos-anonimo --tray\nIcon=syslinuxos-anonimo\n'
                  'X-GNOME-Autostart-enabled=true\nNoDisplay=true\n')


class CheckError(Exception):
    pass


def unit_state(unit=TOR_UNIT, run=subprocess.run):
    try:
        result = run([SYSTEMCTL, 'is-active', unit], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    return result.stdout.strip() or 'unknown'


def read_status(paths=DEFAULT, unit=None):
    mode = read_json(paths.mode)
    bootstrap = read_json(paths.bootstrap)
    unit = unit_state() if unit is None else unit
    state = compute_state(mode, bootstrap, unit)
    try:
        settings = load_settings(paths.settings)
    except SettingsError:
        settings = dict(DEFAULT_SETTINGS)
    progress = (bootstrap or {}).get('progress', 0)
    error = ((mode or {}).get('error') or 'Tor is not running') if state == 'error' else None
    return {'state': state, 'progress': progress if isinstance(progress, int) else 0,
            'summary': str((bootstrap or {}).get('summary', '')), 'error': error,
            'clock_problem': clock_problem(bootstrap), 'settings': settings, 'unit': unit}


def not_tor_status(status):
    """check.torproject.org answered IsTor: false: an error, whatever the
    state files say."""
    return dict(status, state='error', error=NOT_TOR)


def describe(status, cli=False):
    """The state line; in the error state with the way back to the normal
    network, worded for the command line when cli is true."""
    label = tr(STATE_LABELS[status['state']])
    if status['state'] == 'connecting':
        return tr('{state} · {progress}%', state=label, progress=status['progress'])
    if status['state'] == 'error':
        detail = helper_message(status['error'] or 'Tor is not running')
        hints = []
        if status.get('clock_problem'):
            hints.append(tr('Check that the date and time of this computer are correct.'))
        hints.append(tr('Run "anonimo stop" to restore the normal network.') if cli
                     else tr('Switch anonimo off to restore the normal network.'))
        if not detail.endswith(('.', '!', '?')):
            detail += '.'
        return tr('{state}: {detail}', state=label, detail=' '.join([detail, *hints]))
    return label


def helper_argv(action, gui):
    argv = [PKEXEC]
    if gui:
        argv.append('--disable-internal-agent')
    return argv + [HELPER, action]


def parse_event(line):
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) and isinstance(event.get('event'), str) else None


def _number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def event_text(event):
    kind, state = event.get('event'), event.get('state')
    if kind == 'progress':
        return tr('Connecting to Tor… {progress}%', progress=_number(event.get('progress')))
    if kind == 'error':
        return tr('Error: {message}', message=helper_message(str(event.get('message', ''))))
    if kind == 'warning':
        return helper_message(str(event.get('message', '')))
    if kind == 'stopped':
        return tr('anonimo was switched off.')
    if kind != 'done':
        return ''
    if state == 'protected':
        return tr('Protected: traffic goes through Tor.')
    if state == 'off':
        return tr('Off: normal network restored.')
    if state == 'connecting':
        return tr('Connecting to Tor…')
    if state == 'identity':
        return tr('New identity requested.')
    if state == 'settings':
        return tr('Settings saved.')
    if state == 'bridges':
        return tr('Bridges saved: {count}', count=_number(event.get('count')))
    return ''


def run_helper(action, input_text=None, on_event=None, popen=subprocess.Popen):
    """CLI path: pkexec may use its text agent. Streams events, returns the exit code."""
    process = popen(helper_argv(action, gui=False),
                    stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, text=True)
    if input_text is not None:
        process.stdin.write(input_text)
        process.stdin.close()
    for line in process.stdout:
        event = parse_event(line)
        if event is not None and on_event is not None:
            on_event(event)
    return process.wait()


def tor_check(urlopen=urllib.request.urlopen, timeout=15):
    try:
        with urlopen(CHECK_URL, timeout=timeout) as response:
            data = json.loads(response.read(4096).decode('utf-8'))
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise CheckError('Cannot reach check.torproject.org') from error
    if not isinstance(data, dict) or not isinstance(data.get('IsTor'), bool):
        raise CheckError('Unexpected answer from check.torproject.org')
    return {'is_tor': data['IsTor'], 'ip': str(data.get('IP', ''))}


def check_text(result):
    if 'error' in result:
        return tr('Tor check failed: {message}', message=helper_message(str(result['error'])))
    if result['is_tor']:
        return tr('Traffic goes through Tor. Exit address: {ip}', ip=result['ip'])
    return tr('Warning: traffic does NOT go through Tor. Address: {ip}', ip=result['ip'])


def autostart_path(environ=None, home=None):
    env = os.environ if environ is None else environ
    base = env.get('XDG_CONFIG_HOME') or os.path.join(home or str(Path.home()), '.config')
    return Path(base) / 'autostart' / AUTOSTART_NAME


def autostart_enabled(environ=None, home=None):
    return autostart_path(environ, home).is_file()


def set_autostart(enabled, environ=None, home=None):
    path = autostart_path(environ, home)
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(AUTOSTART_TEXT, encoding='utf-8')
    else:
        path.unlink(missing_ok=True)
