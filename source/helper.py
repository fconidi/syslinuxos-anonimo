"""Privileged helper: the only component that changes the firewall, the Tor
service and the settings. Runs as root through pkexec or systemd and writes
JSON lines on stdout. GPL-3.0-or-later."""

import fcntl
import json
import os
import pwd
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from firewall import DELETE_ARGS, build_ruleset, build_ruleset_without_tor
from paths import BOOT_UNIT, DEFAULT, NFT, RUNUSER, SYSTEMCTL, TOR, TOR_UNIT, TOR_USER
from settings import DEFAULT_SETTINGS, SettingsError, load_settings, parse_obfs4_lines, validate_settings
from state import read_json, write_json_atomic, write_text_atomic
from torctl import TorControl, TorControlError
from torrc import TRANSPORT_MISSING, TorrcError, build_torrc, read_bridge_file, transport_available

ACTIONS = ('start', 'stop', 'boot', 'reapply', 'identity', 'set-settings', 'set-bridges', 'get-bridges')
MAX_INPUT = 65536
START_TIMEOUT = {'none': 90, 'obfs4': 300, 'snowflake': 300}
ACTIVE = ('active', 'reloading')


class HelperError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class BusyError(HelperError):
    pass


def _last_line(result):
    text = result.stderr if (result.stderr or '').strip() else (result.stdout or '')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:200] if lines else f'exit status {result.returncode}'


