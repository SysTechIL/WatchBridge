"""WatchBridge command line. Every option in the window is available here; run with --help."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from engine import SyncEngine, Cancelled, __version__, checked_config, public_error, write_report, report_name
import runtime
import scheduler
import settings as storage

STATUSES = ('READY', 'TAGGED', 'UNWATCHED', 'UNMATCHED', 'INCOMPLETE', 'ERROR')
# flag, settings key, help, secret
CONNECTION = [
    ('--plex-url', 'plex_url', 'Plex server URL, e.g. http://localhost:32400', False),
    ('--plex-token', 'plex_token', 'Plex personal token', True),
    ('--plex-profile', 'plex_user', 'exact Plex profile name; empty uses the token owner', False),
    ('--jf-url', 'jf_url', 'Jellyfin server URL, e.g. http://localhost:8096', False),
    ('--jf-user', 'jf_user', 'exact Jellyfin user name', False),
    ('--jf-api-key', 'jf_api_key', 'Jellyfin API key', True),
    ('--jf-password', 'jf_password', 'Jellyfin password (used only without an API key)', True),
    ('--qb-url', 'qb_url', 'qBittorrent Web UI URL, e.g. http://localhost:8080', False),
    ('--qb-user', 'qb_username', 'qBittorrent Web UI username', False),
    ('--qb-password', 'qb_password', 'qBittorrent Web UI password', True),
    ('--tag', 'tag', 'existing qBittorrent tag to add (default Watched)', False),
]
ENV = {key: 'WATCHBRIDGE_' + key.upper() for _, key, _, secret in CONNECTION if secret}

EPILOG = '''examples:
  %(prog)s test
  %(prog)s scan --status ready,unmatched --details
  %(prog)s scan --csv C:\\Reports\\watched.csv
  %(prog)s apply                          tag all ready torrents
  %(prog)s apply --name "Show Name" --hash 0123abcd...
  %(prog)s auto --interval 15             like "Auto sync" in the window
  %(prog)s config set --server jellyfin --jf-url http://nas:8096 --jf-user Me --jf-password - --remember
  %(prog)s schedule set interval --every 30m --at-logon
  %(prog)s schedule set daily --at 03:00,15:00
  %(prog)s schedule set weekly --days sun-thu --at 22:30
  %(prog)s schedule set realtime --fallback 60 --delay 30
  %(prog)s schedule show

secrets: pass "-" to be prompted, or set ''' + ', '.join(ENV.values()) + '''.
exit codes: 0 ok, 1 failed or scan errors, 2 invalid input, 3 another run in progress,
            4 background runs paused, 130 stopped.'''


class Exit(Exception):
    def __init__(self, message, code=runtime.USAGE):
        super().__init__(message)
        self.code = code


def parser():
    p = argparse.ArgumentParser(prog='WatchBridgeCLI', description='WatchBridge ' + __version__
                                + ': add a qBittorrent tag to torrents watched on Plex or Jellyfin.',
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--version', action='version', version='WatchBridge ' + __version__)
    sub = p.add_subparsers(dest='command', metavar='command')

    conn = argparse.ArgumentParser(add_help=False)
    group = conn.add_argument_group('connection (overrides saved settings for this run)')
    group.add_argument('--server', choices=('plex', 'jellyfin'), dest='media_server', help='media server to read')
    for flag, key, text, secret in CONNECTION:
        group.add_argument(flag, dest=key, metavar='VALUE', help=text + (' ("-" prompts)' if secret else ''))
    group.add_argument('--config', metavar='FILE', help='read connection details from a config.json file')
    group.add_argument('--save', action='store_true', help='also save these connection details')
    remember = group.add_mutually_exclusive_group()
    remember.add_argument('--remember', dest='remember', action='store_true', default=None,
                          help='with --save: remember credentials, encrypted for this Windows user')
    remember.add_argument('--no-remember', dest='remember', action='store_false',
                          help='with --save: do not store credentials (removes stored ones)')

    out = argparse.ArgumentParser(add_help=False)
    group = out.add_argument_group('output')
    group.add_argument('--status', metavar='LIST', help='show only these statuses: ' + ','.join(s.lower() for s in STATUSES))
    group.add_argument('--search', metavar='TEXT', help='show only torrents whose name or unmatched paths contain TEXT')
    group.add_argument('--details', action='store_true', help='show unmatched paths and errors under each torrent')
    group.add_argument('--json', action='store_true', help='print results as JSON')
    group.add_argument('--csv', metavar='PATH', help='export ALL video results to this CSV file (filters do not apply)')
    group.add_argument('--no-report', action='store_true', help='do not write the automatic report to the reports folder')
    group.add_argument('-q', '--quiet', action='store_true', help='print only results and errors')

    sub.add_parser('gui', help='open the desktop window (default with no command)')
    sub.add_parser('test', parents=[conn], help='test the media server and qBittorrent connections')
    sub.add_parser('scan', parents=[conn, out], help='dry run: show what would be tagged, change nothing',
                   aliases=['dry-run'])
    a = sub.add_parser('apply', parents=[conn, out], help='scan, then add the tag to ready torrents')
    a.add_argument('--hash', action='append', default=[], metavar='HASH',
                   help='only these torrent hashes (repeat or comma-separate); like "Selected ready torrents"')
    a.add_argument('--name', action='append', default=[], metavar='TEXT',
                   help='only ready torrents whose name contains TEXT (repeatable)')
    s = sub.add_parser('sync', parents=[conn, out], help='scan and tag all ready torrents when the scan has no errors')
    s.add_argument('--scheduled', action='store_true',
                   help='background run: honour the failure pause and record the result for Schedule')
    au = sub.add_parser('auto', parents=[conn, out], help='keep syncing every N minutes until stopped (Ctrl+C)')
    au.add_argument('--interval', type=int, metavar='MIN', help='minutes between runs (default: saved interval)')
    au.add_argument('--runs', type=int, metavar='N', help='stop after N runs')

    ag = sub.add_parser('agent', help='real-time mode: listen for media server events and sync')
    action = ag.add_mutually_exclusive_group()
    action.add_argument('--stop', action='store_true', help='stop the running agent')
    action.add_argument('--run-now', action='store_true', help='ask the running agent to sync now')
    action.add_argument('--status', action='store_true', help='show whether the agent is running')

    sc = sub.add_parser('schedule', help='background runs through Windows Task Scheduler')
    ssub = sc.add_subparsers(dest='action', metavar='action', required=True)
    ssub.add_parser('show', help='show the schedule, next and last run', aliases=['status']).add_argument(
        '--json', action='store_true', help='print as JSON')
    st = ssub.add_parser('set', help='create or change the schedule')
    st.add_argument('mode', choices=[m for m in scheduler.MODES if m != 'off'],
                    help='interval: every X; daily/weekly: at set times; logon: at Windows sign-in; '
                         'realtime: listen for events')
    st.add_argument('--every', metavar='TIME', help='interval mode: 30, 30m, 2h, 1h30m or 1d')
    st.add_argument('--at', metavar='HH:MM', help='daily/weekly: one or more times, e.g. 03:00,15:00')
    st.add_argument('--days', metavar='LIST', help='weekly: Mon,Tue,... or weekdays, weekends, sun-thu, all')
    logon = st.add_mutually_exclusive_group()
    logon.add_argument('--at-logon', dest='at_logon', action='store_true', default=None,
                       help='interval/daily/weekly: also run when you sign in to Windows')
    logon.add_argument('--no-at-logon', dest='at_logon', action='store_false')
    st.add_argument('--fallback', metavar='MIN', help='realtime: full check every MIN minutes, 0 = events only')
    st.add_argument('--delay', metavar='SEC', help='realtime: seconds to wait after an event before syncing')
    st.add_argument('--max-failures', metavar='N', help='pause background runs after N consecutive failures, 0 = never')
    ssub.add_parser('off', help='remove the schedule and stop the real-time agent', aliases=['remove'])
    ssub.add_parser('run', help='start the scheduled run now', aliases=['run-now'])
    ssub.add_parser('resume', help='resume background runs paused after failures')

    cf = sub.add_parser('config', help='show or change saved settings')
    csub = cf.add_subparsers(dest='action', metavar='action', required=True)
    show = csub.add_parser('show', help='show saved settings (secrets hidden)')
    show.add_argument('--show-secrets', action='store_true', help='show tokens and passwords')
    show.add_argument('--json', action='store_true')
    cs = csub.add_parser('set', parents=[conn], help='save connection settings')
    cs.add_argument('--interval', metavar='MIN', help='auto sync interval in minutes')
    imp = csub.add_parser('import', help='import a config.json from the earlier version and save it')
    imp.add_argument('file')
    imp.add_argument('--remember', action='store_true', help='remember imported credentials (encrypted)')
    csub.add_parser('clear-credentials', help='remove remembered tokens and passwords')
    csub.add_parser('path', help='show where settings, reports and logs are stored')

    r = sub.add_parser('reports', help='show the automatic reports folder')
    r.add_argument('--open', action='store_true', help='open it in Explorer')
    r.add_argument('--list', type=int, nargs='?', const=10, metavar='N', help='list the newest N reports')
    lg = sub.add_parser('logs', help='show the background activity log')
    lg.add_argument('--tail', type=int, default=40, metavar='N', help='lines to show (default 40)')
    lg.add_argument('--follow', action='store_true', help='keep printing new lines')
    lg.add_argument('--open', action='store_true', help='open the log folder')
    sub.add_parser('status', help='same as: schedule show')
    sub.add_parser('guide', help='print the user guide')
    return p


def main(argv=None):
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name)
        if stream is None:  # Windowless executable started by Task Scheduler.
            setattr(sys, name, open(os.devnull, 'w'))
        elif hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(errors='replace')
            except Exception:
                pass
    args = parser().parse_args(argv)
    command = {'dry-run': 'scan'}.get(args.command, args.command)
    try:
        if command in (None, 'gui'):
            return open_gui()
        handler = globals()['cmd_' + command.replace('-', '_')]
        return handler(args) or runtime.OK
    except Exit as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print('Stopped. Tags already added remain.', file=sys.stderr)
        return runtime.CANCELLED


# ---------- settings ----------

def load_saved():
    try:
        return storage.load()
    except Exception:
        print('Warning: saved settings could not be unlocked; using defaults.', file=sys.stderr)
        return dict(storage.DEFAULTS)


def resolve(args):
    """Saved settings, then --config file, then WATCHBRIDGE_* variables, then flags."""
    values = load_saved()
    if getattr(args, 'config', None):
        values.update(read_config_file(args.config))
    for key, var in ENV.items():
        if os.environ.get(var):
            values[key] = os.environ[var]
    if getattr(args, 'media_server', None):
        values['media_server'] = args.media_server
    for flag, key, _, secret in CONNECTION:
        value = getattr(args, key, None)
        if value is None:
            continue
        if secret and value == '-':
            value = getpass.getpass(flag.lstrip('-').replace('-', ' ').capitalize() + ': ')
        values[key] = value
    if getattr(args, 'remember', None) is not None:
        values['remember'] = args.remember
    return values


def read_config_file(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise Exit('Could not read the JSON settings file: ' + str(path))
    if not isinstance(data, dict):
        raise Exit('The settings file must contain a JSON object.')
    values = {}
    for key in storage.DEFAULTS:
        if key not in storage.LOCAL_KEYS and isinstance(data.get(key), str):
            if key == 'media_server' and data[key] not in ('plex', 'jellyfin'):
                continue
            values[key] = data[key]
    return values


def connection(args):
    values = resolve(args)
    try:
        values = checked_config(values)
    except ValueError as exc:
        raise Exit(str(exc).replace('in Connections', 'with its option or in the window'))
    if getattr(args, 'save', False):
        save(values)
    return values


def save(values):
    if values.get('remember') and sys.platform != 'win32':
        raise Exit('Remembering credentials is supported on Windows only.')
    try:
        storage.save(values)
    except Exception as exc:
        raise Exit(public_error(exc), runtime.FAILED)
    print('Settings saved.' + ('' if values.get('remember') else ' Credentials were not remembered.'), file=sys.stderr)


# ---------- connection commands ----------

def make_emit(args):
    quiet = getattr(args, 'quiet', False)
    tty = sys.stderr.isatty()

    def emit(kind, data):
        if quiet:
            return
        if kind in ('log', 'phase'):
            print(('\r' + ' ' * 60 + '\r' if tty else '') + str(data), file=sys.stderr)
        elif kind == 'progress' and tty:
            print('\rChecked %s / %s torrents' % (format(data[0], ','), format(data[1], ',')),
                  end='', file=sys.stderr, flush=True)
    return emit


def cmd_test(args):
    values = connection(args)
    engine = SyncEngine(values, make_emit(args))
    try:
        profile, version = engine.connect()
    except Exception as exc:
        raise Exit(public_error(exc), runtime.FAILED)
    finally:
        engine.close()
    print('Both connections verified. Profile: %s. qBittorrent %s. Tag "%s" exists.' % (profile, version, values['tag']))


def locked():
    lock = runtime.RunLock()
    if not lock.acquire():
        raise Exit('Another WatchBridge run (window, schedule or real-time agent) is in progress. Try again shortly.',
                   runtime.BUSY)
    return lock


def cmd_scan(args):
    values = connection(args)
    lock = locked()
    engine = SyncEngine(values, make_emit(args))
    try:
        rows, excluded = engine.scan()
    except Cancelled:
        return runtime.CANCELLED
    except Exception as exc:
        raise Exit(public_error(exc), runtime.FAILED)
    finally:
        engine.close()
        lock.release()
    finish(args, rows, excluded, 'Dry Run complete. No tags changed.')
    return runtime.FAILED if any(r['status'] == 'ERROR' for r in rows) else runtime.OK


def cmd_apply(args):
    values = connection(args)
    hashes = {h.strip().lower() for item in args.hash for h in item.split(',') if h.strip()}
    names = [n.casefold() for n in args.name if n.strip()]
    lock = locked()
    engine = SyncEngine(values, make_emit(args))
    added = 0
    try:
        rows, excluded = engine.scan()
        if any(r['status'] == 'ERROR' for r in rows):
            finish(args, rows, excluded, 'The scan contains errors. Resolve them and scan again before tagging.')
            return runtime.FAILED
        chosen = [r for r in rows if r['status'] == 'READY' and (not (hashes or names) or r['hash'].lower() in hashes
                  or any(n in r['torrent'].casefold() for n in names))]
        if hashes or names:
            print('%s ready torrents match the selection.' % format(len(chosen), ','), file=sys.stderr)
        if chosen:
            added = engine.apply(chosen)
    except Cancelled:
        print('Stopped. Tags already added remain; scan again before retrying.', file=sys.stderr)
        return runtime.CANCELLED
    except Exception as exc:
        raise Exit(public_error(exc), runtime.FAILED)
    finally:
        engine.close()
        lock.release()
    finish(args, rows, excluded, 'Finished. Verified %s tag additions.' % format(added, ','))
    return runtime.OK


def cmd_sync(args):
    runtime.setup_logging(sys.stderr if args.scheduled and not args.quiet else None)
    try:
        values = connection(args)
    except Exit as exc:
        if args.scheduled:
            runtime.record_failure('schedule', str(exc), int(load_saved().get('max_failures') or 0))
        raise
    emit = make_emit(args) if not args.scheduled else None
    result, code, rows = runtime.run_sync(values, trigger='schedule' if args.scheduled else 'command line',
                                          emit=emit, background=args.scheduled, report=not args.no_report)
    if args.json:
        print(json.dumps(dict(result, rows=filtered(args, rows)), indent=2, ensure_ascii=False))
    elif rows:
        show_rows(args, rows)
    if args.csv and rows:
        export(argparse.Namespace(csv=args.csv, no_report=True), rows)
    if not args.json and (not args.scheduled or not args.quiet):
        print(result['message'])
    return code


def cmd_auto(args):
    values = connection(args)
    runtime.setup_logging()
    minutes = args.interval or int(values.get('interval') or 10)
    if minutes < 1:
        raise Exit('The interval must be at least 1 minute.')
    runs = 0
    print('Auto sync every %s minutes. Press Ctrl+C to stop. Errors stop auto sync.' % minutes, file=sys.stderr)
    while True:
        result, code, rows = runtime.run_sync(values, trigger='auto', emit=make_emit(args), background=False,
                                              report=not args.no_report)
        runs += 1
        print(time.strftime('%H:%M:%S') + '  ' + result['message'])
        if code not in (runtime.OK, runtime.BUSY):
            print('Auto sync stopped because of an error.', file=sys.stderr)
            return code
        if args.runs and runs >= args.runs:
            return runtime.OK
        time.sleep(minutes * 60)


def finish(args, rows, excluded, message):
    show_rows(args, rows)
    if not args.json:
        counts = {s: sum(r['status'] == s for r in rows) for s in STATUSES}
        print(' | '.join('%s %s' % (s.capitalize(), format(n, ',')) for s, n in counts.items())
              + ' | %s non-video excluded' % format(excluded, ','))
        print(message)
    export(args, rows)


def export(args, rows):
    if rows and not args.no_report:
        try:
            write_report(runtime.REPORTS / report_name(), rows)
        except OSError:
            print('Could not save the automatic report.', file=sys.stderr)
    if args.csv:
        try:
            write_report(args.csv, rows)
            print('Exported all video results to ' + args.csv, file=sys.stderr)
        except OSError:
            raise Exit('Could not save the CSV file. Choose a writable folder.', runtime.FAILED)


def wanted_statuses(text):
    if not text:
        return set(STATUSES)
    chosen = {s.strip().upper() for s in text.split(',') if s.strip()}
    unknown = chosen - set(STATUSES)
    if unknown:
        raise Exit('Unknown status: ' + ', '.join(sorted(unknown)).lower())
    return chosen


def filtered(args, rows):
    statuses = wanted_statuses(args.status)
    term = (args.search or '').casefold().strip()
    return [r for r in rows if r['status'] in statuses
            and (not term or term in (r['torrent'] + ' ' + r.get('unmatched_paths', '')).casefold())]


def show_rows(args, rows):
    shown = filtered(args, rows)
    if args.json:
        print(json.dumps(shown, indent=2, ensure_ascii=False))
        return
    if args.quiet and not (args.status or args.search):
        return
    for r in shown:
        count = '%s/%s' % (r['watched_files'], r['video_files']) if r['video_files'] != '' else '?'
        print('%-11s %7s  %s' % (r['status'].capitalize(), count, r['torrent']))
        if args.details:
            print('            hash ' + r['hash'])
            for path in filter(None, r.get('unmatched_paths', '').split(' | ')):
                print('            unmatched: ' + path)
            if r.get('error'):
                print('            error: ' + r['error'])


# ---------- agent and schedule ----------

def cmd_agent(args):
    import agent
    if args.status:
        print('Real-time agent: ' + ('running' if agent.agent_running() else 'not running'))
        return runtime.OK
    if args.stop:
        if agent.request_stop():
            print('Real-time agent stopped.')
            return runtime.OK
        scheduler.end()
        print('The agent did not respond; Task Scheduler was asked to end it.')
        return runtime.OK
    if args.run_now:
        if not agent.agent_running():
            raise Exit('The real-time agent is not running.', runtime.FAILED)
        agent.request_run()
        print('The agent will sync within a few seconds.')
        return runtime.OK
    runtime.setup_logging(sys.stderr)
    stop = threading.Event()
    try:
        return agent.run(stop)
    except KeyboardInterrupt:
        stop.set()
        return runtime.OK


def cmd_status(args):
    args.json = False
    return schedule_show(args)


def cmd_schedule(args):
    action = {'status': 'show', 'remove': 'off', 'run-now': 'run'}.get(args.action, args.action)
    return {'show': schedule_show, 'set': schedule_set, 'off': schedule_off,
            'run': schedule_run, 'resume': schedule_resume}[action](args)


def schedule_show(args):
    import agent
    info = agent.status(load_saved())
    if getattr(args, 'json', False):
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print('\n'.join(agent.status_lines(info)))
        if info['paused']:
            print('Resume with: schedule resume')
    return runtime.OK


def schedule_set(args):
    values = load_saved()
    updates = {'schedule_mode': args.mode, 'schedule_every': args.every, 'schedule_times': args.at,
               'schedule_days': args.days, 'schedule_at_logon': args.at_logon, 'realtime_fallback': args.fallback,
               'realtime_delay': args.delay, 'max_failures': args.max_failures}
    values.update({k: v for k, v in updates.items() if v is not None})
    if args.mode == 'weekly' and args.days is None and values.get('schedule_days') == storage.DEFAULTS['schedule_days']:
        print('Note: no --days given; running every day of the week.', file=sys.stderr)
    return configure(values)


def configure(values):
    import agent
    try:
        print(agent.configure(values))
    except ValueError as exc:
        raise Exit(str(exc))
    except Exception as exc:
        raise Exit(public_error(exc), runtime.FAILED)
    return runtime.OK


def schedule_off(args):
    values = load_saved()
    values['schedule_mode'] = 'off'
    return configure(values)


def schedule_run(args):
    import agent
    try:
        print(agent.run_now())
    except (ValueError, RuntimeError) as exc:
        raise Exit(str(exc), runtime.FAILED)
    return runtime.OK


def schedule_resume(args):
    runtime.resume()
    print('Background runs resumed.')
    return runtime.OK


# ---------- config, reports, logs ----------

def cmd_config(args):
    if args.action == 'show':
        values = load_saved()
        shown = {k: (v if args.show_secrets or k not in storage.SECRETS else ('********' if v else ''))
                 for k, v in values.items()}
        if args.json:
            print(json.dumps(shown, indent=2, ensure_ascii=False))
        else:
            for key, value in shown.items():
                print('%-18s %s' % (key, value))
        return runtime.OK
    if args.action == 'set':
        values = resolve(args)
        if args.interval is not None:
            values['interval'] = str(scheduler.number(args.interval, 'Interval', 1, 1440))
        try:
            values = checked_config(values)
        except ValueError as exc:
            print('Warning: ' + str(exc), file=sys.stderr)
        save(values)
        return runtime.OK
    if args.action == 'import':
        values = load_saved()
        values.update(read_config_file(args.file))
        values['remember'] = bool(args.remember) or values.get('remember', False)
        save(values)
        print('Imported connection details from ' + args.file)
        return runtime.OK
    if args.action == 'clear-credentials':
        values = load_saved()
        values['remember'] = False
        save(values)
        return runtime.OK
    print('Settings: ' + str(storage.APP_DIR / 'settings.json'))
    print('Reports:  ' + str(runtime.REPORTS))
    print('Logs:     ' + str(runtime.LOG_FILE.parent))
    return runtime.OK


def cmd_reports(args):
    runtime.REPORTS.mkdir(parents=True, exist_ok=True)
    print(runtime.REPORTS)
    if args.list:
        for path in sorted(runtime.REPORTS.glob('*.csv'), reverse=True)[:args.list]:
            print('  ' + path.name)
    if args.open:
        open_folder(runtime.REPORTS)
    return runtime.OK


def cmd_logs(args):
    if args.open:
        runtime.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        open_folder(runtime.LOG_FILE.parent)
        return runtime.OK
    if not runtime.LOG_FILE.exists():
        print('No background activity has been logged yet.')
        return runtime.OK
    lines = runtime.LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()
    print('\n'.join(lines[-args.tail:]) if args.tail > 0 else '')
    if args.follow:
        with open(runtime.LOG_FILE, encoding='utf-8', errors='replace') as stream:
            stream.seek(0, os.SEEK_END)
            while True:
                line = stream.readline()
                if line:
                    print(line, end='', flush=True)
                else:
                    time.sleep(1)
    return runtime.OK


def cmd_guide(args):
    from helptext import GUIDE
    print(GUIDE)
    return runtime.OK


def open_folder(path):
    if sys.platform == 'win32':
        os.startfile(str(path))
    else:
        subprocess.run(['xdg-open', str(path)], check=False)


def open_gui():
    try:
        from watchbridge import start_gui
    except ImportError:
        # The console build does not bundle the window; start the windowed executable beside it.
        exe = Path(sys.executable).with_name('WatchBridge.exe')
        if getattr(sys, 'frozen', False) and exe.exists():
            subprocess.Popen([str(exe)])
            return runtime.OK
        raise Exit('The desktop window is not available in this build.', runtime.FAILED)
    return start_gui()


if __name__ == '__main__':
    sys.exit(main())
