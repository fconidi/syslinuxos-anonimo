import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / 'source'))

from firewall import build_ruleset

SCENARIO = TESTS / 'netns_scenario.py'


def namespace_ready():
    tools = all(Path(p).exists() for p in ('/usr/sbin/nft', '/usr/sbin/ip', '/usr/sbin/iptables-nft-restore'))
    if not tools or not shutil.which('unshare'):
        return False
    try:
        return subprocess.run(['unshare', '-rn', 'true'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(namespace_ready(), 'needs nft, ip, iptables-nft and unprivileged user namespaces')
class NamespaceTests(unittest.TestCase):
    def run_scenario(self, lan):
        with tempfile.NamedTemporaryFile('w', suffix='.nft') as handle:
            handle.write(build_ruleset(4242, lan))
            handle.flush()
            result = subprocess.run(['unshare', '-rn', sys.executable, '-I', str(SCENARIO), handle.name],
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def check_on(self, probe):
        self.assertEqual(probe['web'], 'connected')
        self.assertIn('1.1.1.1:443', probe['redirected'])
        self.assertEqual(probe['onion'], 'connected')
        self.assertIn('127.200.1.1:80', probe['redirected'])
        self.assertEqual(probe['dns_udp_lan'], 'sent')
        self.assertGreaterEqual(probe['dns_received'], 1)
        self.assertEqual(probe['dns_tcp_lan'], 'connected')
        self.assertIn('192.168.50.1:53', probe['redirected'])
        self.assertEqual(probe['ntp'], 'blocked')
        self.assertEqual(probe['dhcp'], 'sent')
        self.assertEqual(probe['ipv6_web'], 'refused')

    def check_reload_and_off(self, report):
        self.assertIn('inet anonimo', report['tables_after_reload'])
        self.assertIn('ip filter', report['tables_after_reload'])
        self.assertNotIn('inet anonimo', report['tables_after_off'])
        self.assertIn('ip filter', report['tables_after_off'])
        off = report['off']
        self.assertEqual(off['redirected'], [])
        self.assertEqual(off['dns_received'], 0)
        self.assertEqual(off['ntp'], 'sent')
        self.assertEqual(off['web'], 'timeout')

    def test_lan_allowed(self):
        report = self.run_scenario(True)
        for phase in ('on', 'after_reload'):
            with self.subTest(phase=phase):
                self.check_on(report[phase])
                self.assertEqual(report[phase]['lan_web'], 'timeout')
                self.assertNotIn('192.168.50.7:80', report[phase]['redirected'])
        self.check_reload_and_off(report)

    def test_lan_blocked(self):
        report = self.run_scenario(False)
        for phase in ('on', 'after_reload'):
            with self.subTest(phase=phase):
                self.check_on(report[phase])
                self.assertEqual(report[phase]['lan_web'], 'connected')
                self.assertIn('192.168.50.7:80', report[phase]['redirected'])
        self.check_reload_and_off(report)


if __name__ == '__main__':
    unittest.main()
