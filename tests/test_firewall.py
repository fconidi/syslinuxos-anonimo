from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from firewall import DELETE_ARGS, build_ruleset, build_ruleset_without_tor


def chain(rules, name):
    lines = rules.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f'chain {name} {{')
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == '}')
    return [line.strip() for line in lines[start + 1:end]]


def userns_available():
    try:
        return subprocess.run(['unshare', '-rn', 'true'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


FILTER_HEAD = ['oifname "lo" accept', 'ip daddr 127.0.0.0/8 accept', 'meta skuid 1000 accept',
               'meta nfproto ipv4 udp sport 68 udp dport 67 accept',
               'meta l4proto { tcp, udp } th dport 53 reject']
FILTER_TAIL = ['meta l4proto tcp reject with tcp reset', 'reject with icmpx admin-prohibited']


class RulesetTests(unittest.TestCase):
    def test_atomic_replace_header(self):
        lines = build_ruleset(1000, True).splitlines()
        self.assertEqual(lines[:3], ['table inet anonimo {}', 'delete table inet anonimo',
                                     'table inet anonimo {'])
        self.assertEqual(DELETE_ARGS, ['delete', 'table', 'inet', 'anonimo'])

    def test_nat_order_with_lan(self):
        self.assertEqual(chain(build_ruleset(1000, True), 'nat_out'), [
            'type nat hook output priority -105; policy accept;',
            'meta skuid 1000 return',
            'meta nfproto ipv4 ip daddr 127.192.0.0/10 meta l4proto tcp redirect to :9040',
            'oifname "lo" return',
            'meta nfproto ipv4 udp dport 53 redirect to :9053',
            'meta nfproto ipv4 tcp dport 53 redirect to :9040',
            'ip daddr @lan4 return',
            'meta nfproto ipv4 meta l4proto tcp redirect to :9040',
        ])

    def test_no_lan_rules_without_lan(self):
        rules = build_ruleset(1000, False)
        for text in ('@lan4', '@lan6', 'set lan4', 'set lan6'):
            self.assertNotIn(text, rules)

    def test_filter_order_with_lan(self):
        out = chain(build_ruleset(1000, True), 'filter_out')
        self.assertEqual(out[0], 'type filter hook output priority -5; policy drop;')
        self.assertEqual(out[1:], FILTER_HEAD + [
            'ip daddr @lan4 accept', 'ip6 daddr @lan6 accept',
            'icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit } accept',
        ] + FILTER_TAIL)

    def test_filter_without_lan(self):
        self.assertEqual(chain(build_ruleset(1000, False), 'filter_out')[1:], FILTER_HEAD + FILTER_TAIL)

    def test_lan_sets(self):
        rules = build_ruleset(1000, True)
        self.assertIn('elements = { 10.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16 }', rules)
        self.assertIn('elements = { fe80::/10, fc00::/7 }', rules)

    def test_forward_dropped(self):
        self.assertEqual(chain(build_ruleset(1000, False), 'filter_fwd'),
                         ['type filter hook forward priority -5; policy drop;'])

    def test_rejects_invalid_uid(self):
        for uid in (0, -1, True, '1000', None, 1.5):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                build_ruleset(uid, True)

    def test_without_tor_user_nothing_is_exempt(self):
        for lan in (True, False):
            with self.subTest(lan=lan):
                rules = build_ruleset_without_tor(lan)
                self.assertNotIn('skuid', rules)
                self.assertEqual(rules, build_ruleset(1000, lan).replace('        meta skuid 1000 return\n', '')
                                 .replace('        meta skuid 1000 accept\n', ''))
        with self.assertRaises(ValueError):
            build_ruleset_without_tor('false')

    def test_rejects_non_bool_lan_setting(self):
        for value in ('false', 0, 1, None, [True]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_ruleset(1000, value)

    @unittest.skipUnless(shutil.which('nft', path='/usr/sbin:/usr/bin') and userns_available(),
                         'needs nft and unprivileged user namespaces')
    def test_nft_accepts_both_variants(self):
        for lan, tor in ((True, True), (False, True), (True, False)):
            with self.subTest(lan=lan, tor=tor), tempfile.NamedTemporaryFile('w', suffix='.nft') as handle:
                handle.write(build_ruleset(4242, lan) if tor else build_ruleset_without_tor(lan))
                handle.flush()
                result = subprocess.run(['unshare', '-rn', '/usr/sbin/nft', '-c', '-f', handle.name],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
