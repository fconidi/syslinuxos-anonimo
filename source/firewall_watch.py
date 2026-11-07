"""Repair the anonimo nftables table after another service flushes it."""

import json
import time

from helper import Helper, System
from paths import DEFAULT, NFT, TABLE
from state import write_json_atomic


def protective_table(result):
    if result.returncode != 0:
        return False
    try:
        objects = json.loads(result.stdout)['nftables']
    except (KeyError, TypeError, ValueError):
        return False
    chains = {entry['chain']['name']: entry['chain'] for entry in objects if 'chain' in entry}
    for name, hook in (('filter_out', 'output'), ('filter_fwd', 'forward')):
        chain = chains.get(name, {})
        if chain.get('hook') != hook or chain.get('policy') != 'drop':
            return False
    nat = chains.get('nat_out', {})
    if nat.get('hook') != 'output' or nat.get('type') != 'nat':
        return False
    return any(entry.get('rule', {}).get('chain') == 'nat_out' and
               any('redirect' in expr for expr in entry['rule'].get('expr', []))
               for entry in objects)


def check_once(helper):
    """Serialize observation and repair with start, stop and settings changes."""
    with helper.lock():
        if not helper._is_on():
            present = False
        else:
            result = helper.system.run([NFT, '-j', 'list', 'table', 'inet', TABLE], timeout=10)
            if not protective_table(result):
                helper._load_current_table()
                result = helper.system.run([NFT, '-j', 'list', 'table', 'inet', TABLE], timeout=10)
            present = protective_table(result)
        helper.paths.firewall_health.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        write_json_atomic(helper.paths.firewall_health,
                          {'present': present, 'updated': helper.system.wall()})
        return present


def run(helper=None, interval=1, sleep=time.sleep):
    helper = helper or Helper(System(), DEFAULT)
    while True:
        try:
            check_once(helper)
        except Exception:
            # An old positive observation must never remain valid after an error.
            helper.paths.firewall_health.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            write_json_atomic(helper.paths.firewall_health,
                              {'present': False, 'updated': helper.system.wall()})
        sleep(interval)


def main():
    run()
    return 0
