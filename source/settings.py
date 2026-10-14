"""Settings and obfs4 bridge-line validation. GPL-3.0-or-later."""

import base64
import binascii
import ipaddress
import json
import re

DEFAULT_SETTINGS = {'allow_lan': True, 'bridges': 'none', 'start_at_boot': False, 'close_apps': True}
BRIDGE_TYPES = ('none', 'obfs4', 'snowflake')
MAX_BRIDGE_LINES = 32
MAX_BRIDGE_TEXT = 16384

_FINGERPRINT = re.compile(r'[0-9A-Fa-f]{40}')
_CERT = re.compile(r'cert=([A-Za-z0-9+/]+={0,2})')
_PORT = re.compile(r'[0-9]{1,5}')
_IAT = ('iat-mode=0', 'iat-mode=1', 'iat-mode=2')


class SettingsError(ValueError):
    pass


def validate_settings(data):
    if not isinstance(data, dict):
        raise SettingsError('Settings must be a JSON object')
    if set(data) - set(DEFAULT_SETTINGS):
        raise SettingsError('Unknown setting')
    result = dict(DEFAULT_SETTINGS)
    for key, value in data.items():
        valid = value in BRIDGE_TYPES if key == 'bridges' else isinstance(value, bool)
        if not valid or (key == 'bridges' and not isinstance(value, str)):
            raise SettingsError('Invalid setting value')
        result[key] = value
    return result


def load_settings(path):
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError, RecursionError) as error:
        raise SettingsError('Cannot read settings') from error
    return validate_settings(data)


def _valid_endpoint(text):
    host, separator, port = text.rpartition(':')
    if '%' in host or not separator or not _PORT.fullmatch(port) or not 0 < int(port) < 65536:
        return False
    version = 4
    if host.startswith('[') and host.endswith(']'):
        host, version = host[1:-1], 6
    try:
        return ipaddress.ip_address(host).version == version
    except ValueError:
        return False


def parse_obfs4_line(line):
    """Return the normalised line "obfs4 ADDR:PORT FINGERPRINT cert=... iat-mode=N"."""
    words = line.split()
    if words[:1] == ['Bridge']:
        words = words[1:]
    if len(words) != 5 or words[0] != 'obfs4':
        raise SettingsError('Invalid obfs4 bridge line')
    _, endpoint, fingerprint, cert, iat = words
    match = _CERT.fullmatch(cert)
    if (not _valid_endpoint(endpoint) or not _FINGERPRINT.fullmatch(fingerprint)
            or not match or iat not in _IAT):
        raise SettingsError('Invalid obfs4 bridge line')
    value = match.group(1).rstrip('=')
    try:
        base64.b64decode(value + '=' * (-len(value) % 4), validate=True)
    except binascii.Error as error:
        raise SettingsError('Invalid obfs4 bridge line') from error
    return ' '.join(words)


def parse_obfs4_lines(text):
    if len(text) > MAX_BRIDGE_TEXT:
        raise SettingsError('Bridge list too long')
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith('#'):
            lines.append(parse_obfs4_line(stripped))
    if len(lines) > MAX_BRIDGE_LINES:
        raise SettingsError('Too many bridge lines')
    return lines
