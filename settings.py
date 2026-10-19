"""Per-Windows-user settings; optional credentials protected using Windows DPAPI."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

APP_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / 'WatchBridge'
DEFAULTS = {'media_server': 'plex', 'plex_url': 'http://localhost:32400', 'plex_token': '', 'plex_user': '',
            'jf_url': 'http://localhost:8096', 'jf_api_key': '', 'jf_user': '', 'jf_password': '',
            'qb_url': 'http://localhost:8080', 'qb_username': '', 'qb_password': '',
            'tag': 'Watched', 'remember': False, 'interval': '10'}
SECRETS = ('plex_token', 'jf_api_key', 'jf_password', 'qb_password')


def protect(data, decrypt=False):
    if sys.platform != 'win32':
        raise RuntimeError('Remembering credentials is supported on Windows only.')
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]
    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), 'WatchBridge credentials', None, None, None, 1, ctypes.byref(target))
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
    os.replace(temp, APP_DIR / 'settings.json')


def load():
    values = dict(DEFAULTS)
    path = APP_DIR / 'settings.json'
    if not path.exists():
        return values
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    values.update({k: data[k] for k in DEFAULTS if k in data and k not in SECRETS})
    if data.get('protected_credentials'):
        secret = json.loads(protect(base64.b64decode(data['protected_credentials']), decrypt=True))
        values.update({k: secret.get(k, '') for k in SECRETS})
    return values
