"""Feishu administrator consent with browser binding and encrypted rotating tokens."""
import base64
import hashlib
import json
import logging
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import httpx

from app.db import connect
from app.services import feishu_settings
from app.services.password_vault import decrypt_password, encrypt_password

AUTHORIZE_URL = 'https://accounts.feishu.cn/open-apis/authen/v1/authorize'
TOKEN_URL = 'https://accounts.feishu.cn/oauth/v3/token'
SCOPES = frozenset(('docs:permission.member:create', 'offline_access'))
CONNECTION_KEY = 'feishu_oauth_connection'
PENDING_KEY = 'feishu_oauth_pending'
TRANSIENT_KEYS = (CONNECTION_KEY, PENDING_KEY)
_refresh_lock = threading.Lock()
_stop = threading.Event()
_thread = None


class OAuthError(RuntimeError):
    """A safe authorization failure that contains no provider tokens or codes."""


def _read(db, key):
    row = db.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else {}


def _write(db, key, value):
    db.execute('INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (key, json.dumps(value, ensure_ascii=False)))


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def validate_redirect_uri(value):
    """Allow HTTPS callbacks and loopback-only HTTP, without credentials or query data."""
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'))
        if (not valid or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path or any(ord(char) <= 32 for char in value)):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ValueError('回调地址必须为 HTTPS（本机调试允许 localhost / 127.0.0.1 HTTP），不能包含账号、查询参数或锚点') from None
    return value


def _fingerprint(db):
    config = feishu_settings.credentials(db)
    return _digest(json.dumps([config['app_id'], config['app_secret'], feishu_settings.redirect_uri(db)]))


def disconnect(db):
    """Invalidate pending callbacks and the local connection without altering document grants."""
    db.execute('DELETE FROM app_settings WHERE key=?', (PENDING_KEY,))
    _write(db, CONNECTION_KEY, {'generation': secrets.token_urlsafe(24)})


def status(db):
    """Return connection health without exposing tokens, codes or recipient information."""
    record = _read(db, CONNECTION_KEY)
    configured = bool(record.get('tokens_encrypted'))
    stale = configured and record.get('fingerprint') != _fingerprint(db)
    expired = configured and record.get('refresh_expires_at', 0) <= time.time()
    reconnect = bool(configured and (record.get('needs_reconnect') or stale or expired))
    return {'connected': bool(configured and not reconnect), 'needs_reconnect': reconnect,
            'connected_at': record.get('connected_at'), 'refresh_expires_at': record.get('refresh_expires_at'),
            'redirect_uri': feishu_settings.redirect_uri(db),
            'message': '授权已失效，请重新连接飞书资料管理账号' if reconnect else
                       '已连接，文档授权将使用该账号的身份' if configured else '尚未连接飞书资料管理账号'}


def begin(user_id, session_token):
    """Create one ten-minute consent attempt bound to the initiating browser and session."""
    state, binding, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        config = feishu_settings.credentials(db)
        if not config['app_id'] or not config['app_secret']:
            raise OAuthError('请先保存飞书 App ID 和 App Secret')
        redirect = validate_redirect_uri(feishu_settings.redirect_uri(db))
        record = _read(db, CONNECTION_KEY)
        _write(db, PENDING_KEY, {'state_hash': _digest(state), 'binding_hash': _digest(binding),
                                'verifier_encrypted': encrypt_password(verifier), 'user_id': user_id,
                                'session_hash': _digest(session_token), 'fingerprint': _fingerprint(db),
                                'generation': record.get('generation'), 'expires_at': time.time() + 600,
                                'redirect_uri': redirect})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    url = AUTHORIZE_URL + '?' + urlencode({'client_id': config['app_id'], 'response_type': 'code',
          'redirect_uri': redirect, 'scope': ' '.join(sorted(SCOPES)), 'state': state,
          'code_challenge': challenge, 'code_challenge_method': 'S256'})
    return url, binding, redirect.startswith('https:')


def _session_valid(db, attempt):
    sessions = db.execute('''SELECT token FROM sessions JOIN users ON users.id=sessions.user_id
        WHERE users.id=? AND users.is_active=1 AND users.is_superadmin=1 AND users.is_admin=1 AND expires>?''',
        (attempt['user_id'], time.time())).fetchall()
    return any(secrets.compare_digest(_digest(row['token']), attempt['session_hash']) for row in sessions)


def _client():
    return httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False, trust_env=False)


