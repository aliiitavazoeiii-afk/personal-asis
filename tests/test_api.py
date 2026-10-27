import importlib.util
import os
import sys
import tempfile
from pathlib import Path

os.environ['APP_PASSWORD'] = 'test-password-very-private'
os.environ['SESSION_SECRET'] = 'test-secret-for-local-testing-not-for-production'
TEST_DB = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(TEST_DB.name) / 'store.db')
os.environ['COOKIE_SECURE'] = 'false'
os.environ['OPENAI_API_KEY'] = ''
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from fastapi.testclient import TestClient
from app import app, basic_parse
from zoneinfo import ZoneInfo
import datetime as dt


def test_owner_flow():
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
        assert client.get('/api/items').status_code == 401
        assert client.post('/api/login', json={'password': 'wrong'}).status_code == 401
        assert client.post('/api/login', json={'password': 'test-password-very-private'}).status_code == 200
        assert client.get('/api/me').json()['ok']
        assert client.post('/api/items', json={'kind': 'reminder', 'title': 'call'}).status_code == 422
        due=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat()
        resp=client.post('/api/items', json={'kind':'reminder','title':'Call supplier','due_at':due})
        assert resp.status_code == 201, resp.text
        item=resp.json()
        assert client.get('/api/items').json()['items'][0]['id'] == item['id']
        assert client.patch('/api/items/'+item['id'], json={'status':'done'}).json()['status']=='done'
        assert client.delete('/api/items/'+item['id']).status_code==200
        assert client.get('/api/items').json()['items']==[]
        assert client.post('/api/logout',json={}).status_code == 200
        assert client.get('/api/items').status_code == 401


def test_farsi_deadline_and_vague():
    now=dt.datetime(2026,10,27,10,0,tzinfo=ZoneInfo('Asia/Tehran'))
    good=basic_parse('فردا ساعت ۱۰ صبح یادم بنداز با تأمین کننده تماس بگیرم',now)
    assert good['kind']=='reminder'
    assert good['due_at'].startswith('2026-10-28T10:00')
    vague=basic_parse('بعدا یادم بنداز به تأمین کننده زنگ بزنم',now)
    assert vague['kind']=='task' and vague['needs_clarification'] and vague['due_at'] is None


def test_parse_without_openai():
    with TestClient(app) as client:
        client.post('/api/login',json={'password':'test-password-very-private'})
        r=client.post('/api/parse',json={'text':'یه ایده برای بسته بندی دارما دارم','timezone':'Asia/Tehran'})
        assert r.status_code==200 and r.json()['kind']=='idea'
        resp=client.post('/api/transcribe',files={'audio':('voice.m4a',b'a'*400,'audio/mp4')})
        assert resp.status_code==503


def test_pwa_assets_and_no_stale_code():
    import struct
    with TestClient(app) as client:
        root = client.get('/')
        assert root.status_code == 200
        assert '/manifest.webmanifest' in root.text
        assert 'no-store' in root.headers['cache-control']
        manifest = client.get('/manifest.webmanifest')
        assert manifest.status_code == 200
        assert manifest.json()['display'] == 'standalone'
        assert manifest.json()['start_url'] == '/'
        assert 'no-store' in manifest.headers['cache-control']
        for size in (192, 512):
            icon = client.get(f'/assets/icon-{size}.png')
            assert icon.status_code == 200
            assert icon.headers['content-type'].startswith('image/png')
            assert icon.content[:8] == bytes((137, 80, 78, 71, 13, 10, 26, 10))
            assert struct.unpack('>II', icon.content[16:24]) == (size, size)
        assert client.get('/assets/icon-1.png').status_code == 404
        sw = client.get('/sw.js')
        assert sw.status_code == 200
        assert 'no-store' in sw.headers['cache-control']
        assert 'addEventListener' in sw.text
        # Explicit pass-through fetch handler: no CacheStorage or stale shell.
        assert "addEventListener('fetch'" in sw.text
        assert "cache:'no-store'" in sw.text
        assert 'caches.open' not in sw.text
        ui = client.get('/assets/app.js')
        assert 'no-store' in ui.headers['cache-control']
        assert 'navigator.mediaDevices.getUserMedia' in ui.text


def test_transcription_accepts_browser_webm(monkeypatch):
    import app as application
    requests = []

    class FakeOpenAIResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'text': 'فردا ساعت ده یادم بنداز'}

    class FakeOpenAIClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return FakeOpenAIResponse()

    monkeypatch.setattr(application, 'OPENAI_KEY', 'test-only-key')
    monkeypatch.setattr(application.httpx, 'AsyncClient', FakeOpenAIClient)
    with TestClient(app) as client:
        client.post('/api/login', json={'password': 'test-password-very-private'})
        answer = client.post('/api/transcribe', files={
            'audio': ('voice.webm', b'fake-test-audio-data' * 100, 'audio/webm')
        })
        assert answer.status_code == 200, answer.text
        assert answer.json()['text'].startswith('فردا')
        assert len(requests) == 1
        assert requests[0][0].endswith('/audio/transcriptions')
        assert requests[0][1]['data']['language'] == 'fa'
        assert requests[0][1]['files']['file'][2] == 'audio/webm'
