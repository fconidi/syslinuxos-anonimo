"""State files and the state shown to users. GPL-3.0-or-later."""

import json
import os
import re
import tempfile
from pathlib import Path

ACTIVE_UNIT_STATES = ('active', 'reloading')
_FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')


def read_json(path):
    """A JSON object from a file, or None when missing, unreadable or not an object."""
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def write_text_atomic(path, text, mode=0o644, uid=-1, gid=-1):
    """Replace a file in one rename; the parent directory must exist."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        if uid != -1 or gid != -1:
            os.chown(tmp, uid, gid)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path, data, mode=0o644, uid=-1, gid=-1):
    write_text_atomic(path, json.dumps(data, sort_keys=True) + '\n', mode, uid, gid)


def parse_bootstrap_phase(value):
    """Parse 'NOTICE BOOTSTRAP PROGRESS=100 TAG=done SUMMARY="Done"'."""
    words = value.split(None, 2)
    if len(words) < 2 or words[1] != 'BOOTSTRAP':
        raise ValueError('Not a bootstrap status')
    fields = {}
    for key, raw in _FIELD.findall(words[2] if len(words) > 2 else ''):
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            raw = re.sub(r'\\(.)', r'\1', raw[1:-1])
        fields[key.upper()] = raw
    try:
        progress = int(fields.get('PROGRESS', '0'))
    except ValueError:
        progress = 0
    return {'severity': words[0], 'progress': max(0, min(progress, 100)),
            'tag': fields.get('TAG', ''), 'summary': fields.get('SUMMARY', ''),
            'warning': fields.get('WARNING', ''), 'reason': fields.get('REASON', '')}


def compute_state(mode, bootstrap, unit_state):
    """The spec's state table: rules in order, first match wins."""
    if not mode or mode.get('mode') != 'on':
        return 'off'
    progress = (bootstrap or {}).get('progress')
    if unit_state in ACTIVE_UNIT_STATES and progress == 100:
        return 'protected'
    if unit_state in ('failed', 'inactive') or mode.get('error'):
        return 'error'
    return 'connecting'


def clock_problem(bootstrap):
    data = bootstrap or {}
    text = f"{data.get('warning', '')} {data.get('reason', '')}".lower()
    return 'clock' in text or 'skew' in text
