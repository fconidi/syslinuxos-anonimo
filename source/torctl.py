"""Minimal Tor control-socket client: cookie authentication, bootstrap
phase, new circuits. GPL-3.0-or-later."""

import os
import pwd
import socket
import stat

from paths import TOR_USER
from state import parse_bootstrap_phase

MAX_LINE = 65536


class TorControlError(Exception):
    pass


def _readline(reader):
    raw = reader.readline(MAX_LINE)
    if not raw:
        raise TorControlError('Tor closed the control connection')
    return raw.decode('utf-8', 'replace').rstrip('\r\n')


def _read_reply(reader):
    lines = []
    while True:
        line = _readline(reader)
        if len(line) < 4 or not line[:3].isdigit():
            raise TorControlError('Malformed Tor control reply')
        code, kind, text = line[:3], line[3], line[4:]
        if kind == '+':
            data = [text]
            while (more := _readline(reader)) != '.':
                data.append(more)
            lines.append((code, '\n'.join(data)))
            continue
        if kind not in ' -':
            raise TorControlError('Malformed Tor control reply')
        lines.append((code, text))
        if kind == ' ':
            break
    if not lines[-1][0].startswith('2'):
        raise TorControlError('Tor refused the command: ' + lines[-1][1])
    return lines


def trusted_owners():
    """Users that may own the cookie: root and the Tor user."""
    owners = {0}
    try:
        owners.add(pwd.getpwnam(TOR_USER).pw_uid)
    except KeyError:
        pass
    return owners


class TorControl:
    def __init__(self, socket_path, cookie_path, timeout=5.0, owners=None):
        self.socket_path = str(socket_path)
        self.cookie_path = cookie_path
        self.timeout = timeout
        self.owners = owners

    def _read_cookie(self):
        # The helper reads the cookie as root from a directory of the Tor
        # user: no symlinks, no FIFOs, only a regular file of a trusted owner.
        fd = os.open(self.cookie_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            owners = trusted_owners() if self.owners is None else self.owners
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in owners:
                raise TorControlError('Untrusted Tor control cookie')
            return os.read(fd, 64)
        finally:
            os.close(fd)

    def _exchange(self, commands):
        cookie = self._read_cookie()
        if len(cookie) != 32:
            raise TorControlError('Invalid Tor control cookie')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            with sock.makefile('rb') as reader:
                replies = []
                for command in ['AUTHENTICATE ' + cookie.hex(), *commands]:
                    sock.sendall(command.encode('ascii') + b'\r\n')
                    replies.append(_read_reply(reader))
                sock.sendall(b'QUIT\r\n')
        return replies[1:]

    def bootstrap(self):
        (reply,) = self._exchange(['GETINFO status/bootstrap-phase'])
        for _, text in reply:
            key, separator, value = text.partition('=')
            if key == 'status/bootstrap-phase' and separator:
                try:
                    return parse_bootstrap_phase(value)
                except ValueError as error:
                    raise TorControlError('Malformed bootstrap status') from error
        raise TorControlError('Missing bootstrap status')

    def newnym(self):
        self._exchange(['SIGNAL NEWNYM'])
