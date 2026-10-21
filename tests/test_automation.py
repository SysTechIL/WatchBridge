import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
import cli
import engine
import runtime
import scheduler
import settings

NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def config(**kw):
    return dict(settings.DEFAULTS, plex_token='fake-token', qb_username='test', qb_password='fake-password', **kw)


def row(status, name='Show.S01', hash_='h1'):
    return {'status': status, 'torrent': name, 'hash': hash_, 'watched_files': 1, 'video_files': 1,
            'unmatched_paths': '', 'error': ''}


class TempAppDir(unittest.TestCase):
    """Redirect settings, state, locks, logs and reports into a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.dir = d
        paths = {'LOG_FILE': d / 'logs' / 'watchbridge.log', 'STATE_FILE': d / 'schedule-state.json',
                 'RUN_LOCK': d / 'run.lock', 'AGENT_LOCK': d / 'agent.lock', 'AGENT_STOP': d / 'agent.stop',
                 'AGENT_POKE': d / 'agent.poke', 'REPORTS': d / 'reports'}
        self.patches = [patch.object(settings, 'APP_DIR', d)] + [patch.object(runtime, k, v) for k, v in paths.items()]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for handler in list(runtime.log.handlers):
            runtime.log.removeHandler(handler)
            handler.close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class FakeEngine:
    """Stands in for SyncEngine; class attributes choose the behaviour."""
    rows = [row('READY')]
    fail = None
    applied = []

    def __init__(self, settings_, emit=None, cancel=None):
        self.settings = settings_

    def connect(self):
        return 'Viewer', 'v5.0.0'

    def scan(self):
        if self.fail:
            raise self.fail
        return [dict(r) for r in self.rows], 2

    def apply(self, rows):
        FakeEngine.applied = [r['hash'] for r in rows if r['status'] == 'READY']
        for r in rows:
            if r['status'] == 'READY':
                r['status'] = 'TAGGED'
        return len(FakeEngine.applied)

    def close(self):
        pass


class SchedulerTests(unittest.TestCase):
    def test_every(self):
        for text, minutes in (('30', 30), ('30m', 30), ('2h', 120), ('1h30m', 90), ('1d', 1440), ('45 min', 45)):
            self.assertEqual(scheduler.parse_every(text), minutes)
        for text in ('', '0', 'abc', '32d', '-5'):
            with self.assertRaises(ValueError):
                scheduler.parse_every(text)

    def test_times(self):
        self.assertEqual(scheduler.parse_times('15:30, 3:00,15:30'), ['03:00', '15:30'])
        for text in ('', '24:00', '3', '12:60'):
            with self.assertRaises(ValueError):
                scheduler.parse_times(text)

    def test_days(self):
        self.assertEqual(scheduler.parse_days('fri,mon'), ['Mon', 'Fri'])
        self.assertEqual(scheduler.parse_days('weekdays'), list(scheduler.DAYS[:5]))
        self.assertEqual(scheduler.parse_days('sun-thu'), ['Mon', 'Tue', 'Wed', 'Thu', 'Sun'])
        self.assertEqual(scheduler.parse_days('Saturday'), ['Sat'])
        for text in ('', 't', 'xyz'):
            with self.assertRaises(ValueError):
                scheduler.parse_days(text)

    def test_normalize_and_describe(self):
        with self.assertRaises(ValueError):
            scheduler.normalize({'schedule_mode': 'hourly'})
        values = scheduler.normalize({'schedule_mode': 'interval', 'schedule_every': '2h', 'schedule_at_logon': 'yes'})
        self.assertEqual((values['schedule_every'], values['schedule_at_logon']), ('120', True))
        self.assertEqual(scheduler.describe(values), 'Every 2 hours, and when you sign in to Windows.')
        self.assertEqual(scheduler.describe({'schedule_mode': 'interval', 'schedule_every': '60'}), 'Every hour.')
        self.assertIn('Real time', scheduler.describe({'schedule_mode': 'realtime'}))

    def xml(self, **values):
        with patch.object(scheduler, 'current_user', return_value='PC\\Tester'):
            text = scheduler.build_xml(values, now=datetime(2026, 10, 21, 20, 15, 42))
        return ET.fromstring(text.split('\n', 1)[1])

    def test_interval_xml(self):
        root = self.xml(schedule_mode='interval', schedule_every='30m')
        trigger = root.find('t:Triggers/t:TimeTrigger', NS)
        self.assertEqual(trigger.find('t:StartBoundary', NS).text, '2026-10-21T20:16:00')
        self.assertEqual(trigger.find('t:Repetition/t:Interval', NS).text, 'PT30M')
        self.assertIsNone(root.find('t:Triggers/t:LogonTrigger', NS))
        self.assertIn('sync --scheduled', root.find('t:Actions/t:Exec/t:Arguments', NS).text)
        self.assertEqual(root.find('t:Principals/t:Principal/t:LogonType', NS).text, 'InteractiveToken')
        self.assertEqual(root.find('t:Settings/t:MultipleInstancesPolicy', NS).text, 'IgnoreNew')

    def test_daily_xml_moves_past_times_to_tomorrow(self):
        root = self.xml(schedule_mode='daily', schedule_times='03:00,21:00', schedule_at_logon=True)
        starts = [t.find('t:StartBoundary', NS).text for t in root.findall('t:Triggers/t:CalendarTrigger', NS)]
        self.assertEqual(starts, ['2026-10-22T03:00:00', '2026-10-21T21:00:00'])
        self.assertEqual(root.find('t:Triggers/t:LogonTrigger/t:UserId', NS).text, 'PC\\Tester')

    def test_weekly_xml(self):
        root = self.xml(schedule_mode='weekly', schedule_days='mon,fri', schedule_times='08:00')
        days = root.find('t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek', NS)
        self.assertEqual([e.tag.split('}')[1] for e in days], ['Monday', 'Friday'])

    def test_realtime_xml(self):
        root = self.xml(schedule_mode='realtime')
        self.assertIsNotNone(root.find('t:Triggers/t:LogonTrigger', NS))
        self.assertTrue(root.find('t:Actions/t:Exec/t:Arguments', NS).text.endswith('agent'))
        self.assertEqual(root.find('t:Settings/t:ExecutionTimeLimit', NS).text, 'PT0S')
        self.assertIsNotNone(root.find('t:Settings/t:RestartOnFailure', NS))
        with self.assertRaises(ValueError):
            self.xml(schedule_mode='off')

    def test_source_launch_uses_windowless_python(self):
        with tempfile.TemporaryDirectory() as d:
            python = Path(d) / 'python.exe'
            python.write_text('')
            (Path(d) / 'pythonw.exe').write_text('')
            with patch.object(sys, 'executable', str(python)):
                command, arguments, workdir = scheduler.launch_command('agent')
        self.assertTrue(command.endswith('pythonw.exe'))
        self.assertTrue(arguments.endswith('watchbridge.py" agent') or arguments.endswith('watchbridge.py agent'))
        self.assertEqual(Path(workdir), Path(scheduler.__file__).resolve().parent)

    def test_query_parses_schtasks_csv(self):
        out = ('"PC","\\WatchBridge (Tester)","22/10/2026 03:00:00","Ready","Interactive only",'
               '"30/11/1999 00:00:00","267011","N/A"\n')
        with patch.object(scheduler, '_schtasks', return_value=(0, out)):
            info = scheduler.query()
        self.assertEqual((info['next_run'], info['status'], info['last_run']), ('22/10/2026 03:00:00', 'Ready', ''))
        with patch.object(scheduler, '_schtasks', return_value=(1, '')):
            self.assertEqual(scheduler.query(), {'exists': False})


class RuntimeTests(TempAppDir):
    def test_lock_is_exclusive(self):
        first, second = runtime.RunLock(), runtime.RunLock()
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertTrue(second.held_elsewhere())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_failures_pause_and_resume(self):
        for _ in range(2):
            runtime.record({'outcome': 'failed'}, 3)
        self.assertFalse(runtime.read_state().get('paused'))
        runtime.record({'outcome': 'errors'}, 3)
        self.assertTrue(runtime.read_state()['paused'])
        runtime.resume()
        self.assertEqual((runtime.read_state()['paused'], runtime.read_state()['failures']), (False, 0))
        runtime.record({'outcome': 'failed'}, 0)
        runtime.record({'outcome': 'ok'}, 0)
        self.assertEqual(runtime.read_state()['failures'], 0)

    def run_sync(self, **kw):
        with patch.object(runtime, 'SyncEngine', FakeEngine):
            return runtime.run_sync(config(), **kw)

    def test_sync_tags_ready_and_records(self):
        FakeEngine.rows, FakeEngine.fail = [row('READY'), row('UNWATCHED', hash_='h2')], None
        result, code, rows = self.run_sync(trigger='schedule')
        self.assertEqual((code, result['outcome'], result['added'], result['excluded']), (0, 'ok', 1, 2))
        self.assertEqual(rows[0]['status'], 'TAGGED')
        self.assertTrue(Path(result['report']).exists())
        self.assertEqual(runtime.read_state()['last_run']['trigger'], 'schedule')

    def test_scan_errors_block_tagging(self):
        FakeEngine.rows, FakeEngine.fail, FakeEngine.applied = [row('READY'), row('ERROR', hash_='h2')], None, []
        result, code, _ = self.run_sync()
        self.assertEqual((code, result['outcome'], FakeEngine.applied), (runtime.FAILED, 'errors', []))
        self.assertEqual(runtime.read_state()['failures'], 1)

    def test_failure_message_is_public(self):
        FakeEngine.fail = ConnectionError('http://host/?X-Plex-Token=secret')
        try:
            result, code, _ = self.run_sync()
        finally:
            FakeEngine.fail = None
        self.assertEqual(code, runtime.FAILED)
        self.assertNotIn('secret', result['message'])

    def test_busy_and_paused_skip(self):
        lock = runtime.RunLock()
        lock.acquire()
        try:
            self.assertEqual(self.run_sync()[1], runtime.BUSY)
        finally:
            lock.release()
        runtime.write_state({'paused': True})
        self.assertEqual(self.run_sync()[1], runtime.PAUSED)
        self.assertEqual(self.run_sync(background=False)[1], runtime.OK)


class AgentTests(TempAppDir):
    def test_debouncer(self):
        now = [0.0]
        d = agent.Debouncer(30, 60, clock=lambda: now[0])
        self.assertIsNone(d.due())
        d.poke('event')
        now[0] = 29
        self.assertIsNone(d.due())
        now[0] = 30
        self.assertEqual(d.due(), 'event')
        d.ran()
        now[0] = 30 + 3599
        self.assertIsNone(d.due())
        now[0] = 30 + 3600
        self.assertEqual(d.due(), 'fallback check')

    def test_debouncer_caps_waiting_on_steady_events(self):
        now = [0.0]
        d = agent.Debouncer(10, 0, clock=lambda: now[0])
        for t in range(0, 60, 5):
            now[0] = t
            d.poke('event')
        now[0] = 50
        self.assertEqual(d.due(), 'event')
        d.ran()
        d.poke('now', delay=0)
        self.assertEqual(d.due(), 'now')

    def test_plex_events(self):
        stopped = {'NotificationContainer': {'type': 'playing', 'PlaySessionStateNotification': [{'state': 'stopped'}]}}
        playing = {'NotificationContainer': {'type': 'playing', 'PlaySessionStateNotification': [{'state': 'playing'}]}}
        updated = {'NotificationContainer': {'type': 'timeline', 'TimelineEntry': [{'type': 4, 'state': 5}]}}
        scanning = {'NotificationContainer': {'type': 'timeline', 'TimelineEntry': [{'type': 4, 'state': 0}]}}
        self.assertTrue(agent.plex_trigger(stopped))
        self.assertTrue(agent.plex_trigger(updated))
        self.assertIsNone(agent.plex_trigger(playing))
        self.assertIsNone(agent.plex_trigger(scanning))
        self.assertIsNone(agent.plex_trigger({'NotificationContainer': {'type': 'activity'}}))

    def test_jellyfin_events(self):
        state = agent.JellyfinState('ABCD-1234')
        self.assertTrue(state.trigger({'MessageType': 'UserDataChanged', 'Data': {'UserId': 'abcd1234'}}))
        self.assertIsNone(state.trigger({'MessageType': 'UserDataChanged', 'Data': {'UserId': 'other'}}))
        mine = {'Id': 's1', 'UserId': 'abcd1234', 'NowPlayingItem': {'Id': 'x'}}
        other = {'Id': 's2', 'UserId': 'other', 'NowPlayingItem': {'Id': 'y'}}
        self.assertIsNone(state.trigger({'MessageType': 'Sessions', 'Data': [mine, other]}))
        self.assertIsNone(state.trigger({'MessageType': 'Sessions', 'Data': [mine]}))
        self.assertTrue(state.trigger({'MessageType': 'Sessions', 'Data': [dict(mine, NowPlayingItem=None)]}))
        self.assertIsNone(state.trigger({'MessageType': 'KeepAlive'}))

    def test_websocket_url(self):
        self.assertEqual(agent.websocket_url('https://nas.local:8920/jf', '/socket', {'api_key': 'k'}),
                         'wss://nas.local:8920/jf/socket?api_key=k')
        self.assertEqual(agent.websocket_url('http://localhost:32400', '/:/websockets/notifications', {}),
                         'ws://localhost:32400/:/websockets/notifications')

    def test_agent_loop_syncs_and_stops(self):
        calls = []

        class Listener:
            def __init__(self, values, poke, stop):
                self.poke = poke
            def start(self):
                self.poke('Plex playback stopped', delay=0)

        def fake_sync(values, trigger, cancel=None, **kw):
            calls.append(trigger)
            if len(calls) == 1:
                runtime.AGENT_POKE.write_text('run')
            else:
                runtime.AGENT_STOP.write_text('stop')
            return {}, runtime.OK, []

        values = config(schedule_mode='realtime', realtime_delay='5')
        with patch.object(agent.storage, 'load', return_value=values), patch.object(agent, 'Listener', Listener), \
                patch.object(agent.runtime, 'run_sync', fake_sync):
            thread = threading.Thread(target=agent.run, kwargs={'poll': 0.01})
            thread.start()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        # Events arriving during the start-up delay are handled by that first sync.
        self.assertEqual(calls, ['startup', 'run requested'])
        self.assertFalse(agent.agent_running())

    def test_agent_exits_when_mode_changes(self):
        with patch.object(agent.storage, 'load', return_value=config(schedule_mode='interval')):
            self.assertEqual(agent.run(poll=0.01), runtime.OK)

    def test_configure_requires_remembered_credentials(self):
        with self.assertRaises(ValueError):
            agent.configure(config(schedule_mode='interval', remember=False))
        with self.assertRaises(ValueError):
            agent.configure(config(schedule_mode='daily', schedule_times='25:00', remember=True))

    def test_configure_registers_and_removes(self):
        calls = []
        with patch.object(agent.storage, 'save', lambda v: calls.append(('save', v['schedule_mode']))), \
                patch.object(scheduler, 'install', lambda v: calls.append('install')), \
                patch.object(scheduler, 'remove', lambda: calls.append('remove')), \
                patch.object(scheduler, 'run_now', lambda: calls.append('run')):
            text = agent.configure(config(schedule_mode='realtime', remember=True))
            agent.configure(config(schedule_mode='off'))
        self.assertIn('Real time', text)
        self.assertEqual(calls, [('save', 'realtime'), 'install', 'run', ('save', 'off'), 'remove'])


class CliTests(TempAppDir):
    def run_cli(self, *argv, engine_cls=FakeEngine, saved=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(cli, 'SyncEngine', engine_cls), patch.object(runtime, 'SyncEngine', engine_cls), \
                patch.object(cli.storage, 'load', return_value=dict(saved or config())), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_every_gui_action_has_a_command(self):
        commands = set(cli.parser()._subparsers._group_actions[0].choices)
        self.assertTrue({'gui', 'test', 'scan', 'apply', 'sync', 'auto', 'agent', 'schedule', 'config', 'reports',
                         'logs', 'guide'} <= commands)

    def test_precedence(self):
        path = self.dir / 'old.json'
        path.write_text(json.dumps({'qb_url': 'http://file:1', 'qb_password': 'from-file', 'remember': True}))
        args = cli.parser().parse_args(['scan', '--config', str(path), '--qb-password', 'from-flag',
                                        '--server', 'jellyfin'])
        with patch.object(cli.storage, 'load', return_value=config(qb_url='http://saved:1')), \
                patch.dict('os.environ', {'WATCHBRIDGE_QB_PASSWORD': 'from-env', 'WATCHBRIDGE_PLEX_TOKEN': 'env-tok'}):
            values = cli.resolve(args)
        self.assertEqual((values['qb_url'], values['qb_password'], values['plex_token'], values['media_server']),
                         ('http://file:1', 'from-flag', 'env-tok', 'jellyfin'))
        self.assertFalse(values['remember'])

    def test_secret_prompt(self):
        args = cli.parser().parse_args(['test', '--qb-password', '-'])
        with patch.object(cli.storage, 'load', return_value=config()), \
                patch.object(cli.getpass, 'getpass', return_value='typed'):
            self.assertEqual(cli.resolve(args)['qb_password'], 'typed')

    def test_scan_filters_and_exports(self):
        FakeEngine.rows = [row('READY', 'Alpha', 'h1'), row('UNMATCHED', 'Beta', 'h2')]
        csv_path = self.dir / 'out.csv'
        code, out, _ = self.run_cli('scan', '--status', 'unmatched', '--csv', str(csv_path))
        self.assertEqual(code, 0)
        self.assertIn('Beta', out)
        self.assertNotIn('Alpha', out)
        self.assertIn('Ready 1 | Tagged 0', out)
        self.assertEqual(len(csv_path.read_text(encoding='utf-8-sig').splitlines()), 3)
        self.assertEqual(len(list(runtime.REPORTS.glob('*.csv'))), 1)
        code, out, _ = self.run_cli('dry-run', '--json', '--search', 'alp', '--no-report')
        self.assertEqual([r['torrent'] for r in json.loads(out)], ['Alpha'])
        self.assertEqual(self.run_cli('scan', '--status', 'bogus')[0], runtime.USAGE)

    def test_scan_errors_exit_code(self):
        FakeEngine.rows = [row('ERROR')]
        self.assertEqual(self.run_cli('scan', '-q')[0], runtime.FAILED)

    def test_apply_selection(self):
        FakeEngine.rows = [row('READY', 'Alpha', 'h1'), row('READY', 'Beta', 'h2'), row('READY', 'Gamma', 'h3')]
        code, out, _ = self.run_cli('apply', '--name', 'beta', '--hash', 'H3', '-q')
        self.assertEqual((code, sorted(FakeEngine.applied)), (0, ['h2', 'h3']))
        self.assertIn('Verified 2 tag additions', out)
        self.run_cli('apply', '-q')
        self.assertEqual(sorted(FakeEngine.applied), ['h1', 'h2', 'h3'])

    def test_apply_refuses_scan_errors(self):
        FakeEngine.rows, FakeEngine.applied = [row('READY'), row('ERROR', hash_='h2')], []
        self.assertEqual(self.run_cli('apply', '-q')[0], runtime.FAILED)
        self.assertEqual(FakeEngine.applied, [])

    def test_invalid_connection_is_usage_error(self):
        code, _, err = self.run_cli('scan', saved=dict(settings.DEFAULTS))
        self.assertEqual(code, runtime.USAGE)
        self.assertIn('Plex token', err)

    def test_scheduled_sync_records_missing_settings(self):
        code, _, _ = self.run_cli('sync', '--scheduled', '-q', saved=dict(settings.DEFAULTS))
        self.assertEqual(code, runtime.USAGE)
        self.assertEqual(runtime.read_state()['last_run']['outcome'], 'failed')

    def test_scheduled_sync_json(self):
        FakeEngine.rows = [row('READY')]
        code, out, _ = self.run_cli('sync', '--scheduled', '--json', '-q', '--no-report')
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual((result['outcome'], result['rows'][0]['status']), ('ok', 'TAGGED'))
        self.assertTrue(runtime.LOG_FILE.exists())

    def test_schedule_set_needs_remembered_credentials(self):
        code, _, err = self.run_cli('schedule', 'set', 'interval', '--every', '30m')
        self.assertEqual(code, runtime.USAGE)
        self.assertIn('remembered credentials', err)

    def test_schedule_set_passes_options(self):
        seen = {}
        with patch.object(agent, 'configure', lambda v: seen.update(v) or 'described'):
            code, out, _ = self.run_cli('schedule', 'set', 'weekly', '--days', 'sun-thu', '--at', '22:30',
                                        '--at-logon', '--max-failures', '0', saved=config(remember=True))
        self.assertEqual((code, out.strip()), (0, 'described'))
        self.assertEqual((seen['schedule_mode'], seen['schedule_days'], seen['schedule_times'],
                          seen['schedule_at_logon'], seen['max_failures']), ('weekly', 'sun-thu', '22:30', True, '0'))

    def test_config_show_hides_secrets(self):
        code, out, _ = self.run_cli('config', 'show')
        self.assertNotIn('fake-password', out)
        self.assertIn('********', out)
        self.assertIn('fake-password', self.run_cli('config', 'show', '--show-secrets')[1])

    def test_config_set_saves(self):
        saved = {}
        with patch.object(cli.storage, 'save', lambda v: saved.update(v)):
            code, _, _ = self.run_cli('config', 'set', '--qb-url', 'http://nas:8080', '--tag', 'Seen', '--interval', '15')
        self.assertEqual((code, saved['qb_url'], saved['tag'], saved['interval']), (0, 'http://nas:8080', 'Seen', '15'))

    def test_engine_version_matches(self):
        self.assertIn(engine.__version__, cli.parser().format_help())


if __name__ == '__main__':
    unittest.main()
