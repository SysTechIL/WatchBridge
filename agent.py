"""Real-time mode: listen for Plex or Jellyfin playback and watched-state events, then sync.

A full check also runs on a fallback interval, so a missed event only delays tagging.
"""
import json
import os
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from engine import SyncEngine, checked_config, public_error
import runtime
import settings as storage

log = runtime.log
MAX_WAIT = 5  # A steady stream of events delays a sync by at most this many event delays.


class Debouncer:
    """Decide when to sync: shortly after the last event, or when the fallback interval has passed."""

    def __init__(self, delay, fallback_minutes, clock=time.monotonic):
        self.delay, self.fallback, self.clock = delay, fallback_minutes * 60, clock
        self.first = self.last = None
        self.reason = None
        self.next_full = None

    def poke(self, reason, delay=None):
        now = self.clock()
        if self.first is None:
            self.first, self.reason = now, reason
        self.last = now if delay is None else now - self.delay + delay

    def due(self):
        now = self.clock()
        if self.last is not None and (now - self.last >= self.delay or now - self.first >= self.delay * MAX_WAIT):
            return self.reason
        if self.fallback and self.next_full is not None and now >= self.next_full:
            return 'fallback check'
        return None

    def ran(self):
        self.first = self.last = self.reason = None
        self.next_full = self.clock() + self.fallback if self.fallback else None

    def retry(self, seconds):
        self.first = self.last = None
        self.next_full = self.clock() + seconds


def plex_trigger(message):
    """Return a reason when a Plex notification can change watched state."""
    data = message.get('NotificationContainer', message) if isinstance(message, dict) else {}
    kind = data.get('type')
    if kind == 'playing':
        if any(n.get('state') == 'stopped' for n in data.get('PlaySessionStateNotification') or []):
            return 'Plex playback stopped'
    elif kind == 'timeline':
        # state 5 = item processed; types 1 and 4 are movies and episodes, which includes watched toggles.
        if any(str(e.get('type')) in ('1', '4') and str(e.get('state')) == '5' and e.get('metadataState') is None
               for e in data.get('TimelineEntry') or []):
            return 'Plex library item updated'
    return None


def same_id(a, b):
    return str(a or '').replace('-', '').lower() == str(b or '').replace('-', '').lower() != ''


class JellyfinState:
    """Track one user's playing sessions to notice when playback stops."""

    def __init__(self, user_id):
        self.user_id = user_id
        self.playing = set()

    def trigger(self, message):
        kind = message.get('MessageType') if isinstance(message, dict) else None
        data = message.get('Data')
        if kind == 'UserDataChanged' and isinstance(data, dict) and same_id(data.get('UserId'), self.user_id):
            return 'Jellyfin watched state changed'
        if kind == 'Sessions' and isinstance(data, list):
            playing = {s.get('Id') for s in data if isinstance(s, dict) and same_id(s.get('UserId'), self.user_id)
                       and s.get('NowPlayingItem')}
            stopped = self.playing - playing
            self.playing = playing
            if stopped:
                return 'Jellyfin playback stopped'
        if kind in ('PlaybackStopped', 'PlaybackStop'):
            return 'Jellyfin playback stopped'
        return None


def websocket_url(base, path, query):
    parts = urlsplit(base)
    scheme = 'wss' if parts.scheme == 'https' else 'ws'
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip('/') + path, urlencode(query), ''))


