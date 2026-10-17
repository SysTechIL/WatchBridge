import csv
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
import settings


class Response:
    def __init__(self, text='', data=None, status=200):
        self.text, self.data, self.status_code = text, data, status
        self.ok = 200 <= status < 300
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return next(self.responses)
    def close(self):
        pass


def config():
    return dict(settings.DEFAULTS, plex_token='fake-token', qb_username='test', qb_password='fake-password')


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.t = {'save_path': 'M:/Media', 'progress':1}
        self.files = [{'name':'Show/S01E01.mkv', 'progress':1}, {'name':'Show/S01E02.mkv', 'progress':1}]
        self.a, self.b = engine.norm('M:/Media/Show/S01E01.mkv'), engine.norm('M:/Media/Show/S01E02.mkv')
        self.index = {self.a:[True], self.b:[True]}
    def test_complete_season(self):
        self.assertEqual(engine.evaluate(self.t,self.files,self.index)[0], 'READY')
    def test_partial_season(self):
        self.index[self.b]=[False]
        self.assertEqual(engine.evaluate(self.t,self.files,self.index)[0], 'UNWATCHED')
    def test_missing_path(self):
        del self.index[self.b]
        status, watched, total, missing = engine.evaluate(self.t,self.files,self.index)
        self.assertEqual((status,watched,total,missing), ('UNMATCHED',1,2,[self.b]))
    def test_two_episodes_one_file(self):
        self.index[self.a]=[True,False]
        self.assertEqual(engine.evaluate(self.t,self.files,self.index)[0], 'UNWATCHED')
    def test_nonvideo_and_samples_ignored(self):
        files=self.files+[{'name':'Show-sample.mkv'}, {'name':'Readme.nfo'}, {'name':'Film.srt'}]
        self.assertEqual(engine.evaluate(self.t,files,self.index)[0], 'READY')
    def test_archive_not_video(self):
        self.assertEqual(engine.evaluate(self.t,[{'name':'Film.rar'}],{})[0], 'NO_VIDEO')
    def test_incomplete(self):
        self.files[0]['progress']=0.5
        self.assertEqual(engine.evaluate(self.t,self.files,self.index)[0], 'INCOMPLETE')
    def test_bonus_video_blocks(self):
        self.assertEqual(engine.evaluate(self.t,self.files+[{'name':'bonus.mkv','progress':1}],self.index)[0], 'UNMATCHED')
    def test_path_normalization(self):
        self.assertEqual(engine.norm('m:/media/Show/../Film.mkv'),engine.norm('M:\\Media\\Film.mkv'))
    def test_no_fuzzy_matching(self):
        self.assertEqual(engine.evaluate(dict(self.t,save_path='M:/Temporary'),self.files,self.index)[0], 'UNMATCHED')


