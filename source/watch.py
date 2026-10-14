"""Publish Tor's bootstrap progress for unprivileged readers. Runs as the
_anonimo user. GPL-3.0-or-later."""

import time

from paths import DEFAULT
from state import write_json_atomic
from torctl import TorControl, TorControlError

EMPTY = {'severity': '', 'progress': 0, 'tag': '', 'summary': '', 'warning': '', 'reason': ''}


def snapshot(control, now=time.time):
    # Taken before the query: a poll of a Tor that is being restarted then
    # always carries a time earlier than the end of the restart (see the
    # helper's _wait_bootstrap).
    started = float(now())
    try:
        data = control.bootstrap()
        data['error'] = ''
    except (TorControlError, OSError) as error:
        data = dict(EMPTY, error=str(error) or error.__class__.__name__)
    data['updated'] = started
    return data


def run(control, out_path, interval=2.0, iterations=None, sleep=time.sleep, now=time.time):
    count = 0
    while iterations is None or count < iterations:
        write_json_atomic(out_path, snapshot(control, now))
        count += 1
        if iterations is None or count < iterations:
            sleep(interval)


def main():
    run(TorControl(DEFAULT.control_socket, DEFAULT.cookie), DEFAULT.bootstrap)
    return 0
