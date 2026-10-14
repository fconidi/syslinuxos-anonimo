import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from torctl import TorControl, TorControlError, trusted_owners

COOKIE = bytes(range(32))
BOOTSTRAP = (b'250-status/bootstrap-phase=NOTICE BOOTSTRAP PROGRESS=85 TAG=ap_conn '
             b'SUMMARY="Connecting to a relay to build circuits"\r\n250 OK\r\n')


class FakeTor(threading.Thread):
    def __init__(self, path, replies, cookie=COOKIE):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.replies, self.cookie, self.received = replies, cookie, []

    def run(self):
        try:
            conn, _ = self.server.accept()
            with conn, conn.makefile('rb') as reader:
                self.serve(conn, reader)
        except OSError:
            pass   # the client may close first; that is not what is tested
        finally:
            self.server.close()

    def serve(self, conn, reader):
        for raw in reader:
            line = raw.decode().rstrip('\r\n')
            self.received.append(line)
            if line.startswith('AUTHENTICATE '):
                if line.split(' ', 1)[1] != self.cookie.hex():
                    conn.sendall(b'515 Authentication failed: Wrong cookie.\r\n')
                    return
                conn.sendall(b'250 OK\r\n')
            elif line == 'QUIT':
                return
            elif line in self.replies:
                if self.replies[line] is None:
                    return
                conn.sendall(self.replies[line])
            else:
                conn.sendall(b'510 Unrecognized command\r\n')


class TorControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.socket = os.path.join(self.tmp.name, 'control')
        self.cookie = Path(self.tmp.name) / 'cookie'
        self.cookie.write_bytes(COOKIE)

    def tearDown(self):
        self.tmp.cleanup()

    def control(self, owners=None):
        return TorControl(self.socket, self.cookie, owners={os.getuid()} if owners is None else owners)

    def serve(self, replies, cookie=COOKIE):
        server = FakeTor(self.socket, replies, cookie)
        server.start()
        return server

    def test_bootstrap(self):
        server = self.serve({'GETINFO status/bootstrap-phase': BOOTSTRAP})
        data = self.control().bootstrap()
        self.assertEqual(data['progress'], 85)
        self.assertEqual(data['summary'], 'Connecting to a relay to build circuits')
        server.join(2)
        self.assertEqual(server.received[0], 'AUTHENTICATE ' + COOKIE.hex())

    def test_newnym(self):
        server = self.serve({'SIGNAL NEWNYM': b'250 OK\r\n'})
        self.control().newnym()
        server.join(2)
        self.assertIn('SIGNAL NEWNYM', server.received)

    def test_wrong_cookie(self):
        self.serve({}, cookie=bytes(32))
        with self.assertRaisesRegex(TorControlError, 'Tor refused the command'):
            self.control().bootstrap()

    def test_cookie_with_wrong_length(self):
        self.cookie.write_bytes(b'short')
        with self.assertRaisesRegex(TorControlError, 'Invalid Tor control cookie'):
            self.control().bootstrap()

    def test_connection_closed(self):
        self.serve({'GETINFO status/bootstrap-phase': None})
        with self.assertRaisesRegex(TorControlError, 'closed the control connection'):
            self.control().bootstrap()

    def test_reader_is_closed(self):
        readers, real_makefile = [], socket.socket.makefile

        class Reader:
            def __init__(self, inner):
                self.inner, self.closed = inner, False

            def readline(self, *args):
                return self.inner.readline(*args)

            def close(self):
                self.closed = True
                self.inner.close()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()

        def makefile(sock, *args, **kwargs):
            inner = real_makefile(sock, *args, **kwargs)
            if threading.current_thread() is not threading.main_thread():
                return inner                    # the fake Tor's side
            readers.append(Reader(inner))
            return readers[-1]

        server = self.serve({'SIGNAL NEWNYM': b'250 OK\r\n'})
        with patch('socket.socket.makefile', makefile):
            self.control().newnym()
        server.join(2)
        self.assertEqual([reader.closed for reader in readers], [True])

    def test_symlinked_cookie_is_refused(self):
        real = Path(self.tmp.name) / 'real-cookie'
        self.cookie.rename(real)
        self.cookie.symlink_to(real)
        server = self.serve({'SIGNAL NEWNYM': b'250 OK\r\n'})
        with self.assertRaises(OSError):
            self.control().newnym()
        self.assertEqual(server.received, [])

    def test_cookie_of_another_user_is_refused(self):
        server = self.serve({'SIGNAL NEWNYM': b'250 OK\r\n'})
        with self.assertRaisesRegex(TorControlError, 'Untrusted Tor control cookie'):
            self.control(owners={os.getuid() + 1}).newnym()
        self.assertEqual(server.received, [])

    def test_fifo_cookie_is_refused_without_blocking(self):
        self.cookie.unlink()
        os.mkfifo(self.cookie)
        with self.assertRaisesRegex(TorControlError, 'Untrusted Tor control cookie'):
            self.control().newnym()

    def test_default_owners_are_root_and_the_tor_user(self):
        entry = SimpleNamespace(pw_uid=4242)
        with patch('torctl.pwd.getpwnam', return_value=entry) as getpwnam:
            self.assertEqual(trusted_owners(), {0, 4242})
        getpwnam.assert_called_once_with('_anonimo')
        with patch('torctl.pwd.getpwnam', side_effect=KeyError('_anonimo')):
            self.assertEqual(trusted_owners(), {0})

    def test_missing_socket_is_os_error(self):
        with self.assertRaises(OSError):
            self.control().bootstrap()


if __name__ == '__main__':
    unittest.main()
