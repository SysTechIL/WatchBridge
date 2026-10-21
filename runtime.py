"""Background-run helpers shared by the window, command line, scheduled runs and the real-time agent."""
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path

from engine import SyncEngine, Cancelled, public_error, write_report, report_name
import settings as storage

LOG_FILE = storage.APP_DIR / 'logs' / 'watchbridge.log'
STATE_FILE = storage.APP_DIR / 'schedule-state.json'
RUN_LOCK = storage.APP_DIR / 'run.lock'
AGENT_LOCK = storage.APP_DIR / 'agent.lock'
AGENT_STOP = storage.APP_DIR / 'agent.stop'
AGENT_POKE = storage.APP_DIR / 'agent.poke'
REPORTS = storage.APP_DIR / 'reports'

# Exit codes used by the command line and recorded for scheduled runs.
OK, FAILED, USAGE, BUSY, PAUSED, CANCELLED = 0, 1, 2, 3, 4, 130

log = logging.getLogger('watchbridge')


def setup_logging(console=None):
    """Log to a rotating file; tokens and passwords are never passed to the logger."""
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        try:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s  %(levelname)-7s %(message)s', '%Y-%m-%d %H:%M:%S'))
            log.addHandler(handler)
        except OSError:
            pass
    if console is not None and not any(getattr(h, 'console', False) for h in log.handlers):
        handler = logging.StreamHandler(console)
        handler.console = True
        handler.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


class RunLock:
    """Cross-process, non-blocking lock. Windows releases it automatically if the process ends."""

    def __init__(self, path=None):
        self.path = Path(path or RUN_LOCK)
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(self.path, 'a+')
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self.stream = stream
        return True

    def release(self):
        if not self.stream:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.stream.close()
        self.stream = None

    def held_elsewhere(self):
        if self.acquire():
            self.release()
            return False
        return True


def read_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2), encoding='utf-8')
    os.replace(temp, STATE_FILE)


def record(result, max_failures):
    """Store the last background run; pause background runs after repeated failures."""
    state = read_state()
    state['last_run'] = result
    if result['outcome'] == 'ok':
        state['failures'] = 0
    elif result['outcome'] in ('failed', 'errors'):
        state['failures'] = int(state.get('failures', 0)) + 1
        if max_failures and state['failures'] >= max_failures and not state.get('paused'):
            state['paused'] = True
            log.warning('Background runs paused after %s consecutive failures. Resume them in Schedule '
                        'or with: schedule resume', state['failures'])
    write_state(state)
    return state


def record_failure(trigger, message, max_failures):
    """Record a background run that could not start, such as missing or locked settings."""
    stamp = now_text()
    log.error('Sync could not start (%s): %s', trigger, message)
    return record({'trigger': trigger, 'started': stamp, 'finished': stamp, 'outcome': 'failed', 'added': 0,
                   'ready': 0, 'errors': 0, 'videos': 0, 'excluded': 0, 'message': message, 'report': ''},
                  max_failures)


def resume():
    state = read_state()
    state.update(failures=0, paused=False)
    write_state(state)


def now_text():
    return datetime.now().isoformat(timespec='seconds')


def run_sync(values, trigger='manual', emit=None, cancel=None, background=True, report=True):
    """Scan, then add the tag to every ready torrent when the scan has no errors.

    Background runs honour the failure pause and record their outcome in the state file.
    """
    result = {'trigger': trigger, 'started': now_text(), 'finished': None, 'outcome': None, 'added': 0,
              'ready': 0, 'errors': 0, 'videos': 0, 'excluded': 0, 'message': '', 'report': ''}
    max_failures = _int(values.get('max_failures'), 5)
    if background and read_state().get('paused'):
        result.update(outcome='paused', finished=now_text(),
                      message='Background runs are paused after repeated failures. Resume them to continue.')
        log.warning(result['message'])
        return result, PAUSED, []
    lock = RunLock()
    if not lock.acquire():
        result.update(outcome='busy', finished=now_text(), message='Another WatchBridge run is in progress. Skipped.')
        log.info(result['message'])
        return result, BUSY, []
    rows, code = [], OK
    engine = SyncEngine(values, emit or _log_emit, cancel)
    try:
        log.info('Sync started (%s).', trigger)
        rows, excluded = engine.scan()
        result['errors'] = sum(r['status'] == 'ERROR' for r in rows)
        result['ready'] = sum(r['status'] == 'READY' for r in rows)
        if result['errors']:
            result.update(outcome='errors', message=str(result['errors']) + ' torrents could not be read. No tags added.')
            code = FAILED
        else:
            result['added'] = engine.apply(rows)
            result.update(outcome='ok', message='Verified ' + format(result['added'], ',') + ' tag additions.')
        result.update(videos=len(rows), excluded=excluded)
    except Cancelled:
        result.update(outcome='cancelled', message='Stopped. Tags already added remain.')
        code = CANCELLED
    except Exception as exc:
        result.update(outcome='failed', message=public_error(exc))
        code = FAILED
    finally:
        engine.close()
        lock.release()
    result['finished'] = now_text()
    if report and rows:
        try:
            path = REPORTS / report_name()
            write_report(path, rows)
            result['report'] = str(path)
        except OSError:
            log.warning('Could not save the automatic report.')
    (log.info if code == OK else log.error)('Sync %s: %s', result['outcome'], result['message'])
    if background:
        record(result, max_failures)
    return result, code, rows


def _log_emit(kind, data):
    if kind in ('log', 'phase'):
        log.info('%s', data)


def _int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
