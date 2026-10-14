"""nftables ruleset of anonimo: one dedicated table, replaced atomically.
GPL-3.0-or-later."""

from paths import DNS_PORT, ONION_NET, TABLE, TRANS_PORT

LAN4 = '10.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16'
LAN6 = 'fe80::/10, fc00::/7'
DELETE_ARGS = ['delete', 'table', 'inet', TABLE]


def build_ruleset(tor_uid, allow_lan):
    if isinstance(tor_uid, bool) or not isinstance(tor_uid, int) or tor_uid <= 0:
        raise ValueError('Invalid Tor user id')
    return _ruleset(tor_uid, allow_lan)


def build_ruleset_without_tor(allow_lan):
    """The same table with no Tor exemption, for when the Tor user is
    missing: Tor's own traffic is blocked too."""
    return _ruleset(None, allow_lan)


def _ruleset(tor_uid, allow_lan):
    if not isinstance(allow_lan, bool):
        # A string such as "false" must never open the LAN.
        raise ValueError('Invalid local network setting')
    lan = allow_lan
    exempt = [] if tor_uid is None else [f'meta skuid {tor_uid}']
    # Creating, deleting and re-creating the table in one file makes the
    # replacement a single nftables transaction.
    lines = [f'table inet {TABLE} {{}}', f'delete table inet {TABLE}', f'table inet {TABLE} {{']
    if lan:
        lines += [
            '    set lan4 {', '        type ipv4_addr; flags interval',
            f'        elements = {{ {LAN4} }}', '    }',
            '    set lan6 {', '        type ipv6_addr; flags interval',
            f'        elements = {{ {LAN6} }}', '    }',
        ]
    lines += [
        '    chain nat_out {',
        '        type nat hook output priority -105; policy accept;',
        *(f'        {match} return' for match in exempt),
        # .onion names are mapped into a loopback range: redirect them before
        # loopback traffic is left alone.
        f'        meta nfproto ipv4 ip daddr {ONION_NET} meta l4proto tcp redirect to :{TRANS_PORT}',
        '        oifname "lo" return',
        # All DNS goes to Tor, including queries to a LAN resolver.
        f'        meta nfproto ipv4 udp dport 53 redirect to :{DNS_PORT}',
        f'        meta nfproto ipv4 tcp dport 53 redirect to :{TRANS_PORT}',
    ]
    if lan:
        lines.append('        ip daddr @lan4 return')
    lines += [
        f'        meta nfproto ipv4 meta l4proto tcp redirect to :{TRANS_PORT}',
        '    }',
        '    chain filter_out {',
        '        type filter hook output priority -5; policy drop;',
        '        oifname "lo" accept',
        # After a redirect oifname still names the original interface:
        # accept redirected traffic by destination.
        '        ip daddr 127.0.0.0/8 accept',
        *(f'        {match} accept' for match in exempt),
        '        meta nfproto ipv4 udp sport 68 udp dport 67 accept',
        '        meta l4proto { tcp, udp } th dport 53 reject',
    ]
    if lan:
        lines += [
            '        ip daddr @lan4 accept',
            '        ip6 daddr @lan6 accept',
            '        icmpv6 type { nd-neighbor-solicit, nd-neighbor-advert, nd-router-solicit } accept',
        ]
    lines += [
        '        meta l4proto tcp reject with tcp reset',
        '        reject with icmpx admin-prohibited',
        '    }',
        '    chain filter_fwd {',
        '        type filter hook forward priority -5; policy drop;',
        '    }',
        '}',
    ]
    return '\n'.join(lines) + '\n'