class Listener(threading.Thread):
    """Keep one websocket open, reconnecting with backoff, and report events through poke()."""

    def __init__(self, values, poke, stop):
        super().__init__(daemon=True, name='watchbridge-events')
        self.values, self.poke, self.stop = values, poke, stop
        self.connected = False

    def run(self):
        try:
            import websocket
        except ImportError:
            log.warning('Real-time events are unavailable (websocket-client is missing). Using the fallback interval only.')
            return
        backoff = 5
        while not self.stop.is_set():
            ws = None
            try:
                ws, handle, keepalive = self.open(websocket)
                self.connected, backoff = True, 5
                log.info('Listening for %s events.', 'Jellyfin' if self.jellyfin else 'Plex')
                last_ping = time.monotonic()
                while not self.stop.is_set():
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        raw = None
                    if raw:
                        try:
                            message = json.loads(raw)
                        except ValueError:
                            message = None
                        if isinstance(message, dict):
                            keepalive = self.keepalive(message, keepalive)
                            reason = handle(message)
                            if reason:
                                log.info('Event: %s.', reason)
                                self.poke(reason)
                    elif raw == '':
                        raise ConnectionError('closed')
                    if time.monotonic() - last_ping >= keepalive:
                        if self.jellyfin:
                            ws.send(json.dumps({'MessageType': 'KeepAlive'}))
                        else:
                            ws.ping()
                        last_ping = time.monotonic()
            except Exception as exc:
                if not self.stop.is_set():
                    log.warning('Event connection lost (%s). Retrying in %s seconds.', public_error(exc), backoff)
            finally:
                self.connected = False
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:
                        pass
            self.stop.wait(backoff)
            backoff = min(backoff * 2, 300)

    @property
    def jellyfin(self):
        return self.values.get('media_server') == 'jellyfin'

    def open(self, websocket):
        if self.jellyfin:
            engine = SyncEngine(self.values)
            try:
                engine.connect_jellyfin()
                token, user_id = engine.jf_token, engine.jf_user_id
            finally:
                engine.close()
            url = websocket_url(self.values['jf_url'], '/socket', {'api_key': token, 'deviceId': 'watchbridge-agent'})
            ws = websocket.create_connection(url, timeout=5)
            ws.send(json.dumps({'MessageType': 'SessionsStart', 'Data': '0,1500'}))
            return ws, JellyfinState(user_id).trigger, 30
        url = websocket_url(self.values['plex_url'], '/:/websockets/notifications',
                            {'X-Plex-Token': self.values['plex_token'].strip()})
        return websocket.create_connection(url, timeout=5), plex_trigger, 30

    def keepalive(self, message, current):
        if message.get('MessageType') == 'ForceKeepAlive':
            try:
                return max(5, int(message.get('Data')) / 2)
            except (TypeError, ValueError):
                pass
        return current


def connection_signature(values):
    return tuple(values.get(k) for k in sorted(storage.DEFAULTS) if k not in storage.LOCAL_KEYS)


def agent_running():
    return runtime.RunLock(runtime.AGENT_LOCK).held_elsewhere()


def request_stop(wait=15):
    """Ask a running agent to stop; returns True when it has stopped."""
    if not agent_running():
        return True
    runtime.AGENT_STOP.parent.mkdir(parents=True, exist_ok=True)
    runtime.AGENT_STOP.write_text('stop', encoding='utf-8')
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not agent_running():
            return True
        time.sleep(0.5)
    return False


def request_run():
    runtime.AGENT_POKE.parent.mkdir(parents=True, exist_ok=True)
    runtime.AGENT_POKE.write_text('run', encoding='utf-8')


def configure(values):
    """Validate, save and register the background schedule. Returns its description.

    Raises ValueError for invalid input and RuntimeError when Windows refuses the change.
    """
    import scheduler
    values.update(scheduler.normalize(values))
    mode = values['schedule_mode']
    if mode != 'off':
        values.update(checked_config(values))
        if not values.get('remember'):
            raise ValueError('Background runs need remembered credentials. Turn on "Remember credentials" in '
                             'Connections, or run: WatchBridgeCLI config set --remember, then try again.')
    storage.save(values)
    if not request_stop():
        scheduler.end()
    if mode == 'off':
        scheduler.remove()
    else:
        scheduler.install(values)
        runtime.resume()
        if mode == 'realtime':
            scheduler.run_now()
    return scheduler.describe(values)


def status(values):
    """Schedule, Task Scheduler and last-run details for the Schedule page and the command line."""
    import scheduler
    state = runtime.read_state()
    try:
        task = scheduler.query()
    except RuntimeError as exc:
        task = {'exists': False, 'error': str(exc)}
    try:
        summary = scheduler.describe(values)
    except ValueError as exc:
        summary = 'Invalid schedule: ' + str(exc)
    return {'mode': values.get('schedule_mode', 'off'), 'description': summary, 'task_name': scheduler.task_name(),
            'task': task, 'agent_running': agent_running(), 'paused': bool(state.get('paused')),
            'consecutive_failures': int(state.get('failures', 0)), 'last_run': state.get('last_run')}