class System:
    """Real system access; tests pass a fake with the same methods."""

    def run(self, argv, input_text=None, timeout=120):
        try:
            return subprocess.run(argv, input=input_text, capture_output=True, text=True,
                                  timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return subprocess.CompletedProcess(argv, 1, '', str(error))

    def exists(self, path):
        return os.path.exists(path)

    def tor_ids(self):
        try:
            entry = pwd.getpwnam(TOR_USER)
        except KeyError as error:
            raise HelperError(f'System user {TOR_USER} is missing') from error
        return entry.pw_uid, entry.pw_gid

    def unit_state(self, unit):
        return self.run([SYSTEMCTL, 'is-active', unit], timeout=30).stdout.strip() or 'unknown'

    def control(self, paths):
        return TorControl(paths.control_socket, paths.cookie)

    def time(self):
        return time.monotonic()

    def wall(self):
        return time.time()

    def sleep(self, seconds):
        time.sleep(seconds)

    def now_iso(self):
        return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Helper:
    def __init__(self, system=None, paths=DEFAULT, out=None):
        self.system = system or System()
        self.paths = paths
        self.out = out or sys.stdout

    def emit(self, event, **fields):
        fields['event'] = event
        self.out.write(json.dumps(fields, sort_keys=True) + '\n')
        self.out.flush()

    @contextmanager
    def lock(self, wait=30):
        """Held only while files, firewall or units change, never while
        waiting for Tor, so Off can always get through."""
        self.paths.run.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = self.system.time() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.system.time() >= deadline:
                        raise BusyError('anonimo is busy: try again in a moment') from None
                    self.system.sleep(0.2)
            yield
        finally:
            os.close(fd)

    # --- building blocks -------------------------------------------------

    def _write_mode(self, mode, settings=None, error=None):
        data = {'mode': mode, 'error': error, 'since': self.system.now_iso()}
        if settings is not None:
            data['settings'] = settings
        write_json_atomic(self.paths.mode, data)

    def _is_on(self):
        mode = read_json(self.paths.mode)
        return bool(mode) and mode.get('mode') == 'on'

    def _set_error(self, message):
        mode = read_json(self.paths.mode)
        if mode and mode.get('mode') == 'on':
            mode['error'] = message
            write_json_atomic(self.paths.mode, mode)

    def _settings_or_default(self):
        try:
            return load_settings(self.paths.settings)
        except SettingsError:
            return dict(DEFAULT_SETTINGS)

    def _obfs4_lines(self):
        try:
            with open(self.paths.obfs4_bridges, encoding='utf-8') as handle:
                return parse_obfs4_lines(handle.read())
        except (OSError, SettingsError):
            return []

    def _prepare(self):
        """Validate settings, write the torrc and let Tor check it. Changes
        nothing else, so a failure here leaves the network as it was."""
        settings = load_settings(self.paths.settings)
        kind = settings['bridges']
        obfs4 = self._obfs4_lines() if kind == 'obfs4' else []
        snowflake = read_bridge_file(self.paths.snowflake_bridges) if kind == 'snowflake' else []
        text = build_torrc(kind, obfs4, snowflake, exists=self.system.exists)
        uid, gid = self.system.tor_ids()
        write_text_atomic(self.paths.torrc, text, mode=0o640, gid=gid)
        result = self.system.run([RUNUSER, '-u', TOR_USER, '--', TOR, '--defaults-torrc', '/dev/null',
                                  '-f', str(self.paths.torrc), '--verify-config'])
        if result.returncode != 0:
            raise HelperError('Tor rejected the configuration: ' + _last_line(result))
        return settings, uid

    def _tor_uid_or_none(self):
        try:
            return self.system.tor_ids()[0]
        except HelperError:
            return None

    def _load_firewall(self, uid, allow_lan):
        """uid None: the Tor user is missing, so nothing is exempt."""
        rules = build_ruleset_without_tor(allow_lan) if uid is None else build_ruleset(uid, allow_lan)
        result = self.system.run([NFT, '-f', '-'], input_text=rules)
        if result.returncode != 0:
            raise HelperError('Cannot load the firewall rules: ' + _last_line(result))

    def _delete_firewall(self):
        result = self.system.run([NFT, *DELETE_ARGS])
        if result.returncode != 0 and 'No such file or directory' not in (result.stderr or ''):
            raise HelperError('Cannot remove the firewall rules: ' + _last_line(result))

    def _restart_tor(self):
        """Restart the Tor unit; returns the wall-clock time at which the
        restart was over."""
        self.paths.bootstrap.unlink(missing_ok=True)
        result = self.system.run([SYSTEMCTL, 'restart', TOR_UNIT], timeout=120)
        if result.returncode != 0:
            self._set_error('Cannot start Tor')
            raise HelperError('Cannot start Tor: ' + _last_line(result))
        return self.system.wall()

    def _wait_bootstrap(self, timeout, since):
        """Wait for the Tor started at `since` (wall clock). The watcher can
        still write the old Tor's progress after the unlink in _restart_tor;
        it stamps each poll before querying Tor, so only data stamped after
        the restart was over comes from the new Tor."""
        deadline = self.system.time() + timeout
        last = None
        while True:
            if not self._is_on():
                self.emit('stopped')
                return 3
            data = read_json(self.paths.bootstrap) or {}
            updated = data.get('updated')
            if isinstance(updated, bool) or not isinstance(updated, (int, float)) or not updated > since:
                data = {}
            progress = data.get('progress') if isinstance(data.get('progress'), int) else 0
            if progress != last:
                self.emit('progress', progress=progress, summary=str(data.get('summary', '')))
                last = progress
            unit = self.system.unit_state(TOR_UNIT)
            if unit in ACTIVE and progress == 100:
                self.emit('done', state='protected')
                return 0
            if unit in ('failed', 'inactive'):
                if not self._is_on():
                    # An Off stopped Tor after the mode check above.
                    self.emit('stopped')
                    return 3
                # inactive: Tor exited cleanly or was stopped by hand; it
                # will not connect, so do not wait for the timeout.
                return self._fail('Tor stopped with an error' if unit == 'failed' else 'Tor is not running')
            if self.system.time() >= deadline:
                return self._fail('Tor did not connect in time')
            self.system.sleep(1)

    def _fail(self, message):
        with self.lock():
            self._set_error(message)
        self.emit('error', message=message)
        return 2

    # --- actions ---------------------------------------------------------

    def start(self):
        with self.lock():
            settings, uid = self._prepare()
            self._load_firewall(uid, settings['allow_lan'])
            self._write_mode('on', settings=settings)
            since = self._restart_tor()
        return self._wait_bootstrap(START_TIMEOUT[settings['bridges']], since)

    def stop(self):
        with self.lock(wait=150):
            self._delete_firewall()
            # Off as soon as the table is gone: stopping Tor can take up to
            # TimeoutStopSec, and nobody may read "protected" meanwhile.
            self._write_mode('off')
            result = self.system.run([SYSTEMCTL, 'stop', TOR_UNIT], timeout=90)
            # Off leaves no generated files behind; mode.json says "off".
            self.paths.torrc.unlink(missing_ok=True)
        if result.returncode != 0:
            self.emit('warning', message='Tor did not stop cleanly')
        self.emit('done', state='off')
        return 0

    def boot(self):
        """Early boot: load the firewall before the network starts, start Tor
        without waiting. Even a broken configuration loads the firewall."""
        with self.lock():
            try:
                settings, uid = self._prepare()
            except Exception as error:
                # Fail closed on any error: the firewall must load whatever went wrong.
                message = str(error) or error.__class__.__name__
                settings = self._settings_or_default()
                # Without the Tor user, a table that blocks Tor's traffic too.
                self._load_firewall(self._tor_uid_or_none(), settings['allow_lan'])
                self._write_mode('on', settings=settings, error=message)
                raise HelperError(message) from error
            self._load_firewall(uid, settings['allow_lan'])
            self._write_mode('on', settings=settings)
            self.paths.bootstrap.unlink(missing_ok=True)
            result = self.system.run([SYSTEMCTL, 'start', '--no-block', TOR_UNIT])
            if result.returncode != 0:
                self._set_error('Cannot start Tor')
                raise HelperError('Cannot start Tor: ' + _last_line(result))
        self.emit('done', state='connecting')
        return 0

    def reapply(self):
        """Run by nftables.service (drop-in) after it loaded or flushed the
        whole ruleset, which removes anonimo's table."""
        on = self._is_on()
        if not on and not self.paths.run.exists():
            # Early boot: no helper has run yet, so there is nothing to protect.
            self.emit('done', state='off')
            return 0
        # An unlocked "off" proves nothing: a start() that holds the lock may
        # not have written mode=on yet. Only the read under the lock counts.
        touched = False
        if on:
            # Protection first: load the table at once, before waiting for the
            # lock. After a flush nothing is blocked, so this can only block more.
            self._load_current_table()
            touched = True
        try:
            with self.lock(wait=150):
                # Settle with whatever ran meanwhile: an Off wins (and removes
                # the table this reapply loaded), a settings change is picked up.
                if self._is_on():
                    self._load_current_table()
                    touched = True
                elif touched:
                    self._delete_firewall()
        except BusyError:
            # Fail closed: a table loaded above stays; otherwise look once more.
            if not touched and self._is_on():
                self._load_current_table()
                touched = True
        self.emit('done', state='reapplied' if touched else 'off')
        return 0

    def _load_current_table(self):
        self._load_firewall(self._tor_uid_or_none(), self._settings_or_default()['allow_lan'])

    def identity(self):
        if self.system.unit_state(TOR_UNIT) not in ACTIVE:
            raise HelperError('Tor is not running')
        try:
            self.system.control(self.paths).newnym()
        except (TorControlError, OSError) as error:
            raise HelperError(f'Cannot change identity: {error}') from error
        self.emit('done', state='identity')
        return 0

    def set_settings(self, text):
        try:
            new = validate_settings(json.loads(text))
        except SettingsError as error:
            raise HelperError(str(error)) from error
        except (ValueError, RecursionError) as error:
            raise HelperError('Invalid settings input') from error
        if not transport_available(new['bridges'], self.system.exists):
            raise HelperError(TRANSPORT_MISSING[new['bridges']])
        with self.lock():
            if new['bridges'] == 'obfs4' and not self._obfs4_lines():
                raise HelperError('Add at least one obfs4 bridge line first')
            try:
                old = load_settings(self.paths.settings)
            except SettingsError:
                old = None
            self.paths.etc.mkdir(mode=0o755, parents=True, exist_ok=True)
            write_json_atomic(self.paths.settings, new, mode=0o644)
            if old is None or old['start_at_boot'] != new['start_at_boot']:
                verb = 'enable' if new['start_at_boot'] else 'disable'
                result = self.system.run([SYSTEMCTL, verb, BOOT_UNIT])
                if result.returncode != 0:
                    raise HelperError('Cannot change start at boot: ' + _last_line(result))
            mode = read_json(self.paths.mode)
            if mode and mode.get('mode') == 'on':
                if old is None or old['bridges'] != new['bridges']:
                    settings, uid = self._prepare()
                    self._load_firewall(uid, settings['allow_lan'])
                    self._write_mode('on', settings=settings)
                    self._restart_tor()
                elif old['allow_lan'] != new['allow_lan']:
                    self._load_firewall(self.system.tor_ids()[0], new['allow_lan'])
                    self._write_mode('on', settings=new, error=mode.get('error'))
        self.emit('done', state='settings')
        return 0

    def set_bridges(self, text):
        try:
            lines = parse_obfs4_lines(text)
        except SettingsError as error:
            raise HelperError(str(error)) from error
        with self.lock():
            settings = self._settings_or_default()
            if not lines and settings['bridges'] == 'obfs4':
                raise HelperError('Add at least one obfs4 bridge line first')
            self.paths.etc.mkdir(mode=0o755, parents=True, exist_ok=True)
            write_text_atomic(self.paths.obfs4_bridges, ''.join(line + '\n' for line in lines), mode=0o600)
            mode = read_json(self.paths.mode)
            if mode and mode.get('mode') == 'on' and settings['bridges'] == 'obfs4':
                settings, _ = self._prepare()
                self._write_mode('on', settings=settings)
                self._restart_tor()
        self.emit('done', state='bridges', count=len(lines))
        return 0

    def get_bridges(self):
        self.emit('bridges', lines=self._obfs4_lines())
        return 0


def main(argv=None, stdin=None, stdout=None, system=None, paths=DEFAULT):
    os.umask(0o022)
    argv = sys.argv[1:] if argv is None else argv
    helper = Helper(system, paths, stdout or sys.stdout)
    if len(argv) != 1 or argv[0] not in ACTIONS:
        helper.emit('error', message='Invalid command')
        return 64
    if system is None and os.geteuid() != 0:
        helper.emit('error', message='The helper must run as root')
        return 77
    action = argv[0]
    try:
        if action in ('set-settings', 'set-bridges'):
            text = (stdin or sys.stdin).read(MAX_INPUT + 1)
            if len(text) > MAX_INPUT:
                raise HelperError('Input too large')
            return helper.set_settings(text) if action == 'set-settings' else helper.set_bridges(text)
        return getattr(helper, action.replace('-', '_'))()
    except (HelperError, SettingsError, TorrcError) as error:
        helper.emit('error', message=str(error))
        return getattr(error, 'code', 1)
    except (OSError, ValueError) as error:
        helper.emit('error', message=str(error) or error.__class__.__name__)
        return 1
