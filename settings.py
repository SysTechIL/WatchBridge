"""Per-Windows-user settings; optional credentials protected using Windows DPAPI."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import sys

APP_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'WatchBridge'
DEFAULTS = {'media_server': 'plex', 'plex_url': 'http://localhost:32400', 'plex_token': '', 'plex_user': '',
            'jf_url': 'http://localhost:8096', 'jf_api_key': '', 'jf_user': '', 'jf_password': '',
            'qb_url': 'http://localhost:8080', 'qb_username': '', 'qb_password': '',
            'tag': 'Watched', 'ca_file': '', 'remember': False, 'interval': '10',
            'schedule_mode': 'off', 'schedule_every': '60', 'schedule_times': '03:00',
            'schedule_days': 'Mon,Tue,Wed,Thu,Fri,Sat,Sun', 'schedule_at_logon': False,
            'realtime_fallback': '60', 'realtime_delay': '30', 'max_failures': '5', 'keep_reports': '100'}
SECRETS = ('plex_token', 'jf_api_key', 'jf_password', 'qb_password')
# Saved only from the Schedule page or `schedule set`, so other saves keep the registered schedule.
SCHEDULE_KEYS = ('schedule_mode', 'schedule_every', 'schedule_times', 'schedule_days', 'schedule_at_logon',
                 'realtime_fallback', 'realtime_delay', 'max_failures')
# Preferences that do not change which servers, accounts or tag a scan uses.
LOCAL_KEYS = ('remember', 'interval', 'keep_reports') + SCHEDULE_KEYS
# Extra DPAPI input: a generic tool that unprotects data without it cannot read the credentials.
ENTROPY = b'WatchBridge credentials v1'


class Unreadable(RuntimeError):
    """Saved settings exist but could not be read in full. `values` holds everything that could be read."""

    def __init__(self, message, values):
        super().__init__(message)
        self.values = values


def protect(data, decrypt=False):
    if sys.platform != 'win32':
        raise RuntimeError('Remembering credentials is supported on Windows only.')
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

    def blob(value):
        raw = ctypes.create_string_buffer(value, len(value))
        return Blob(len(value), ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte))), raw

    source, keep = blob(data)
    entropy, keep_entropy = blob(ENTROPY)
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p if decrypt else wintypes.LPCWSTR, ctypes.POINTER(Blob),
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    target = Blob()
    if decrypt:
        # Credentials saved before version 1.3 were protected without the extra entropy.
        ok = (fn(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(target))
              or fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)))
    else:
        ok = fn(ctypes.byref(source), 'WatchBridge credentials', ctypes.byref(entropy), None, None, 1,
                ctypes.byref(target))
    if not ok:
        raise RuntimeError('Windows could not protect or unlock the saved credentials.')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def save(values):
    data = {k: values.get(k, v) for k, v in DEFAULTS.items() if k not in SECRETS}
    if values.get('remember'):
        secret = json.dumps({k: values.get(k, '') for k in SECRETS}).encode()
        data['protected_credentials'] = base64.b64encode(protect(secret)).decode('ascii')
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp = APP_DIR / 'settings.tmp'
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    target = APP_DIR / 'settings.json'
    if target.exists():
        # One previous version, in case settings that could not be read are replaced.
        shutil.copyfile(target, APP_DIR / 'settings.bak')
    os.replace(temp, target)


def save_local(**updates):
    """Change preferences in LOCAL_KEYS without reading or rewriting credentials."""
    path = APP_DIR / 'settings.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    except (OSError, ValueError):
        raise RuntimeError('The saved settings file is damaged or unreadable.') from None
    if not isinstance(data, dict):
        raise RuntimeError('The saved settings file is damaged or unreadable.')
    data.update({k: v for k, v in updates.items() if k in LOCAL_KEYS})
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp = APP_DIR / 'settings.tmp'
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temp, path)


def load():
    """Return saved settings. Raises Unreadable when the file is damaged or credentials cannot be unlocked."""
    values = dict(DEFAULTS)
    path = APP_DIR / 'settings.json'
    if not path.exists():
        return values
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        raise Unreadable('The saved settings file is damaged or unreadable.', values) from None
    values.update({k: data[k] for k in DEFAULTS if k in data and k not in SECRETS})
    if data.get('protected_credentials'):
        try:
            secret = json.loads(protect(base64.b64decode(data['protected_credentials']), decrypt=True))
        except Exception:
            raise Unreadable('Saved credentials could not be unlocked for this Windows user.', values) from None
        values.update({k: secret.get(k, '') for k in SECRETS})
    return values


def load_plain():
    """Saved settings without credentials; never raises for a damaged file or locked credentials."""
    try:
        values = load()
    except Unreadable as exc:
        values = exc.values
    return {k: ('' if k in SECRETS else v) for k, v in values.items()}