def status_lines(info):
    task = info['task']
    lines = ['Schedule:   ' + info['description'],
             'Task:       ' + (info['task_name'] + ' (' + task.get('status', 'registered') + ')'
                               if task.get('exists') else 'not registered')]
    if task.get('next_run'):
        lines.append('Next run:   ' + task['next_run'])
    if info['mode'] == 'realtime':
        lines.append('Agent:      ' + ('running' if info['agent_running'] else 'not running'))
    last = info['last_run']
    lines.append('Last run:   ' + ('%s, %s (%s): %s' % (last.get('finished') or last.get('started'), last.get('outcome'),
                                                       last.get('trigger'), last.get('message')) if last else 'none yet'))
    if info['paused']:
        lines.append('PAUSED after %s consecutive failures. Fix the problem, then resume background runs.'
                     % info['consecutive_failures'])
    return lines


def run_now():
    """Start a background run now: through the running agent, or the scheduled task."""
    import scheduler
    if agent_running():
        request_run()
        return 'The real-time agent will sync within a few seconds.'
    if not scheduler.exists():
        raise ValueError('No schedule is registered. Save a schedule first.')
    scheduler.run_now()
    return 'Scheduled run started.'


def run(stop=None, poll=1.0):
    """Run until stopped, the schedule mode changes, or a stop file appears. Returns an exit code."""
    stop = stop or threading.Event()
    lock = runtime.RunLock(runtime.AGENT_LOCK)
    if not lock.acquire():
        log.info('The real-time agent is already running.')
        return runtime.OK
    for path in (runtime.AGENT_STOP, runtime.AGENT_POKE):
        path.unlink(missing_ok=True)
    listener = None
    listener_stop = threading.Event()
    debouncer = None
    signature = None
    paused_logged = False
    next_reload = 0
    values = None

    def watch_stop_file():
        # Separate thread so a stop request also cancels a sync that is in progress.
        while not stop.wait(1):
            if runtime.AGENT_STOP.exists():
                runtime.AGENT_STOP.unlink(missing_ok=True)
                log.info('Stop requested.')
                stop.set()

    threading.Thread(target=watch_stop_file, daemon=True).start()
    try:
        log.info('Real-time agent started (pid %s).', os.getpid())
        while not stop.is_set():
            if time.monotonic() >= next_reload:
                next_reload = time.monotonic() + 60
                try:
                    values = checked_config(storage.load())
                except Exception as exc:
                    log.error('Settings could not be loaded: %s', public_error(exc))
                    values = None
                if values and values.get('schedule_mode') != 'realtime':
                    log.info('Schedule mode is no longer real time. Stopping.')
                    break
                if values:
                    delay = _int(values.get('realtime_delay'), 30)
                    fallback = _int(values.get('realtime_fallback'), 60)
                    if debouncer is None:
                        debouncer = Debouncer(delay, fallback)
                        debouncer.poke('startup', delay=delay)
                    else:
                        debouncer.delay, debouncer.fallback = delay, fallback * 60
                    if connection_signature(values) != signature:
                        signature = connection_signature(values)
                        listener_stop.set()
                        listener_stop = threading.Event()
                        listener = Listener(values, debouncer.poke, listener_stop)
                        listener.start()
            if debouncer and runtime.AGENT_POKE.exists():
                runtime.AGENT_POKE.unlink(missing_ok=True)
                debouncer.poke('run requested', delay=0)
            reason = debouncer.due() if debouncer and values else None
            if reason:
                if runtime.read_state().get('paused'):
                    if not paused_logged:
                        log.warning('Background runs are paused after repeated failures; waiting for resume.')
                        paused_logged = True
                    debouncer.retry(60)
                else:
                    paused_logged = False
                    _, code, _ = runtime.run_sync(values, trigger=reason, cancel=stop)
                    if code == runtime.BUSY:
                        debouncer.retry(60)
                    else:
                        debouncer.ran()
            stop.wait(poll)
    finally:
        stop.set()
        listener_stop.set()
        lock.release()
        log.info('Real-time agent stopped.')
    return runtime.OK


def _int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
