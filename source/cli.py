"""anonimo: command-line interface of SysLinuxOS Anonimo. GPL-3.0-or-later."""

import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import appclose
import client
from i18n import tr
from paths import HELPER

YES = ('y', 'yes')


def default_deps():
    return SimpleNamespace(run_helper=client.run_helper, read_status=client.read_status,
                           tor_check=client.tor_check, helper_exists=lambda: Path(HELPER).is_file(),
                           find_targets=appclose.find_targets, close_apps=appclose.close_apps,
                           run_bleachbit=appclose.run_bleachbit)


def build_parser():
    parser = argparse.ArgumentParser(prog='anonimo', description=tr('Route all traffic of this computer through Tor.'))
    commands = parser.add_subparsers(dest='command', required=True)
    for name, text in (('start', tr('Switch anonimo on')), ('stop', tr('Switch anonimo off'))):
        command = commands.add_parser(name, help=text)
        group = command.add_mutually_exclusive_group()
        group.add_argument('--close-apps', dest='close_apps', action='store_true',
                           help=tr('Close network applications first'))
        group.add_argument('--no-close-apps', dest='close_apps', action='store_false',
                           help=tr('Do not close applications'))
        command.set_defaults(close_apps=None)
    status = commands.add_parser('status', help=tr('Show the current state'))
    status.add_argument('--json', action='store_true', help=tr('Machine-readable output'))
    status.add_argument('--check', action='store_true', help=tr('Ask check.torproject.org whether traffic uses Tor'))
    commands.add_parser('identity', help=tr('Use new Tor circuits for new connections'))
    settings = commands.add_parser('settings', help=tr('Show or change the settings'))
    settings.add_argument('--lan', choices=('on', 'off'), help=tr('Reach the local network directly'))
    settings.add_argument('--bridges', choices=('none', 'obfs4', 'snowflake'), help=tr('Bridge type'))
    settings.add_argument('--boot', choices=('on', 'off'), help=tr('Switch on automatically at boot'))
    settings.add_argument('--close-apps', choices=('on', 'off'), dest='close_apps',
                          help=tr('Close network applications on start and stop'))
    bridges = commands.add_parser('bridges', help=tr('Show or set the obfs4 bridge lines'))
    bridges.add_argument('--set', metavar='FILE',
                         help=tr('File with one bridge line per line, or - for standard input'))
    return parser


def main(argv=None, stdin=None, stdout=None, deps=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    deps = deps or default_deps()
    args = build_parser().parse_args(argv)

    def say(text):
        if text:
            print(text, file=stdout, flush=True)

    if args.command == 'status':
        return _status(args, deps, say)
    if not deps.helper_exists():
        say(tr('Install the syslinuxos-anonimo package to use this command.'))
        return 1
    if args.command in ('start', 'stop'):
        ask = args.close_apps is None
        close = args.close_apps
        if close is None:
            close = deps.read_status()['settings']['close_apps'] and stdin.isatty()
        if close:
            _close_apps(ask, stdin, say, deps)
        code = _run(args.command, None, deps, say)
        if args.command == 'start' and code == 0:
            return _check_after_start(deps, say)
        if args.command == 'start' and code == 2:
            # The error state keeps the firewall loaded: say how to get out.
            say(tr('Run "anonimo stop" to restore the normal network.'))
        return code
    if args.command == 'identity':
        return _run('identity', None, deps, say)
    if args.command == 'settings':
        current = deps.read_status()['settings']
        changes = {'allow_lan': args.lan, 'bridges': args.bridges,
                   'start_at_boot': args.boot, 'close_apps': args.close_apps}
        if all(value is None for value in changes.values()):
            say(json.dumps(current, indent=2, sort_keys=True))
            return 0
        new = dict(current)
        for key, value in changes.items():
            if value is not None:
                new[key] = value if key == 'bridges' else value == 'on'
        return _run('set-settings', json.dumps(new), deps, say)
    if args.set is None:
        return _run('get-bridges', None, deps, say)
    try:
        text = stdin.read() if args.set == '-' else Path(args.set).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        say(tr('Cannot read the bridge file: {path}', path=args.set))
        return 1
    return _run('set-bridges', text, deps, say)


def _status(args, deps, say):
    status = deps.read_status()
    result = {key: status[key] for key in ('state', 'progress', 'summary', 'error', 'settings')}
    if args.check:
        try:
            result['check'] = deps.tor_check()
        except client.CheckError as error:
            result['check'] = {'error': str(error)}
    if args.json:
        say(json.dumps(result, sort_keys=True))
    else:
        say(client.describe(status, cli=True))
        if 'check' in result:
            say(client.check_text(result['check']))
    return client.EXIT_CODES[status['state']]


def _check_after_start(deps, say):
    """Ask check.torproject.org, as the window does once protected. Only
    IsTor: false is a failure; an unreachable site is a warning."""
    try:
        result = deps.tor_check()
    except client.CheckError as error:
        result = {'error': str(error)}
    say(client.check_text(result))
    if result.get('is_tor') is True:
        return 0
    say(tr('Run "anonimo stop" to restore the normal network.'))
    return 0 if 'error' in result else 1


def _close_apps(ask, stdin, say, deps):
    targets = deps.find_targets()
    if targets and ask:
        names = ', '.join(sorted({name for _, name in targets}))
        say(tr('Close these applications first? {names} [y/N]', names=names))
        if stdin.readline().strip().lower() not in YES + (tr('y'),):
            return
    if targets:
        deps.close_apps([pid for pid, _ in targets])
    deps.run_bleachbit()


def _run(action, input_text, deps, say):
    def on_event(event):
        if event['event'] == 'bridges':
            for line in event.get('lines', []):
                say(str(line))
        else:
            say(client.event_text(event))

    code = deps.run_helper(action, input_text, on_event)
    if code in client.AUTH_FAILED:
        say(tr('Authorization cancelled or failed.'))
    return code


if __name__ == '__main__':
    sys.exit(main())
