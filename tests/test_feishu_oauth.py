"""Administrator OAuth callback binding, encrypted tokens and refresh behavior."""
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.db import connect
from test_system import client, login


def root_login(client):
    response = client.post('/api/login', json={'username': 'root', 'password': 'root'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}


def prepare(client):
    headers = root_login(client)
    response = client.patch('/api/admin/feishu-settings', headers=headers, json={
        'app_id': 'cli_oauth_test', 'app_secret': 'oauth-app-secret',
        'redirect_uri': 'http://127.0.0.1:8000/api/feishu/oauth/callback',
    })
    assert response.status_code == 200
    return headers


def begin(client, headers):
    response = client.post('/api/feishu/oauth/connect', headers=headers)
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()['authorization_url']).query)
    assert set(query['scope'][0].split()) == {'docs:permission.member:create', 'offline_access'}
    assert query['code_challenge_method'] == ['S256']
    return query['state'][0]


def provider(monkeypatch, *, expires=7200, scopes=None):
    from app.services import feishu_oauth
    calls = []
    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://accounts.feishu.cn/oauth/v3/token'
        return httpx.Response(200, json={
            'code': 0, 'access_token': 'private-access-' + str(len(calls)), 'expires_in': expires,
            'refresh_token': 'private-refresh-' + str(len(calls)), 'refresh_token_expires_in': 604800,
            'scope': scopes if scopes is not None else 'docs:permission.member:create offline_access',
        })
    factory = httpx.Client
    monkeypatch.setattr(feishu_oauth, '_client', lambda: factory(transport=httpx.MockTransport(handle)))
    return calls


def test_oauth_management_requires_superadmin(client):
    for name, expected in [('alice', 403), ('manager', 403)]:
        headers = login(client, name)
        assert client.post('/api/feishu/oauth/connect', headers=headers).status_code == expected
        assert client.delete('/api/feishu/oauth/connection', headers=headers).status_code == expected
    assert client.get('/api/feishu/oauth/status').status_code == 401


def test_callback_is_bound_to_browser_and_session_and_is_single_use(client, monkeypatch):
    headers = prepare(client)
    calls = provider(monkeypatch)
    state = begin(client, headers)
    binding = client.cookies.get('feishu_oauth_binding')
    assert binding
    client.cookies.clear()
    failed = client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    assert failed.status_code == 400 and not calls
    client.cookies.set('feishu_oauth_binding', binding)
    response = client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/admin#view=systemSettings'
    assert len(calls) == 1
    payload = parse_qs(calls[0].content.decode())
    assert payload['grant_type'] == ['authorization_code'] and payload['code'] == ['test-code']
    status = client.get('/api/feishu/oauth/status', headers=headers)
    assert status.json()['connected'] is True
    assert 'private-' not in status.text and 'oauth-app-secret' not in status.text
    with connect() as db:
        raw = db.execute("SELECT value FROM app_settings WHERE key='feishu_oauth_connection'").fetchone()[0]
    assert 'private-access' not in raw and 'private-refresh' not in raw
    repeated = client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    assert repeated.status_code == 400 and len(calls) == 1


@pytest.mark.parametrize('reason', ['expired', 'logout', 'changed_app', 'disconnect'])
def test_stale_callback_never_exchanges_code(client, monkeypatch, reason):
    headers = prepare(client)
    calls = provider(monkeypatch)
    state = begin(client, headers)
    with connect() as db:
        if reason == 'expired':
            row = db.execute("SELECT value FROM app_settings WHERE key='feishu_oauth_pending'").fetchone()
            pending = json.loads(row[0]); pending['expires_at'] = time.time() - 1
            db.execute("UPDATE app_settings SET value=? WHERE key='feishu_oauth_pending'", (json.dumps(pending),))
        if reason == 'logout':
            db.execute('DELETE FROM sessions WHERE token=?', (headers['Authorization'][7:],))
    if reason == 'changed_app':
        client.patch('/api/admin/feishu-settings', headers=headers, json={'app_id': 'cli_other'})
    if reason == 'disconnect':
        client.delete('/api/feishu/oauth/connection', headers=headers)
    response = client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    assert response.status_code == 400 and not calls


