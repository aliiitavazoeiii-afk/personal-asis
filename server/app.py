"""Personal Assist: private single-user voice capture, task inbox and reminders."""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent
DB_FILE = Path(os.getenv('DB_PATH', '/data/assistant.sqlite3'))
PASSWORD = os.getenv('APP_PASSWORD', '')
SESSION_SECRET = os.getenv('SESSION_SECRET', '')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
DEFAULT_TZ = os.getenv('DEFAULT_TZ', 'Asia/Tehran')
AUDIO_LIMIT = 12 * 1024 * 1024
COOKIE = 'pa_session'

if not PASSWORD or not SESSION_SECRET or len(SESSION_SECRET) < 32:
    raise RuntimeError('Set APP_PASSWORD and SESSION_SECRET (32+ characters) before starting.')

signer = URLSafeTimedSerializer(SESSION_SECRET, salt='personal-assist-auth-v1')
failed_logins: dict[str, list[float]] = {}


def db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


@asynccontextmanager
async def lifespan(app: FastAPI):
    with db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '', due_at TEXT, status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )''')
    yield

app = FastAPI(title='Personal Assist', docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware('http')
async def secure_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
        "connect-src 'self'; frame-src 'none'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


class Login(BaseModel):
    password: str


class ItemInput(BaseModel):
    kind: str = Field(pattern='^(reminder|task|note|idea)$')
    title: str = Field(min_length=1, max_length=500)
    detail: str = Field(default='', max_length=8000)
    due_at: str | None = None


class ItemPatch(BaseModel):
    kind: str | None = Field(default=None, pattern='^(reminder|task|note|idea)$')
    title: str | None = Field(default=None, min_length=1, max_length=500)
    detail: str | None = Field(default=None, max_length=8000)
    due_at: str | None = None
    status: str | None = Field(default=None, pattern='^(open|done)$')


class ParseInput(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    timezone: str = Field(default=DEFAULT_TZ, max_length=80)
    now: str | None = None


def require_auth(req: Request):
    try:
        value = signer.loads(req.cookies.get(COOKIE, ''), max_age=60 * 60 * 24 * 30)
        if value != 'owner':
            raise ValueError()
    except (BadSignature, SignatureExpired, ValueError):
        raise HTTPException(status_code=401, detail='Login required')
    if req.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = req.headers.get('origin')
        # Same-origin browser requests include Origin for POST; native WebView may omit it.
        if origin:
            host = req.headers.get('x-forwarded-host') or req.headers.get('host') or ''
            if origin.split('://', 1)[-1].rstrip('/') != host:
                raise HTTPException(status_code=403, detail='Cross-origin request rejected')


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def validated_date(value: str | None):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timezone required')
        return parsed.astimezone(dt.timezone.utc).isoformat()
    except ValueError:
        raise HTTPException(422, 'due_at must be ISO 8601 with timezone')


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/assets/{filename}')
def asset(filename: str):
    if '/' in filename or '..' in filename:
        raise HTTPException(404)
    p = ROOT / 'static' / 'assets' / filename
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, headers={'Cache-Control': 'no-store'})


@app.post('/api/login')
def login(data: Login, req: Request, resp: Response):
    ip = req.client.host if req.client else 'unknown'
    stamp = time.monotonic()
    failed_logins[ip] = [t for t in failed_logins.get(ip, []) if stamp - t < 600]
    if len(failed_logins[ip]) >= 8:
        raise HTTPException(429, 'Try again later')
    if not secrets.compare_digest(data.password.encode(), PASSWORD.encode()):
        failed_logins[ip].append(stamp)
        raise HTTPException(401, 'Wrong password')
    failed_logins.pop(ip, None)
    resp.set_cookie(COOKIE, signer.dumps('owner'), max_age=30 * 86400,
                    httponly=True, secure=COOKIE_SECURE, samesite='strict', path='/')
    return {'ok': True}


@app.post('/api/logout')
def logout(req: Request, resp: Response):
    require_auth(req)
    resp.delete_cookie(COOKIE, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict')
    return {'ok': True}


@app.get('/api/me')
def me(req: Request):
    require_auth(req)
    return {'ok': True, 'ai_enabled': bool(OPENAI_KEY)}


@app.get('/api/items')
def items(req: Request):
    require_auth(req)
    with db() as con:
        rows = con.execute('SELECT * FROM items ORDER BY created_at DESC LIMIT 1500').fetchall()
    return {'items': [dict(x) for x in rows]}


@app.post('/api/items', status_code=201)
def create_item(req: Request, body: ItemInput):
    require_auth(req)
    due = validated_date(body.due_at)
    if body.kind == 'reminder' and not due:
        raise HTTPException(422, 'A reminder requires a specific date and time')
    item_id, stamp = secrets.token_hex(12), now_iso()
    with db() as con:
        con.execute('INSERT INTO items(id,kind,title,detail,due_at,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                    (item_id, body.kind, body.title.strip(), body.detail, due, 'open', stamp, stamp))
        row = con.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
    return dict(row)


@app.patch('/api/items/{item_id}')
def edit_item(item_id: str, req: Request, body: ItemPatch):
    require_auth(req)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(400, 'No updates')
    if 'due_at' in values:
        values['due_at'] = validated_date(values['due_at'])
    with db() as con:
        old = con.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
        if not old:
            raise HTTPException(404, 'Item not found')
        merged = {**dict(old), **values}
        if merged['kind'] == 'reminder' and not merged['due_at']:
            raise HTTPException(422, 'A reminder requires due_at')
        values['updated_at'] = now_iso()
        assignments = ', '.join(f'{k}=?' for k in values)
        con.execute(f'UPDATE items SET {assignments} WHERE id=?', (*values.values(), item_id))
        row = con.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
    return dict(row)


@app.delete('/api/items/{item_id}')
def delete_item(item_id: str, req: Request):
    require_auth(req)
    with db() as con:
        con.execute('DELETE FROM items WHERE id=?', (item_id,))
    return {'ok': True}


@app.post('/api/transcribe')
async def transcribe(req: Request, audio: UploadFile = File(...)):
    require_auth(req)
    if not OPENAI_KEY:
        raise HTTPException(503, 'OPENAI_API_KEY has not been configured')
    if (audio.content_type or '').split(';')[0] not in ('audio/mp4', 'audio/webm', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/wav', 'audio/x-m4a', 'application/octet-stream'):
        raise HTTPException(415, 'Unsupported audio format')
    content = await audio.read(AUDIO_LIMIT + 1)
    if len(content) > AUDIO_LIMIT:
        raise HTTPException(413, 'Recording is too large (12 MB max)')
    if len(content) < 300:
        raise HTTPException(422, 'Recording is too short')
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post('https://api.openai.com/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {OPENAI_KEY}'},
                data={'model': os.getenv('TRANSCRIBE_MODEL', 'gpt-4o-transcribe'), 'language': 'fa'},
                files={'file': (audio.filename or 'voice.m4a', content, audio.content_type or 'audio/mp4')})
            r.raise_for_status()
            return {'text': r.json().get('text', '').strip()}
    except httpx.HTTPError:
        raise HTTPException(502, 'Transcription provider is unavailable')


def basic_parse(text: str, now: dt.datetime):
    """Conservative fallback. Never fabricate a missing deadline."""
    norm = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    is_remind = bool(re.search(r'یادم بنداز|یادآوری کن|یادم بیار|بهم یادآوری کن', norm))
    is_idea = bool(re.search(r'ایده|به ذهنم رسید', norm))
    is_task = bool(re.search(r'باید|کار جدید|انجام بدم|وظیفه', norm))
    kind = 'reminder' if is_remind else 'idea' if is_idea else 'task' if is_task else 'note'
    due_at = None
    day_shift = 1 if 'فردا' in norm else 2 if 'پس‌فردا' in norm or 'پس فردا' in norm else 0
    day_found = bool(day_shift or 'امروز' in norm)
    m = re.search(r'ساعت\s*(\d{1,2})(?:[:٫](\d{1,2}))?', norm)
    if m and day_found:
        h, minute = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= minute < 60:
            if 'عصر' in norm or 'شب' in norm:
                h = h + 12 if 1 <= h <= 11 else h
            if 'صبح' in norm and h == 12:
                h = 0
            point = (now + dt.timedelta(days=day_shift)).replace(hour=h, minute=minute, second=0, microsecond=0)
            if point > now:
                due_at = point.isoformat()
    # Only create a reminder if an actual supported timestamp is established.
    if kind == 'reminder' and not due_at:
        kind = 'task'
    return {'kind': kind, 'title': text.strip(), 'detail': '', 'due_at': due_at,
            'needs_clarification': is_remind and not due_at,
            'clarification': 'چه روز و ساعتی یادآوری کنم؟' if is_remind and not due_at else None,
            'source': 'basic'}


@app.post('/api/parse')
async def parse(req: Request, body: ParseInput):
    require_auth(req)
    try:
        zone = ZoneInfo(body.timezone)
    except (KeyError, ValueError):
        raise HTTPException(422, 'Invalid timezone')
    now = dt.datetime.now(zone)
    if body.now:
        try:
            supplied = dt.datetime.fromisoformat(body.now.replace('Z', '+00:00'))
            if supplied.tzinfo:
                now = supplied.astimezone(zone)
        except ValueError:
            pass
    result = basic_parse(body.text, now)
    if not OPENAI_KEY:
        return result
    system_prompt = ("You are an accurate Persian-language personal assistant. Convert a user's voice transcript into exactly one structured object. "
       "Type must be reminder, task, note, or idea. Interpret Persian colloquial dates and time relative to the provided CURRENT date/time and IANA timezone. "
       "For a reminder supply due_at as ISO 8601 with numeric timezone offset ONLY if the user stated an unambiguous actionable date and time. "
       "If date/time is vague or absent, set due_at null, kind task, needs_clarification true when reminder was requested, and ask a concise Persian clarification. "
       "Do not invent dates or times. A normal task, idea, or note must not get an auto-created deadline. Avoid omitting details from the transcript. "
       "Output a JSON object with keys kind,title,detail,due_at,needs_clarification,clarification.")
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            r = await client.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {OPENAI_KEY}'},
                json={'model': os.getenv('PARSE_MODEL', 'gpt-4.1-mini'), 'temperature': 0,
                  'response_format': {'type': 'json_object'},
                  'messages': [{'role': 'system', 'content': system_prompt},
                               {'role': 'user', 'content': f'CURRENT: {now.isoformat()}\nTIMEZONE: {body.timezone}\nTRANSCRIPT: {body.text}'}]})
            r.raise_for_status()
            parsed = json.loads(r.json()['choices'][0]['message']['content'])
            if parsed.get('kind') not in ('reminder', 'task', 'note', 'idea'):
                return result
            due = parsed.get('due_at')
            if due:
                try:
                    deadline = dt.datetime.fromisoformat(due.replace('Z', '+00:00'))
                    if deadline.tzinfo is None or deadline <= now.astimezone(dt.timezone.utc):
                        due = None
                except (ValueError, TypeError):
                    due = None
            if parsed['kind'] == 'reminder' and not due:
                parsed['kind'] = 'task'
                parsed['needs_clarification'] = True
                parsed['clarification'] = parsed.get('clarification') or 'چه روز و ساعتی یادآوری کنم؟'
            return {'kind': parsed['kind'], 'title': str(parsed.get('title') or body.text)[:500],
                    'detail': str(parsed.get('detail') or '')[:8000], 'due_at': due,
                    'needs_clarification': bool(parsed.get('needs_clarification')),
                    'clarification': parsed.get('clarification'), 'source': 'ai'}
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return result
