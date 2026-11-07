import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from firewall_watch import check_once
from helper import Helper
from paths import NFT, Paths
from state import read_json, write_json_atomic


class FakeSystem:
    def __init__(self):
        self.table = False
        self.rules = False
        self.loads = 0

    def run(self, argv, input_text=None, timeout=120):
        if argv[:2] == [NFT, '-j']:
            chains = [{'chain': {'name': name, 'hook': hook, 'policy': policy, 'type': kind}}
                      for name, hook, policy, kind in (
                          ('nat_out', 'output', 'accept', 'nat'),
                          ('filter_out', 'output', 'drop', 'filter'),
                          ('filter_fwd', 'forward', 'drop', 'filter'))]
            rules = [{'rule': {'chain': 'nat_out', 'expr': [{'redirect': {'port': 9040}}]}}]
            data = {'nftables': chains + (rules if self.rules else [])}
            return subprocess.CompletedProcess(argv, 0 if self.table else 1, json.dumps(data), '')
        if argv[:2] == [NFT, '-f']:
            self.table = True
            self.rules = True
            self.loads += 1
            return subprocess.CompletedProcess(argv, 0, '', '')
        raise AssertionError(argv)

    def tor_ids(self):
        return 4242, 4242

    def time(self):
        return 0

    def wall(self):
        return 1800000000

    def sleep(self, seconds):
        raise AssertionError('unexpected lock wait')


class FirewallWatchTests(unittest.TestCase):
    def test_repairs_a_flushed_table_only_when_mode_is_on(self):
        with tempfile.TemporaryDirectory() as root:
            paths = Paths.under(root)
            system = FakeSystem()
            helper = Helper(system, paths, io.StringIO())
            self.assertFalse(check_once(helper))
            self.assertEqual(system.loads, 0)
            write_json_atomic(paths.mode, {'mode': 'on'})
            self.assertTrue(check_once(helper))
            self.assertEqual(system.loads, 1)
            self.assertTrue(read_json(paths.firewall_health)['present'])
            self.assertTrue(check_once(helper))
            self.assertEqual(system.loads, 1)
            system.table = False
            self.assertTrue(check_once(helper))
            self.assertEqual(system.loads, 2)
            system.rules = False
            self.assertTrue(check_once(helper))
            self.assertEqual(system.loads, 3)
            write_json_atomic(paths.mode, {'mode': 'off'})
            self.assertFalse(check_once(helper))
            self.assertFalse(read_json(paths.firewall_health)['present'])
