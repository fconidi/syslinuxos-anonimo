from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from state import read_json
from torctl import TorControlError
from watch import run, snapshot


class FakeControl:
    def __init__(self, results):
        self.results = list(results)

    def bootstrap(self):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return dict(result)


DONE = {'severity': 'NOTICE', 'progress': 100, 'tag': 'done', 'summary': 'Done', 'warning': '', 'reason': ''}


class WatchTests(unittest.TestCase):
    def test_snapshot_success(self):
        data = snapshot(FakeControl([DONE]), now=lambda: 1234.5)
        self.assertEqual(data['progress'], 100)
        self.assertEqual(data['error'], '')
        self.assertEqual(data['updated'], 1234.5)

    def test_snapshot_time_is_taken_before_the_query(self):
        # A poll of the old Tor must carry a time earlier than the restart that stopped it.
        clock = [10.5]

        class SlowControl(FakeControl):
            def bootstrap(self):
                clock[0] = 99.5
                return super().bootstrap()

        self.assertEqual(snapshot(SlowControl([DONE]), now=lambda: clock[0])['updated'], 10.5)

    def test_snapshot_failure(self):
        for failure in (TorControlError('Tor closed the control connection'), FileNotFoundError(2, 'missing')):
            data = snapshot(FakeControl([failure]), now=lambda: 10)
            self.assertEqual(data['progress'], 0)
            self.assertTrue(data['error'])

    def test_run_writes_file_and_sleeps_between_rounds(self):
        sleeps = []
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'bootstrap.json'
            run(FakeControl([dict(DONE, progress=50), DONE]), out, iterations=2, sleep=sleeps.append, now=lambda: 1)
            self.assertEqual(read_json(out)['progress'], 100)
        self.assertEqual(sleeps, [2.0])


if __name__ == '__main__':
    unittest.main()
