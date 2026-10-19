"""WatchBridge matching and API operations. No GUI or persistent secrets here."""
import csv
import ntpath
import re
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

VIDEO = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.mpg', '.mpeg',
         '.ts', '.m2ts', '.mts', '.webm', '.vob', '.flv', '.ogv', '.divx'}


class Cancelled(Exception):
    pass


def norm(value):
    return ntpath.normcase(ntpath.normpath(value.replace('/', '\\')))


def clean_url(value):
    parts = urlsplit(value.strip())
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username:
        raise ValueError('Use a full http:// or https:// URL without embedded credentials.')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/'), '', ''))


def media_files(files):
    return [f for f in files if ntpath.splitext(f['name'])[1].lower() in VIDEO
            and not re.search(r'(^|[ ._\-])sample([ ._\-]|$)', ntpath.basename(f['name']), re.I)]


def evaluate(torrent, files, index):
    media = media_files(files)
    if not media:
        return 'NO_VIDEO', 0, 0, []
    watched, missing = 0, []
    for f in media:
        path = norm(ntpath.join(torrent['save_path'], f['name']))
        states = index.get(path, [])
        if not states:
            missing.append(path)
        elif all(states):
            watched += 1
    if missing:
        return 'UNMATCHED', watched, len(media), missing
    if watched != len(media):
        return 'UNWATCHED', watched, len(media), []
    if float(torrent.get('progress', 0)) < 1 or any(float(f.get('progress', 0)) < 1 for f in media):
        return 'INCOMPLETE', watched, len(media), []
    return 'READY', watched, len(media), []


def public_error(exc):
    # URLs, HTTP bodies and exception reprs can contain personal tokens.
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)
    return type(exc).__name__ + ': check network access, service addresses and account access.'


