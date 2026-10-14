"""Fixed paths, names and ports of syslinuxos-anonimo. GPL-3.0-or-later."""

from dataclasses import dataclass
from pathlib import Path

TOR_USER = '_anonimo'
TOR_UNIT = 'syslinuxos-anonimo-tor.service'
WATCH_UNIT = 'syslinuxos-anonimo-watch.service'
BOOT_UNIT = 'syslinuxos-anonimo-boot.service'
TABLE = 'anonimo'
TRANS_PORT = 9040
DNS_PORT = 9053
ONION_NET = '127.192.0.0/10'
HELPER = '/usr/lib/syslinuxos-anonimo/anonimo-helper'
PKEXEC = '/usr/bin/pkexec'
TOR = '/usr/bin/tor'
NFT = '/usr/sbin/nft'
SYSTEMCTL = '/usr/bin/systemctl'
RUNUSER = '/usr/sbin/runuser'
OBFS4PROXY = '/usr/bin/obfs4proxy'
SNOWFLAKE_CLIENT = '/usr/bin/snowflake-client'
BLEACHBIT = '/usr/bin/bleachbit'
CHECK_URL = 'https://check.torproject.org/api/ip'


@dataclass(frozen=True)
class Paths:
    etc: Path = Path('/etc/syslinuxos-anonimo')
    run: Path = Path('/run/syslinuxos-anonimo')
    lib: Path = Path('/var/lib/syslinuxos-anonimo')
    share: Path = Path('/usr/share/syslinuxos-anonimo')

    @classmethod
    def under(cls, root):
        """Same layout below another directory, for tests."""
        root = Path(root)
        return cls(root / 'etc', root / 'run', root / 'lib', root / 'share')

    settings = property(lambda self: self.etc / 'settings.json')
    obfs4_bridges = property(lambda self: self.etc / 'obfs4-bridges')
    snowflake_bridges = property(lambda self: self.share / 'snowflake-bridges')
    torrc = property(lambda self: self.run / 'torrc')
    mode = property(lambda self: self.run / 'mode.json')
    lock = property(lambda self: self.run / 'helper.lock')
    tor_run = property(lambda self: self.run / 'tor')
    control_socket = property(lambda self: self.run / 'tor' / 'control')
    cookie = property(lambda self: self.run / 'tor' / 'control.authcookie')
    bootstrap = property(lambda self: self.run / 'status' / 'bootstrap.json')
    data_dir = property(lambda self: self.lib / 'tor')
    default_tor_marker = property(lambda self: self.lib / 'default-tor-disabled')


DEFAULT = Paths()
