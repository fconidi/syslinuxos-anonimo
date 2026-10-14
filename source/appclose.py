"""Close the user's network applications and clean their caches with
BleachBit. Runs as the desktop user, on the user's own processes only.
GPL-3.0-or-later."""

import os
import signal
import subprocess
import time

from paths import BLEACHBIT

TARGETS = ('firefox', 'firefox-esr', 'chromium', 'chrome', 'brave', 'thunderbird',
           'telegram-desktop', 'discord', 'hexchat', 'pidgin', 'transmission-gtk',
           'qbittorrent', 'steam')
CLEANERS = ('firefox.cache', 'firefox.url_history', 'firefox.forms', 'firefox.session_restore',
            'firefox.crash_reports', 'chromium.cache', 'chromium.history', 'chromium.session',
            'chromium.form_history', 'google_chrome.cache', 'google_chrome.history',
            'google_chrome.session', 'google_chrome.form_history', 'system.cache')


def _match(comm, exe_name):
    # /proc/<pid>/comm is cut to 15 characters; the executable name is not.
    # Case-insensitive: some apps run as e.g. 'Discord'.
    comm, exe_name = comm.lower(), exe_name.lower()
    for target in TARGETS:
        if exe_name == target or comm == target[:15]:
            return target
    return None


def find_targets(proc_root='/proc', uid=None):
    uid = os.getuid() if uid is None else uid
    found = []
    for entry in os.scandir(proc_root):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat(follow_symlinks=False).st_uid != uid:
                continue
            with open(os.path.join(entry.path, 'comm'), encoding='utf-8', errors='replace') as handle:
                comm = handle.read().strip()
        except OSError:
            continue
        try:
            exe_name = os.path.basename(os.readlink(os.path.join(entry.path, 'exe')))
        except OSError:
            exe_name = ''
        target = _match(comm, exe_name)
        if target:
            found.append((int(entry.name), target))
    return sorted(found)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def close_apps(pids, kill=os.kill, sleep=time.sleep, alive=None, grace=5.0):
    alive = alive or _alive
    for pid in pids:
        try:
            kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    remaining = [pid for pid in pids if alive(pid)]
    waited = 0.0
    while remaining and waited < grace:
        sleep(0.25)
        waited += 0.25
        remaining = [pid for pid in remaining if alive(pid)]
    for pid in remaining:
        try:
            kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return remaining


def available_cleaners(list_output):
    available = set(list_output.split())
    return [cleaner for cleaner in CLEANERS if cleaner in available]


def run_bleachbit(run=subprocess.run, exists=os.path.exists):
    if not exists(BLEACHBIT):
        return None
    try:
        listed = run([BLEACHBIT, '--list-cleaners'], capture_output=True, text=True, timeout=60, check=False)
        cleaners = available_cleaners(listed.stdout)
        if cleaners:
            run([BLEACHBIT, '--clean', *cleaners], capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return cleaners