class ApiTests(unittest.TestCase):
    def test_legacy_and_new_login(self):
        for status, text in [(200,'Ok.'),(200,''),(204,'')]:
            with self.subTest(status=status,text=text):
                session=Session([Response(text,status=status),Response('v5.2.4'),Response(data=['Watched'])])
                with patch.dict(sys.modules,{'requests':types.SimpleNamespace(Session=lambda:session)}):
                    self.assertEqual(engine.SyncEngine(config()).connect_qb(),('v5.2.4',['Watched']))
    def test_bad_login(self):
        session=Session([Response('Fails.')])
        with patch.dict(sys.modules,{'requests':types.SimpleNamespace(Session=lambda:session)}):
            with self.assertRaisesRegex(RuntimeError,'rejected'):
                engine.SyncEngine(config()).connect_qb()
    def test_reject_wrong_service(self):
        session=Session([Response(''),Response('<html>login</html>'),Response(data=[])])
        with patch.dict(sys.modules,{'requests':types.SimpleNamespace(Session=lambda:session)}):
            with self.assertRaises(RuntimeError): engine.SyncEngine(config()).connect_qb()
    def test_403_not_success(self):
        session=Session([Response('',status=204),Response('',status=403)])
        with patch.dict(sys.modules,{'requests':types.SimpleNamespace(Session=lambda:session)}):
            with self.assertRaisesRegex(RuntimeError,'403'):engine.SyncEngine(config()).connect_qb()
    def test_fragment_removed(self):
        self.assertEqual(engine.clean_url('http://localhost:8080/#/'),'http://localhost:8080')
    def test_cancel_before_network(self):
        event=threading.Event();event.set()
        with self.assertRaises(engine.Cancelled):engine.SyncEngine(config(),cancel=event).checkpoint()
    def test_pagination_and_watch_state(self):
        class Plex:
            def query(self,url):
                if url=='/library/sections':return ET.fromstring('<MediaContainer><Directory key="1" type="show" title="Test"/></MediaContainer>')
                n=0 if 'Start=0' in url else 1
                return ET.fromstring(f'<MediaContainer totalSize="2"><Video viewCount="{1-n}"><Media><Part file="M:/e{n}.mkv"/></Media></Video></MediaContainer>')
        e=engine.SyncEngine(config());e.plex=Plex();idx=e.scan_plex()
        self.assertEqual(idx[engine.norm('M:/e0.mkv')],[True]);self.assertEqual(idx[engine.norm('M:/e1.mkv')],[False])
    def test_profile_exact_and_switch(self):
        owner=types.SimpleNamespace(username='owner',title='Owner',friendlyName='Owner',users=lambda:[types.SimpleNamespace(title='Viewer')])
        class Plex:
            def __init__(self,*args,**kwargs):pass
            def myPlexAccount(self):return owner
            def switchUser(self,user):return 'switched-server'
        modules={'plexapi':types.ModuleType('plexapi'),'plexapi.server':types.SimpleNamespace(PlexServer=Plex)}
        with patch.dict(sys.modules,modules):
            e=engine.SyncEngine(dict(config(),plex_user='Viewer'))
            self.assertEqual(e.connect_plex(),'Viewer');self.assertEqual(e.plex,'switched-server')
            with self.assertRaises(ValueError):engine.SyncEngine(dict(config(),plex_user='Other')).connect_plex()
    def test_nonvideo_excluded_even_if_tagged(self):
        e=engine.SyncEngine(config());e.connect=lambda:None;e.scan_plex=lambda:{}
        e.request=lambda endpoint,params=None:Response(data=([{'hash':'abc','name':'Book','tags':'Watched','save_path':'M:/','progress':1}] if endpoint=='torrents/info' else [{'name':'book.pdf'}]))
        rows,excluded=e.scan();self.assertEqual(rows,[]);self.assertEqual(excluded,1)
    def test_apply_adds_and_verifies_only(self):
        events=[];e=engine.SyncEngine(config(),lambda kind,data:events.append((kind,data)))
        e.connect=lambda:None;e.scan_plex=lambda:{engine.norm('M:/film.mkv'):[True]}
        torrent={'hash':'abc','name':'Film','save_path':'M:/','progress':1,'tags':''}
        tagged=False;calls=[]
        def request(endpoint,data=None,params=None):
            nonlocal tagged
            calls.append(endpoint)
            if endpoint=='torrents/info':return Response(data=[dict(torrent,tags='Watched' if tagged else '')])
            if endpoint=='torrents/files':return Response(data=[{'name':'film.mkv','progress':1}])
            if endpoint=='torrents/addTags':tagged=True;return Response()
            raise AssertionError(endpoint)
        e.request=request
        self.assertEqual(e.apply([{'hash':'abc','torrent':'Film','status':'READY'}]),1)
        self.assertEqual(calls,['torrents/info','torrents/files','torrents/addTags','torrents/info'])
        self.assertEqual([data['status'] for kind,data in events if kind=='updated'],['TAGGED'])
    def test_apply_rechecks_unwatched(self):
        e=engine.SyncEngine(config());e.connect=lambda:None;e.scan_plex=lambda:{engine.norm('M:/film.mkv'):[False]}
        def request(endpoint,data=None,params=None):
            if endpoint=='torrents/info':return Response(data=[{'save_path':'M:/','progress':1}])
            if endpoint=='torrents/files':return Response(data=[{'name':'film.mkv','progress':1}])
            raise AssertionError('Unexpected mutation: '+endpoint)
        e.request=request
        self.assertEqual(e.apply([{'hash':'abc','torrent':'Film','status':'READY'}]),0)
    def test_error_blocks_apply(self):
        with self.assertRaises(ValueError):engine.SyncEngine(config()).apply([{'status':'ERROR'}])


class StorageTests(unittest.TestCase):
    def test_report_filters_and_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.csv'
            engine.write_report(p,[{'status':'NO_VIDEO','torrent':'book'}, {'status':'READY','torrent':'=danger','hash':'abc','video_files':1}])
            with p.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['torrent'],"'=danger")
    def test_settings_do_not_store_plaintext_secrets(self):
        with tempfile.TemporaryDirectory() as d,patch.object(settings,'APP_DIR',Path(d)):
            settings.save(config())
            text=(Path(d)/'settings.json').read_text()
            self.assertNotIn('fake-token',text);self.assertNotIn('fake-password',text)
            self.assertEqual(settings.load()['plex_token'],'')
    def test_encrypted_round_trip_contract(self):
        def fake_protect(data,decrypt=False):return data[::-1]
        with tempfile.TemporaryDirectory() as d,patch.object(settings,'APP_DIR',Path(d)),patch.object(settings,'protect',fake_protect):
            settings.save(dict(config(),remember=True))
            self.assertNotIn('fake-token',(Path(d)/'settings.json').read_text())
            self.assertEqual(settings.load()['plex_token'],'fake-token')
            settings.save(dict(config(),remember=False))
            self.assertNotIn('protected_credentials',(Path(d)/'settings.json').read_text())


if __name__=='__main__':unittest.main()
