from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

import paths
from paths import DEFAULT, Paths


class PathsTests(unittest.TestCase):
    def test_default_locations(self):
        self.assertEqual(str(DEFAULT.settings), '/etc/syslinuxos-anonimo/settings.json')
        self.assertEqual(str(DEFAULT.obfs4_bridges), '/etc/syslinuxos-anonimo/obfs4-bridges')
        self.assertEqual(str(DEFAULT.torrc), '/run/syslinuxos-anonimo/torrc')
        self.assertEqual(str(DEFAULT.mode), '/run/syslinuxos-anonimo/mode.json')
        self.assertEqual(str(DEFAULT.lock), '/run/syslinuxos-anonimo/helper.lock')
        self.assertEqual(str(DEFAULT.control_socket), '/run/syslinuxos-anonimo/tor/control')
        self.assertEqual(str(DEFAULT.cookie), '/run/syslinuxos-anonimo/tor/control.authcookie')
        self.assertEqual(str(DEFAULT.bootstrap), '/run/syslinuxos-anonimo/status/bootstrap.json')
        self.assertEqual(str(DEFAULT.data_dir), '/var/lib/syslinuxos-anonimo/tor')
        self.assertEqual(str(DEFAULT.default_tor_marker), '/var/lib/syslinuxos-anonimo/default-tor-disabled')
        self.assertEqual(str(DEFAULT.snowflake_bridges), '/usr/share/syslinuxos-anonimo/snowflake-bridges')

    def test_under_moves_every_location(self):
        moved = Paths.under('/x')
        for path in (moved.settings, moved.obfs4_bridges, moved.snowflake_bridges, moved.torrc,
                     moved.mode, moved.lock, moved.control_socket, moved.cookie, moved.bootstrap,
                     moved.data_dir, moved.default_tor_marker):
            self.assertTrue(str(path).startswith('/x/'), path)

    def test_fixed_names_and_ports(self):
        self.assertEqual(paths.TOR_USER, '_anonimo')
        self.assertEqual(paths.TABLE, 'anonimo')
        self.assertEqual((paths.TRANS_PORT, paths.DNS_PORT), (9040, 9053))
        self.assertEqual(paths.ONION_NET, '127.192.0.0/10')
        self.assertEqual(paths.TOR_UNIT, 'syslinuxos-anonimo-tor.service')
        self.assertEqual(paths.WATCH_UNIT, 'syslinuxos-anonimo-watch.service')
        self.assertEqual(paths.BOOT_UNIT, 'syslinuxos-anonimo-boot.service')
        self.assertEqual(paths.HELPER, '/usr/lib/syslinuxos-anonimo/anonimo-helper')


if __name__ == '__main__':
    unittest.main()
