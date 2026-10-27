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
