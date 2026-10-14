"""Runs inside `unshare -rn`: applies an anonimo ruleset in an empty network
namespace and reports what happens to typical traffic as JSON. Test tool
only. GPL-3.0-or-later."""

import json
import socket
import struct
import subprocess
import sys
import threading
import time

NFT = '/usr/sbin/nft'
IP = '/usr/sbin/ip'
RESTORE = '/usr/sbin/iptables-nft-restore'
SO_ORIGINAL_DST = 80
UFW_LIKE_RELOAD = ('*filter\n:INPUT DROP [0:0]\n:FORWARD DROP [0:0]\n:OUTPUT ACCEPT [0:0]\n'
                   '-A INPUT -i lo -j ACCEPT\n-A OUTPUT -o lo -j ACCEPT\nCOMMIT\n'
                   '*nat\n:PREROUTING ACCEPT [0:0]\n:OUTPUT ACCEPT [0:0]\nCOMMIT\n')


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True, text=True)


class Recorder:
    """Fake TransPort (records the original destination) and fake DNSPort."""

    def __init__(self):
        self.tcp, self.udp = [], []
        self.ready = threading.Event()

    def serve(self):
        tcp = socket.socket()
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind(('127.0.0.1', 9040))
        tcp.listen(16)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(('127.0.0.1', 9053))
        threading.Thread(target=self._udp, args=(udp,), daemon=True).start()
        self.ready.set()
        while True:
            conn, _ = tcp.accept()
            port, addr = struct.unpack('!2xH4s8x', conn.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16))
            self.tcp.append(f'{socket.inet_ntoa(addr)}:{port}')
            conn.close()

    def _udp(self, udp):
        while True:
            data, _ = udp.recvfrom(2048)
            self.udp.append(len(data))


def tcp(host, port, family=socket.AF_INET):
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect((host, port))
        return 'connected'
    except socket.timeout:
        return 'timeout'
    except ConnectionRefusedError:
        return 'refused'
    except OSError as error:
        return f'error:{error.errno}'
    finally:
        sock.close()


def udp(host, port, sport=None, broadcast=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if sport:
            sock.bind(('0.0.0.0', sport))
        sock.sendto(b'\x12\x34' + b'\x00' * 10, (host, port))
        return 'sent'
    except PermissionError:
        return 'blocked'
    except OSError as error:
        return f'error:{error.errno}'
    finally:
        sock.close()


def probe(recorder):
    tcp_before, udp_before = len(recorder.tcp), len(recorder.udp)
    result = {
        'web': tcp('1.1.1.1', 443),
        'lan_web': tcp('192.168.50.7', 80),
        'onion': tcp('127.200.1.1', 80),
        'dns_udp_lan': udp('192.168.50.1', 53),
        'dns_tcp_lan': tcp('192.168.50.1', 53),
        'ntp': udp('8.8.8.8', 123),
        'dhcp': udp('255.255.255.255', 67, sport=68, broadcast=True),
        'ipv6_web': tcp('2001:db8:1::1', 80, socket.AF_INET6),
    }
    time.sleep(0.3)
    result['redirected'] = recorder.tcp[tcp_before:]
    result['dns_received'] = len(recorder.udp) - udp_before
    return result


def tables():
    out = subprocess.run([NFT, 'list', 'tables'], capture_output=True, text=True, check=True).stdout
    return [line.replace('table ', '', 1).strip() for line in out.splitlines() if line.strip()]


def main():
    rules = sys.argv[1]
    sh(IP, 'link', 'set', 'lo', 'up')
    sh(IP, 'link', 'add', 'd0', 'type', 'dummy')
    sh(IP, 'addr', 'add', '192.168.50.2/24', 'dev', 'd0')
    sh(IP, '-6', 'addr', 'add', '2001:db8::2/64', 'dev', 'd0', 'nodad')
    sh(IP, 'link', 'set', 'd0', 'up')
    sh(IP, 'route', 'add', 'default', 'via', '192.168.50.1')
    sh(IP, '-6', 'route', 'add', 'default', 'via', '2001:db8::1')
    recorder = Recorder()
    threading.Thread(target=recorder.serve, daemon=True).start()
    recorder.ready.wait(5)
    sh(NFT, '-f', rules)
    report = {'on': probe(recorder)}
    subprocess.run([RESTORE], input=UFW_LIKE_RELOAD, text=True, check=True, capture_output=True)
    report['tables_after_reload'] = tables()
    report['after_reload'] = probe(recorder)
    sh(NFT, 'delete', 'table', 'inet', 'anonimo')
    report['tables_after_off'] = tables()
    report['off'] = probe(recorder)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
