import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from state import (clock_problem, compute_state, parse_bootstrap_phase, read_json,
                   write_json_atomic, write_text_atomic)

ON = {'mode': 'on', 'error': None}


class FileTests(unittest.TestCase):
    def test_json_round_trip_mode_and_no_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mode.json'
            write_json_atomic(path, {'mode': 'on'}, mode=0o640, gid=os.getgid())
            self.assertEqual(read_json(path), {'mode': 'on'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            write_text_atomic(path, '{"mode": "off"}\n')
            self.assertEqual(read_json(path), {'mode': 'off'})
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['mode.json'])

    def test_read_json_tolerates_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.json'
            self.assertIsNone(read_json(path))
            path.write_text('{broken')
            self.assertIsNone(read_json(path))
            path.write_text('[1, 2]')
            self.assertIsNone(read_json(path))
            path.write_text('[' * 100000)
            self.assertIsNone(read_json(path))


class BootstrapTests(unittest.TestCase):
    def test_done(self):
        data = parse_bootstrap_phase('NOTICE BOOTSTRAP PROGRESS=100 TAG=done SUMMARY="Done"')
        self.assertEqual(data, {'severity': 'NOTICE', 'progress': 100, 'tag': 'done',
                                'summary': 'Done', 'warning': '', 'reason': ''})

    def test_warning_with_quotes(self):
        value = (r'WARN BOOTSTRAP PROGRESS=10 TAG=conn_done SUMMARY="Connected to a relay" '
                 r'WARNING="Clock skew \"-3600\" seconds" REASON=CLOCK_SKEW COUNT=1 RECOMMENDATION=warn')
        data = parse_bootstrap_phase(value)
        self.assertEqual(data['progress'], 10)
        self.assertEqual(data['summary'], 'Connected to a relay')
        self.assertEqual(data['warning'], 'Clock skew "-3600" seconds')
        self.assertEqual(data['reason'], 'CLOCK_SKEW')
        self.assertTrue(clock_problem(data))

    def test_bad_values(self):
        with self.assertRaises(ValueError):
            parse_bootstrap_phase('garbage')
        self.assertEqual(parse_bootstrap_phase('NOTICE BOOTSTRAP PROGRESS=abc')['progress'], 0)
        self.assertEqual(parse_bootstrap_phase('NOTICE BOOTSTRAP PROGRESS=150')['progress'], 100)
        self.assertFalse(clock_problem({'warning': 'Connection refused', 'reason': 'CONNECTREFUSED'}))
        self.assertFalse(clock_problem(None))


class StateTests(unittest.TestCase):
    def test_off(self):
        self.assertEqual(compute_state(None, {'progress': 100}, 'active'), 'off')
        self.assertEqual(compute_state({'mode': 'off'}, {'progress': 100}, 'active'), 'off')

    def test_protected(self):
        self.assertEqual(compute_state(ON, {'progress': 100}, 'active'), 'protected')

    def test_late_bootstrap_clears_error(self):
        mode = {'mode': 'on', 'error': 'Tor did not connect in time'}
        self.assertEqual(compute_state(mode, {'progress': 100}, 'active'), 'protected')

    def test_unit_failed_is_error(self):
        self.assertEqual(compute_state(ON, {'progress': 40}, 'failed'), 'error')
        self.assertEqual(compute_state(ON, None, 'inactive'), 'error')

    def test_helper_error_is_error(self):
        mode = {'mode': 'on', 'error': 'Tor did not connect in time'}
        self.assertEqual(compute_state(mode, {'progress': 40}, 'active'), 'error')

    def test_connecting(self):
        self.assertEqual(compute_state(ON, {'progress': 40}, 'active'), 'connecting')
        self.assertEqual(compute_state(ON, None, 'activating'), 'connecting')


if __name__ == '__main__':
    unittest.main()