def test_refresh_rotates_once_and_failed_refresh_does_not_fallback(client, monkeypatch):
    from app.services import feishu_oauth, feishu_permissions
    headers = prepare(client)
    calls = provider(monkeypatch, expires=1)
    state = begin(client, headers)
    assert client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False).status_code == 303
    assert feishu_oauth.access_token() == 'private-access-2'
    assert parse_qs(calls[1].content.decode())['refresh_token'] == ['private-refresh-1']
    factory = httpx.Client
    monkeypatch.setattr(feishu_oauth, '_client', lambda: factory(transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={'code': 20026, 'error_description': 'private-refresh-2'}))))
    monkeypatch.setattr(feishu_permissions, '_application_token', lambda: pytest.fail('must not fall back'))
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'also-must-not-fallback')
    with pytest.raises(feishu_permissions.GrantError, match='重新连接') as error:
        feishu_permissions.grant({'url': 'https://my.feishu.cn/docx/TestDoc', 'permission': 'view'},
                                 {'member_type': 'email', 'member_id': 'student@example.com'})
    assert 'private-' not in str(error.value)
    assert client.get('/api/feishu/oauth/status', headers=headers).json()['needs_reconnect'] is True


def test_partial_consent_does_not_create_connection(client, monkeypatch):
    headers = prepare(client)
    provider(monkeypatch, scopes='offline_access')
    state = begin(client, headers)
    response = client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    assert response.status_code == 400
    assert client.get('/api/feishu/oauth/status', headers=headers).json()['connected'] is False


def test_callback_url_rejects_non_loopback_http_and_query(client):
    headers = root_login(client)
    for url in ['http://example.com/api/feishu/oauth/callback', 'https://example.com/cb?token=secret',
                'https://user:password@example.com/cb', 'https://example.com/cb#frag']:
        assert client.patch('/api/admin/feishu-settings', headers=headers, json={'redirect_uri': url}).status_code == 422


def test_concurrent_refresh_uses_rotated_token_once(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.services import feishu_oauth
    headers = prepare(client)
    calls = provider(monkeypatch)
    state = begin(client, headers)
    client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    with connect() as db:
        record = feishu_oauth._read(db, feishu_oauth.CONNECTION_KEY)
        from app.services.password_vault import decrypt_password, encrypt_password
        tokens = json.loads(decrypt_password(record['tokens_encrypted']))
        tokens['expires_at'] = time.time() - 1
        record['tokens_encrypted'] = encrypt_password(json.dumps(tokens))
        feishu_oauth._write(db, feishu_oauth.CONNECTION_KEY, record)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: feishu_oauth.access_token(), range(4)))
    assert results == ['private-access-2'] * 4 and len(calls) == 2


def test_backup_excludes_oauth_credentials_and_pending_consent(client):
    import io
    import zipfile
    from app.services import backups
    with connect() as db:
        for key in ('feishu_oauth_connection', 'feishu_oauth_pending'):
            db.execute('INSERT INTO app_settings(key,value) VALUES (?,?)', (key, '{"secret":"must-not-export"}'))
        data, _ = backups.build_backup(db, ['settings'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        settings = archive.read('settings/app_settings.json').decode()
    assert 'feishu_oauth_' not in settings and 'must-not-export' not in settings


def test_oauth_callback_access_log_has_no_code_or_state():
    import logging
    from app.services.feishu_oauth import CallbackLogFilter
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1', 'GET', '/api/feishu/oauth/callback?code=private-code&state=private-state', '1.1', 303), None)
    assert CallbackLogFilter().filter(record)
    assert 'private-' not in record.getMessage()


def test_maintenance_refreshes_a_connected_account(client, monkeypatch):
    from app.services import feishu_oauth
    headers = prepare(client)
    calls = provider(monkeypatch, expires=1)
    state = begin(client, headers)
    client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    feishu_oauth.maintain()
    assert len(calls) == 2


def test_connected_user_identity_is_used_for_document_grants(client, monkeypatch):
    from app.services import feishu_permissions
    headers = prepare(client)
    provider(monkeypatch)
    state = begin(client, headers)
    client.get('/api/feishu/oauth/callback', params={'state': state, 'code': 'test-code'}, follow_redirects=False)
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'unused-environment-token')
    monkeypatch.setattr(feishu_permissions, '_application_token', lambda: pytest.fail('must use connected account'))
    factory = httpx.Client
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer private-access-1'
        return httpx.Response(200, json={'code': 0})
    monkeypatch.setattr(feishu_permissions, '_client', lambda: factory(transport=httpx.MockTransport(handle)))
    feishu_permissions.grant({'url': 'https://my.feishu.cn/docx/TestDoc', 'permission': 'view'},
                             {'member_type': 'email', 'member_id': 'student@example.com'})
    assert len(requests) == 1
