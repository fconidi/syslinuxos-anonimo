import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from appclose import CLEANERS, available_cleaners, close_apps, find_targets, run_bleachbit


def fake_process(root, pid, comm, exe=None):
    directory = Path(root) / str(pid)
    directory.mkdir()
    (directory / 'comm').write_text(comm + '\n')
    if exe:
        (directory / 'exe').symlink_to(exe)


class FindTargetsTests(unittest.TestCase):
    def test_matches_comm_and_executable(self):
        with tempfile.TemporaryDirectory() as proc:
            fake_process(proc, 100, 'firefox-esr', '/usr/lib/firefox-esr/firefox-esr')
            fake_process(proc, 101, 'Isolated Web Co', '/usr/lib/firefox-esr/firefox-esr')
            fake_process(proc, 102, 'bash', '/usr/bin/bash')
            fake_process(proc, 103, 'telegram-deskto')
            fake_process(proc, 104, 'chrome', '/opt/google/chrome/chrome')
            (Path(proc) / 'self').mkdir()
            self.assertEqual(find_targets(proc), [(100, 'firefox-esr'), (101, 'firefox-esr'),
                                                  (103, 'telegram-desktop'), (104, 'chrome')])

    def test_other_users_are_ignored(self):
        with tempfile.TemporaryDirectory() as proc:
            fake_process(proc, 100, 'firefox', '/usr/lib/firefox/firefox')
            self.assertEqual(find_targets(proc, uid=os.getuid() + 1), [])

    def test_capitalised_process_names_match(self):
        # Discord runs as 'Discord' (comm and executable), not 'discord'.
        with tempfile.TemporaryDirectory() as proc:
            fake_process(proc, 105, 'Discord', '/usr/share/discord/Discord')
            self.assertEqual(find_targets(proc), [(105, 'discord')])


class CloseTests(unittest.TestCase):
    def test_term_then_kill_survivors(self):
        sent, living = [], {5, 6}

        def kill(pid, sig):
            sent.append((pid, sig))
            if sig == signal.SIGTERM and pid == 6:
                living.discard(6)

        survivors = close_apps([5, 6], kill=kill, sleep=lambda s: None, alive=lambda p: p in living, grace=1.0)
        self.assertEqual(survivors, [5])
        self.assertEqual(sent, [(5, signal.SIGTERM), (6, signal.SIGTERM), (5, signal.SIGKILL)])

    def test_vanished_process_is_fine(self):
        def kill(pid, sig):
            raise ProcessLookupError

        self.assertEqual(close_apps([7], kill=kill, sleep=lambda s: None, alive=lambda p: False), [])


class BleachBitTests(unittest.TestCase):
    def test_only_known_cleaners_are_used(self):
        self.assertEqual(available_cleaners('firefox.cache\nfirefox.cookies\nsystem.cache\n'),
                         ['firefox.cache', 'system.cache'])

    def test_run(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            out = '\n'.join(CLEANERS[:2]) if argv[1] == '--list-cleaners' else ''
            return subprocess.CompletedProcess(argv, 0, out, '')

        self.assertEqual(run_bleachbit(run=run, exists=lambda p: True), list(CLEANERS[:2]))
        self.assertEqual(calls, [['/usr/bin/bleachbit', '--list-cleaners'],
                                 ['/usr/bin/bleachbit', '--clean', *CLEANERS[:2]]])
        self.assertIsNone(run_bleachbit(run=run, exists=lambda p: False))


if __name__ == '__main__':
    unittest.main()