class SyncEngine:
    def __init__(self, settings, emit=None, cancel=None):
        self.settings = dict(settings)
        self.emit = emit or (lambda kind, data: None)
        self.cancel = cancel or threading.Event()
        self.qb = None
        self.plex = None
        self.jf = None
        self.jf_user_id = None

    @property
    def server(self):
        return 'jellyfin' if self.settings.get('media_server') == 'jellyfin' else 'plex'

    def checkpoint(self):
        if self.cancel.is_set():
            raise Cancelled()

    def request(self, endpoint, data=None, params=None):
        self.checkpoint()
        try:
            r = self.qb.request('POST' if data is not None else 'GET',
                self.qb_url + '/api/v2/' + endpoint, data=data, params=params, timeout=(10, 60))
        except Exception:
            raise RuntimeError('qBittorrent could not be reached. Check its Web UI address and network access.') from None
        if not r.ok:
            raise RuntimeError('qBittorrent API returned HTTP ' + str(r.status_code)
                + ' at ' + endpoint + '. Check Web UI access; HTTP 403 can also mean a temporary IP ban.')
        return r

    def connect_qb(self):
        import requests
        self.checkpoint()
        self.qb_url = clean_url(self.settings.get('qb_url', ''))
        self.qb = requests.Session()
        parts = urlsplit(self.qb_url)
        self.qb.headers.update({'Referer': self.qb_url + '/',
                               'Origin': urlunsplit((parts.scheme, parts.netloc, '', '', ''))})
        login = self.request('auth/login', data={'username': self.settings.get('qb_username', ''),
                                                'password': self.settings.get('qb_password', '')})
        if login.text.strip() == 'Fails.':
            raise RuntimeError('qBittorrent rejected the login. Check the Web UI username and password.')
        try:
            version = self.request('app/version').text.strip()
            tags = self.request('torrents/tags').json()
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError('The address did not return valid qBittorrent API data.') from None
        if not re.fullmatch(r'v?\d+\.\d+(?:\.\d+)?[^\s<>]*', version) or not isinstance(tags, list):
            raise RuntimeError('This address does not appear to be a qBittorrent Web UI.')
        self.emit('log', 'qBittorrent connected: ' + version)
        return version, tags

    def connect_plex(self):
        from plexapi.server import PlexServer
        self.checkpoint()
        token = self.settings.get('plex_token', '').strip()
        if not token:
            raise ValueError('Enter your personal Plex token in Connections.')
        try:
            plex = PlexServer(clean_url(self.settings.get('plex_url', '')), token=token, timeout=60)
            account = plex.myPlexAccount()
            wanted = self.settings.get('plex_user', '').strip().casefold()
            names = {str(getattr(account, k, '') or '').strip().casefold()
                     for k in ('username', 'title', 'friendlyName')}
            title = account.friendlyName or account.title or account.username
            if wanted and wanted not in names:
                matches = [u for u in account.users() if wanted in {
                    str(getattr(u, k, '') or '').strip().casefold() for k in ('username', 'title')}]
                if len(matches) != 1:
                    raise ValueError('The requested Plex profile could not be verified. '
                                     'Use its exact name or a token from that account.')
                plex = plex.switchUser(matches[0])
                title = matches[0].title
            self.plex = plex
            self.emit('profile', str(title))
            self.emit('log', 'Plex profile verified: ' + str(title))
            return str(title)
        except ValueError:
            raise
        except Exception:
            raise RuntimeError('Plex connection or profile verification failed. '
                               'Check the server URL, personal token and access to plex.tv.') from None

    def jf_request(self, path, params=None, data=None):
        self.checkpoint()
        try:
            r = self.jf.request('POST' if data is not None else 'GET', self.jf_url + path,
                                json=data, params=params, timeout=(10, 60))
        except Exception:
            raise RuntimeError('Jellyfin could not be reached. Check its server address and network access.') from None
        if r.status_code in (401, 403):
            raise RuntimeError('Jellyfin rejected the API key or login. Check your Jellyfin credentials.')
        if not r.ok:
            raise RuntimeError('Jellyfin API returned HTTP ' + str(r.status_code) + '. Check the server address.')
        try:
            return r.json()
        except Exception:
            raise RuntimeError('The address did not return valid Jellyfin API data.') from None

    def jf_auth(self, token=None):
        value = 'MediaBrowser Client="WatchBridge", Device="Windows", DeviceId="watchbridge", Version="1.1.0"'
        self.jf.headers['Authorization'] = value + (', Token="' + token + '"' if token else '')

    def connect_jellyfin(self):
        import requests
        self.checkpoint()
        self.jf_url = clean_url(self.settings.get('jf_url', ''))
        key = self.settings.get('jf_api_key', '').strip()
        password = self.settings.get('jf_password', '')
        wanted = self.settings.get('jf_user', '').strip()
        if not wanted:
            raise ValueError('Enter your Jellyfin user name in Connections.')
        if not key and not password:
            raise ValueError('Enter a Jellyfin API key, or your Jellyfin password, in Connections.')
        self.jf = requests.Session()
        if key:
            self.jf_auth(key)
            users = self.jf_request('/Users')
            if not isinstance(users, list):
                raise RuntimeError('This address does not appear to be a Jellyfin server.')
            matches = [u for u in users if isinstance(u, dict)
                       and str(u.get('Name', '')).strip().casefold() == wanted.casefold()]
            if len(matches) != 1:
                raise ValueError('The requested Jellyfin user could not be verified. Use the exact user name.')
            user = matches[0]
        else:
            self.jf_auth()
            login = self.jf_request('/Users/AuthenticateByName', data={'Username': wanted, 'Pw': password})
            if not isinstance(login, dict) or not login.get('AccessToken') or not isinstance(login.get('User'), dict):
                raise RuntimeError('This address does not appear to be a Jellyfin server.')
            self.jf_auth(login['AccessToken'])
            user = login['User']
        if not user.get('Id'):
            raise RuntimeError('Jellyfin did not return a user id.')
        self.jf_user_id = user['Id']
        title = str(user.get('Name') or wanted)
        self.emit('profile', title)
        self.emit('log', 'Jellyfin user verified: ' + title)
        return title

    def connect(self):
        version, tags = self.connect_qb()
        profile = self.connect_jellyfin() if self.server == 'jellyfin' else self.connect_plex()
        tag = self.settings.get('tag', 'Watched').strip()
        if not tag or ',' in tag:
            raise ValueError('Enter one tag name without commas.')
        if tag not in tags:
            raise ValueError('Create the tag "' + tag + '" in qBittorrent first, then try again.')
        return profile, version

    def scan_plex(self):
        index = defaultdict(list)
        for section in self.plex.query('/library/sections').findall('Directory'):
            if section.get('type') not in ('movie', 'show'):
                continue
            self.emit('phase', 'Reading Plex library: ' + section.get('title', ''))
            offset, expected = 0, None
            while True:
                self.checkpoint()
                query = urlencode({'type': 1 if section.get('type') == 'movie' else 4,
                    'includeMedia': 1, 'X-Plex-Container-Start': offset, 'X-Plex-Container-Size': 500})
                data = self.plex.query('/library/sections/' + section.get('key') + '/all?' + query)
                items = data.findall('Video')
                total = int(data.get('totalSize', data.get('size', len(items))))
                if expected is None:
                    expected = total
                if total != expected or (not items and offset < total):
                    raise RuntimeError('Plex library changed or returned an incomplete page. Please scan again.')
                for item in items:
                    watched = int(item.get('viewCount', '0')) > 0
                    parts = item.findall('./Media/Part')
                    if not parts:
                        self.checkpoint()
                        parts = self.plex.query(item.get('key')).findall('./Video/Media/Part')
                    for part in parts:
                        if part.get('file'):
                            index[norm(part.get('file'))].append(watched)
                offset += len(items)
                if offset >= total:
                    break
        if not index:
            raise RuntimeError('Plex returned no movie or episode file paths. No tags changed.')
        self.emit('log', 'Indexed ' + format(len(index), ',') + ' Plex file paths.')
        return index

    def scan_jellyfin(self):
        index = defaultdict(list)
        self.emit('phase', 'Reading Jellyfin library')
        offset, expected = 0, None
        while True:
            data = self.jf_request('/Items', params={
                'userId': self.jf_user_id, 'Recursive': 'true', 'IncludeItemTypes': 'Movie,Episode',
                'Fields': 'Path,MediaSources', 'EnableUserData': 'true', 'SortBy': 'SortName',
                'StartIndex': offset, 'Limit': 500})
            if not isinstance(data, dict) or not isinstance(data.get('Items'), list):
                raise RuntimeError('Jellyfin returned an unexpected library response. No tags changed.')
            items = data['Items']
            total = int(data.get('TotalRecordCount', len(items)))
            if expected is None:
                expected = total
            if total != expected or (not items and offset < total):
                raise RuntimeError('Jellyfin library changed or returned an incomplete page. Please scan again.')
            for item in items:
                watched = bool((item.get('UserData') or {}).get('Played'))
                # Each version of an item has its own file; strm and remote sources are not files.
                paths = {s['Path'] for s in item.get('MediaSources') or []
                         if s.get('Path') and s.get('Protocol', 'File') == 'File'}
                if not paths and item.get('Path'):
                    paths = {item['Path']}
                for path in paths:
                    index[norm(path)].append(watched)
            offset += len(items)
            if offset >= total:
                break
        if not index:
            raise RuntimeError('Jellyfin returned no movie or episode file paths. No tags changed.')
        self.emit('log', 'Indexed ' + format(len(index), ',') + ' Jellyfin file paths.')
        return index

    def scan_media(self):
        return self.scan_jellyfin() if self.server == 'jellyfin' else self.scan_plex()

    def scan(self):
        self.connect()
        index = self.scan_media()
        torrents = self.request('torrents/info').json()
        rows, excluded = [], 0
        for i, torrent in enumerate(torrents, 1):
            self.checkpoint()
            try:
                files = self.request('torrents/files', params={'hash': torrent['hash']}).json()
                status, watched, total, missing = evaluate(torrent, files, index)
                if status == 'NO_VIDEO':
                    excluded += 1
                    continue
                if self.settings['tag'] in {t.strip() for t in torrent.get('tags', '').split(',')}:
                    status = 'TAGGED'
                row = {'status': status, 'torrent': torrent['name'], 'hash': torrent['hash'],
                       'watched_files': watched, 'video_files': total,
                       'unmatched_paths': ' | '.join(missing), 'error': ''}
            except Cancelled:
                raise
            except Exception as exc:
                row = {'status': 'ERROR', 'torrent': torrent['name'], 'hash': torrent['hash'],
                       'watched_files': '', 'video_files': '', 'unmatched_paths': '', 'error': public_error(exc)}
            rows.append(row)
            self.emit('row', dict(row))
            self.emit('progress', (i, len(torrents)))
        self.emit('progress', (len(torrents), len(torrents)))
        self.emit('log', 'Excluded ' + str(excluded) + ' torrents without supported video files.')
        if any(r['status'] == 'ERROR' for r in rows):
            self.emit('log', 'Some torrents could not be read. Fix the errors and scan again before tagging.')
        return rows, excluded

    def apply(self, rows):
        """Re-read watched state and exact file paths before adding any tags."""
        if any(r['status'] == 'ERROR' for r in rows):
            raise ValueError('The scan contains errors. Resolve them and scan again before tagging.')
        ready = [r for r in rows if r['status'] == 'READY']
        if not ready:
            return 0
        self.connect()
        index = self.scan_media()
        added = 0
        for i, row in enumerate(ready, 1):
            self.checkpoint()
            current = self.request('torrents/info', params={'hashes': row['hash']}).json()
            if len(current) != 1:
                self.emit('log', 'Skipped a torrent that is no longer available: ' + row['torrent'])
                continue
            files = self.request('torrents/files', params={'hash': row['hash']}).json()
            status, watched, total, missing = evaluate(current[0], files, index)
            if status != 'READY':
                row.update(status=status, watched_files=watched, video_files=total,
                           unmatched_paths=' | '.join(missing))
                self.emit('updated', dict(row))
                continue
            if self.settings['tag'] not in {t.strip() for t in current[0].get('tags', '').split(',')}:
                self.request('torrents/addTags', data={'hashes': row['hash'], 'tags': self.settings['tag']})
            check = self.request('torrents/info', params={'hashes': row['hash']}).json()
            if len(check) != 1 or self.settings['tag'] not in {t.strip() for t in check[0].get('tags', '').split(',')}:
                raise RuntimeError('Could not verify a tag update. Some earlier tags may have been added. Scan again.')
            row['status'] = 'TAGGED'
            self.emit('updated', dict(row))
            self.emit('log', 'Tagged: ' + row['torrent'])
            self.emit('progress', (i, len(ready)))
            added += 1
        return added

    def close(self):
        for session in (self.qb, self.jf):
            if session:
                session.close()


FIELDS = ['status', 'torrent', 'hash', 'watched_files', 'video_files', 'unmatched_paths', 'error']


def write_report(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            if row['status'] == 'NO_VIDEO':
                continue
            values = {k: str(row.get(k, '')) for k in FIELDS}
            writer.writerow({k: "'" + v if v.startswith(('=', '+', '-', '@')) else v
                             for k, v in values.items()})


def report_name():
    return 'watchbridge-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.csv'