def _exchange(config, parameters):
    try:
        with _client() as client:
            response = client.post(TOKEN_URL, data={'client_id': config['app_id'],
                'client_secret': config['app_secret'], **parameters})
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise OAuthError('飞书授权请求未完成，请检查网络并重新连接') from None
    if not isinstance(data, dict) or not response.is_success or data.get('code', 0) != 0 or data.get('error'):
        raise OAuthError('飞书未接受授权或续期请求，请检查应用配置并重新连接')
    if (not isinstance(data.get('scope'), str) or not SCOPES.issubset(data['scope'].split())
            or not all(isinstance(data.get(key), str) and data[key] for key in ('access_token', 'refresh_token'))
            or not all(type(data.get(key)) is int and data[key] > 0 for key in ('expires_in', 'refresh_token_expires_in'))):
        raise OAuthError('飞书授权未包含文档协作者和离线访问权限，请检查权限后重新连接')
    return {'access_token': data['access_token'], 'refresh_token': data['refresh_token'],
            'expires_at': time.time() + data['expires_in'],
            'refresh_expires_at': time.time() + data['refresh_token_expires_in']}


def complete(state, binding, code):
    """Consume a valid callback once, then save tokens only if its session is still valid."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        attempt = _read(db, PENDING_KEY)
        if (not state or not binding or not attempt
                or not secrets.compare_digest(attempt['state_hash'], _digest(state))
                or not secrets.compare_digest(attempt['binding_hash'], _digest(binding))):
            raise OAuthError('授权校验失败，请从系统设置重新连接飞书')
        db.execute('DELETE FROM app_settings WHERE key=?', (PENDING_KEY,))
        valid = attempt['expires_at'] > time.time() and _session_valid(db, attempt) and attempt['fingerprint'] == _fingerprint(db)
        config = feishu_settings.credentials(db)
    if not valid or not code:
        raise OAuthError('授权已取消、过期或登录状态发生变化，请重新连接')
    tokens = _exchange(config, {'grant_type': 'authorization_code', 'code': code,
                       'redirect_uri': attempt['redirect_uri'],
                       'code_verifier': decrypt_password(attempt['verifier_encrypted'])})
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = _read(db, CONNECTION_KEY)
        if (not _session_valid(db, attempt) or attempt['fingerprint'] != _fingerprint(db)
                or current.get('generation') != attempt['generation']):
            raise OAuthError('授权期间配置或登录状态已变化，请重新连接')
        _write(db, CONNECTION_KEY, {'generation': secrets.token_urlsafe(24),
               'fingerprint': attempt['fingerprint'], 'connected_at': time.time(),
               'tokens_encrypted': encrypt_password(json.dumps(tokens)),
               'refresh_expires_at': tokens['refresh_expires_at']})


def access_token():
    """Resolve a connected user token; a broken connection never falls back to app identity."""
    with _refresh_lock:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = _read(db, CONNECTION_KEY)
            if not record.get('tokens_encrypted'):
                return None
            if status(db)['needs_reconnect']:
                raise OAuthError('飞书资料管理账号授权已失效，请在系统设置重新连接')
            tokens = json.loads(decrypt_password(record['tokens_encrypted']))
            if tokens['expires_at'] > time.time() + 60:
                return tokens['access_token']
            config = feishu_settings.credentials(db)
            # A crash or unknown refresh outcome must require consent, never reuse a consumed refresh token.
            record['needs_reconnect'] = True
            _write(db, CONNECTION_KEY, record)
        renewed = _exchange(config, {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']})
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = _read(db, CONNECTION_KEY)
            if (current.get('generation') != record['generation'] or record['fingerprint'] != _fingerprint(db)):
                raise OAuthError('飞书授权设置已变化，请重新连接')
            record.update(tokens_encrypted=encrypt_password(json.dumps(renewed)),
                          refresh_expires_at=renewed['refresh_expires_at'], needs_reconnect=False)
            _write(db, CONNECTION_KEY, record)
        return renewed['access_token']


class CallbackLogFilter(logging.Filter):
    """Remove OAuth authorization codes and state from Uvicorn access log URLs."""
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].split('?')[0] == '/api/feishu/oauth/callback':
                args[2] = '/api/feishu/oauth/callback'
                record.args = tuple(args)
        return True


def maintain():
    """Renew an active connection without adding collaborators or issuing local benefits."""
    with connect() as db:
        active = status(db)['connected']
    if active:
        access_token()


def _run():
    while not _stop.is_set():
        try:
            maintain()
        except Exception:
            # Never log provider exception details; the settings page exposes safe connection status.
            logging.getLogger(__name__).warning('Feishu connection maintenance failed; check administrator settings')
        if _stop.wait(60):
            return


def start():
    """Keep consent refreshed while the server runs, including periods with no grant requests."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name='feishu-oauth-maintenance', daemon=True)
    _thread.start()


def stop():
    """Stop periodic maintenance; allow the bounded provider request to finish on shutdown."""
    _stop.set()
    if _thread:
        _thread.join(timeout=20)
