"""Windows Task Scheduler integration. Tasks run as the signed-in user, so no administrator rights,
stored Windows password or service account are needed, and DPAPI credentials stay readable."""
import csv
from datetime import datetime, timedelta
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

MODES = {'off': 'Off', 'interval': 'Every X minutes', 'daily': 'Daily at set times',
         'weekly': 'Weekly on set days', 'logon': 'At Windows sign-in', 'realtime': 'Real time'}
DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
DAY_XML = dict(zip(DAYS, ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')))
DAY_GROUPS = {'all': DAYS, 'everyday': DAYS, 'daily': DAYS, 'weekdays': DAYS[:5], 'weekends': DAYS[5:],
              # Israeli work week.
              'sun-thu': ('Sun', 'Mon', 'Tue', 'Wed', 'Thu')}
MAX_MINUTES = 31 * 24 * 60
NO_WINDOW = 0x08000000


def task_name():
    return 'WatchBridge (' + os.environ.get('USERNAME', 'user') + ')'


def parse_every(text):
    """Return minutes from '30', '30m', '2h', '1h30m' or '1d'."""
    value = str(text).strip().lower().replace(' ', '')
    if value.isdigit():
        minutes = int(value)
    else:
        parts = re.fullmatch(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m(?:in)?)?', value)
        if not value or not parts or not any(parts.groups()):
            raise ValueError('Use an interval such as 30, 30m, 2h, 1h30m or 1d.')
        d, h, m = (int(x or 0) for x in parts.groups())
        minutes = d * 1440 + h * 60 + m
    if not 1 <= minutes <= MAX_MINUTES:
        raise ValueError('The interval must be between 1 minute and 31 days.')
    return minutes


def parse_times(text):
    times = set()
    for item in re.split(r'[,\s;]+', str(text).strip()):
        if not item:
            continue
        match = re.fullmatch(r'(\d{1,2}):(\d{2})', item)
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError('Use 24-hour times such as 03:00 or 08:30,20:00.')
        times.add('%02d:%02d' % (int(match[1]), int(match[2])))
    if not times:
        raise ValueError('Enter at least one time, such as 03:00.')
    return sorted(times)


def parse_days(text):
    days = set()
    for item in re.split(r'[,\s;]+', str(text).strip().lower()):
        if not item:
            continue
        if item in DAY_GROUPS:
            days.update(DAY_GROUPS[item])
            continue
        match = [d for d in DAYS if DAY_XML[d].lower().startswith(item) and len(item) >= 2]
        if len(match) != 1:
            raise ValueError('Unknown day "' + item + '". Use Mon,Tue,... or weekdays, weekends, sun-thu, all.')
        days.add(match[0])
    if not days:
        raise ValueError('Choose at least one day.')
    return [d for d in DAYS if d in days]


def number(value, name, low, high):
    try:
        result = int(str(value).strip())
    except ValueError:
        raise ValueError(name + ' must be a whole number.') from None
    if not low <= result <= high:
        raise ValueError(name + ' must be between ' + str(low) + ' and ' + str(high) + '.')
    return result


def normalize(values):
    """Validate the schedule keys and return them in their stored text form."""
    mode = str(values.get('schedule_mode', 'off')).strip().lower()
    if mode not in MODES:
        raise ValueError('Schedule mode must be one of: ' + ', '.join(MODES) + '.')
    out = {'schedule_mode': mode,
           'schedule_every': str(parse_every(values.get('schedule_every', '60'))),
           'schedule_times': ','.join(parse_times(values.get('schedule_times', '03:00'))),
           'schedule_days': ','.join(parse_days(values.get('schedule_days', 'all'))),
           'schedule_at_logon': _bool(values.get('schedule_at_logon', False)),
           'realtime_fallback': str(number(values.get('realtime_fallback', '60'), 'Fallback scan', 0, MAX_MINUTES)),
           'realtime_delay': str(number(values.get('realtime_delay', '30'), 'Event delay', 5, 3600)),
           'max_failures': str(number(values.get('max_failures', '5'), 'Failure limit', 0, 1000))}
    return out


def describe(values):
    v = normalize(values)
    mode = v['schedule_mode']
    if mode == 'off':
        return 'Off. Nothing runs in the background.'
    if mode == 'interval':
        text = 'Every ' + _duration(int(v['schedule_every']))
    elif mode == 'daily':
        text = 'Every day at ' + ', '.join(v['schedule_times'].split(','))
    elif mode == 'weekly':
        text = 'On ' + ', '.join(v['schedule_days'].split(',')) + ' at ' + ', '.join(v['schedule_times'].split(','))
    elif mode == 'logon':
        return 'Once each time you sign in to Windows.'
    else:
        fallback = int(v['realtime_fallback'])
        return ('Real time: listens for playback and watched-state changes, then syncs after '
                + v['realtime_delay'] + ' seconds' + (', plus a full check every ' + _duration(fallback) if fallback else '')
                + '. Starts when you sign in to Windows.')
    return text + (', and when you sign in to Windows.' if v['schedule_at_logon'] else '.')


def launch_command(arguments):
    """Command line for Task Scheduler, using the windowless executable so no console window appears."""
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable)
        gui = exe.with_name('WatchBridge.exe')
        return str(gui if gui.exists() else exe), arguments, str(exe.parent)
    python = Path(sys.executable)
    pythonw = python.with_name('pythonw.exe')
    script = Path(__file__).resolve().with_name('watchbridge.py')
    return (str(pythonw if pythonw.exists() else python), _quote(str(script)) + ' ' + arguments,
            str(script.parent))


def build_xml(values, now=None):
    v = normalize(values)
    mode = v['schedule_mode']
    if mode == 'off':
        raise ValueError('Nothing to schedule when the mode is off.')
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    user = escape(current_user())
    logon = ('<LogonTrigger><Enabled>true</Enabled><UserId>' + user + '</UserId><Delay>PT1M</Delay></LogonTrigger>')
    triggers = []
    if mode == 'interval':
        start = now + timedelta(minutes=1)
        triggers.append('<TimeTrigger><StartBoundary>' + _stamp(start) + '</StartBoundary><Enabled>true</Enabled>'
                        '<Repetition><Interval>PT' + v['schedule_every'] + 'M</Interval>'
                        '<StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger>')
    elif mode in ('daily', 'weekly'):
        days = ''.join('<' + DAY_XML[d] + ' />' for d in v['schedule_days'].split(','))
        for hhmm in v['schedule_times'].split(','):
            hour, minute = map(int, hhmm.split(':'))
            start = now.replace(hour=hour, minute=minute)
            if start <= now:
                start += timedelta(days=1)
            schedule = ('<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>' if mode == 'daily' else
                        '<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek>' + days
                        + '</DaysOfWeek></ScheduleByWeek>')
            triggers.append('<CalendarTrigger><StartBoundary>' + _stamp(start) + '</StartBoundary>'
                            '<Enabled>true</Enabled>' + schedule + '</CalendarTrigger>')
    if mode in ('logon', 'realtime') or v['schedule_at_logon']:
        triggers.append(logon)
    realtime = mode == 'realtime'
    command, arguments, workdir = launch_command('agent' if realtime else 'sync --scheduled')
    restart = '<RestartOnFailure><Interval>PT5M</Interval><Count>3</Count></RestartOnFailure>' if realtime else ''
    return ('<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            '<RegistrationInfo><Author>WatchBridge</Author><Description>' + escape(describe(v))
            + ' Managed by WatchBridge; change it from the Schedule page or the command line.</Description>'
            '</RegistrationInfo>'
            '<Triggers>' + ''.join(triggers) + '</Triggers>'
            '<Principals><Principal id="Author"><UserId>' + user + '</UserId>'
            '<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>'
            '<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>'
            '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>'
            '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate>'
            '<StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>'
            '<IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>'
            '<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden>'
            '<RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun>'
            '<ExecutionTimeLimit>' + ('PT0S' if realtime else 'PT2H') + '</ExecutionTimeLimit>'
            '<Priority>7</Priority>' + restart + '</Settings>'
            '<Actions Context="Author"><Exec><Command>' + escape(command) + '</Command><Arguments>'
            + escape(arguments) + '</Arguments><WorkingDirectory>' + escape(workdir)
            + '</WorkingDirectory></Exec></Actions></Task>')


def install(values):
    """Create or replace the task for the chosen mode; 'off' removes it."""
    if normalize(values)['schedule_mode'] == 'off':
        remove()
        return
    xml = build_xml(values)
    handle, path = tempfile.mkstemp(suffix='.xml', prefix='watchbridge-task-')
    os.close(handle)
    try:
        Path(path).write_text(xml, encoding='utf-16')
        _schtasks('/Create', '/TN', task_name(), '/XML', path, '/F')
    finally:
        Path(path).unlink(missing_ok=True)


def remove():
    if exists():
        _schtasks('/Delete', '/TN', task_name(), '/F')


def run_now():
    _schtasks('/Run', '/TN', task_name())


def end():
    if exists():
        _schtasks('/End', '/TN', task_name(), check=False)


def exists():
    return _schtasks('/Query', '/TN', task_name(), check=False)[0] == 0


def query():
    """Return task status as Task Scheduler reports it (dates use the Windows regional format)."""
    code, out = _schtasks('/Query', '/TN', task_name(), '/FO', 'CSV', '/V', '/NH', check=False)
    if code != 0:
        return {'exists': False}
    rows = [r for r in csv.reader(io.StringIO(out)) if len(r) > 6]
    if not rows:
        return {'exists': True}
    row = rows[0]
    last = '' if '1999' in row[5] else row[5]
    return {'exists': True, 'next_run': '' if row[2] in ('N/A', '') else row[2], 'status': row[3],
            'last_run': last, 'last_result': row[6] if last else ''}


def current_user():
    domain = os.environ.get('USERDOMAIN', '')
    user = os.environ.get('USERNAME', '')
    return domain + '\\' + user if domain else user


def _schtasks(*args, check=True):
    if sys.platform != 'win32':
        raise RuntimeError('Scheduling uses Windows Task Scheduler and is available on Windows only.')
    try:
        result = subprocess.run(['schtasks', *args], capture_output=True, creationflags=NO_WINDOW)
    except OSError:
        raise RuntimeError('Windows Task Scheduler (schtasks.exe) could not be started.') from None
    out = (result.stdout or b'').decode('oem', 'replace')
    if check and result.returncode != 0:
        detail = (result.stderr or b'').decode('oem', 'replace').strip() or out.strip()
        raise RuntimeError('Task Scheduler refused the change: ' + (detail or 'error ' + str(result.returncode)))
    return result.returncode, out


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _duration(minutes):
    if minutes % 1440 == 0:
        n, unit = minutes // 1440, 'day'
    elif minutes % 60 == 0:
        n, unit = minutes // 60, 'hour'
    else:
        n, unit = minutes, 'minute'
    return (unit if n == 1 else str(n) + ' ' + unit + 's')


def _stamp(value):
    return value.strftime('%Y-%m-%dT%H:%M:%S')


def _quote(value):
    return '"' + value + '"' if ' ' in value or not value else value
