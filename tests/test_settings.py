import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from settings import (DEFAULT_SETTINGS, MAX_BRIDGE_LINES, SettingsError, load_settings,
                      parse_obfs4_line, parse_obfs4_lines, validate_settings)

CERT = base64.b64encode(bytes(range(52))).decode().rstrip('=')
FINGERPRINT = '0123456789ABCDEF0123456789ABCDEF01234567'
LINE = f'obfs4 192.0.2.10:443 {FINGERPRINT} cert={CERT} iat-mode=0'


class SettingsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(DEFAULT_SETTINGS, {'allow_lan': True, 'bridges': 'none',
                                            'start_at_boot': False, 'close_apps': True})
        self.assertEqual(validate_settings({}), DEFAULT_SETTINGS)

    def test_partial_settings_keep_defaults(self):
        result = validate_settings({'allow_lan': False})
        self.assertFalse(result['allow_lan'])
        self.assertEqual(result['bridges'], 'none')

    def test_rejects_wrong_shapes(self):
        for data in ([], 'x', None):
            with self.subTest(data=data), self.assertRaisesRegex(SettingsError, 'JSON object'):
                validate_settings(data)
        with self.assertRaisesRegex(SettingsError, 'Unknown setting'):
            validate_settings({'proxy': 1})
        for data in ({'allow_lan': 1}, {'start_at_boot': 'yes'}, {'close_apps': None},
                     {'bridges': 'meek'}, {'bridges': True}):
            with self.subTest(data=data), self.assertRaisesRegex(SettingsError, 'Invalid setting value'):
                validate_settings(data)

    def test_load_missing_corrupted_and_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            self.assertEqual(load_settings(path), DEFAULT_SETTINGS)
            path.write_text('{broken')
            with self.assertRaisesRegex(SettingsError, 'Cannot read settings'):
                load_settings(path)
            path.write_text(json.dumps({'bridges': 'snowflake'}))
            self.assertEqual(load_settings(path)['bridges'], 'snowflake')

    def test_deeply_nested_file_is_cannot_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text('[' * 100000)
            with self.assertRaisesRegex(SettingsError, 'Cannot read settings'):
                load_settings(path)


class BridgeLineTests(unittest.TestCase):
    def test_valid_line_with_and_without_prefix(self):
        self.assertEqual(parse_obfs4_line(LINE), LINE)
        self.assertEqual(parse_obfs4_line('Bridge ' + LINE), LINE)
        self.assertEqual(parse_obfs4_line('  ' + LINE.replace(' ', '   ') + '  '), LINE)

    def test_ipv6_endpoint(self):
        line = LINE.replace('192.0.2.10:443', '[2001:db8::7]:9001')
        self.assertEqual(parse_obfs4_line(line), line)

    def test_rejects_malformed_lines(self):
        bad = [
            LINE.replace('obfs4 ', 'obfs3 '),
            LINE.replace(FINGERPRINT, FINGERPRINT[:-1]),
            LINE.replace(FINGERPRINT, 'Z' * 40),
            LINE.replace('cert=', 'crt='),
            LINE.replace(f'cert={CERT}', 'cert=AAAAA'),
            LINE.replace('iat-mode=0', 'iat-mode=3'),
            LINE.replace(':443', ':0'),
            LINE.replace(':443', ':70000'),
            LINE.replace('192.0.2.10', 'bridge.example.com'),
            LINE.replace('192.0.2.10:443', '[192.0.2.10]:443'),
            LINE.replace('192.0.2.10:443', '[fe80::1%eth0]:443'),
            LINE.replace('192.0.2.10:443', '[fe80::1%a#b"c]:443'),
            LINE + ' extra',
            'obfs4',
        ]
        for line in bad:
            with self.subTest(line=line), self.assertRaisesRegex(SettingsError, 'Invalid obfs4 bridge line'):
                parse_obfs4_line(line)

    def test_list_skips_blank_and_comment_lines(self):
        text = f'# from bridges.torproject.org\n\n{LINE}\r\nBridge {LINE}\n'
        self.assertEqual(parse_obfs4_lines(text), [LINE, LINE])
        self.assertEqual(parse_obfs4_lines(''), [])

    def test_list_limits(self):
        with self.assertRaisesRegex(SettingsError, 'Too many bridge lines'):
            parse_obfs4_lines('\n'.join([LINE] * (MAX_BRIDGE_LINES + 1)))
        with self.assertRaisesRegex(SettingsError, 'Bridge list too long'):
            parse_obfs4_lines('#' * 20000)

    def test_port_is_ascii_digits_within_range(self):
        for port in ('²', '9' * 5000, '0443x', '+443'):
            line = LINE.replace(':443', f':{port}')
            with self.subTest(port=port[:10]), self.assertRaisesRegex(SettingsError, 'Invalid obfs4 bridge line'):
                parse_obfs4_line(line)


if __name__ == '__main__':
    unittest.main()
