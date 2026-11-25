"""Administrator management of encrypted Feishu application credentials."""
import json

from app.db import connect
from app.services import feishu_settings
from test_system import client, login


def test_feishu_app_secret_is_encrypted_and_never_returned(client, monkeypatch):
    admin, student = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/admin/feishu-settings', headers=student).status_code == 403

    secret = 'feishu-secret-for-test-only'
    response = client.patch('/api/admin/feishu-settings', headers=admin, json={
        'app_id': 'cli_test_app', 'app_secret': secret,
    })
    assert response.status_code == 200, response.text
    assert secret not in response.text
    assert response.json() == {'app_id': 'cli_test_app', 'app_secret_configured': True,
                               'credential_source': '后台设置',
                               'redirect_uri': 'http://127.0.0.1:8000/api/feishu/oauth/callback'}

    with connect() as db:
        encoded = db.execute("SELECT value FROM app_settings WHERE key='feishu_credentials'").fetchone()['value']
    stored = json.loads(encoded)
    assert secret not in encoded and stored['app_secret_encrypted'] != secret
    monkeypatch.delenv('FEISHU_APP_ID', raising=False)
    monkeypatch.delenv('FEISHU_APP_SECRET', raising=False)
    assert feishu_settings.credentials()['app_id'] == 'cli_test_app'
    assert feishu_settings.credentials()['app_secret'] == secret

    read = client.get('/api/admin/feishu-settings', headers=admin)
    assert read.status_code == 200 and secret not in read.text
    assert read.json()['app_secret_configured'] is True


def test_feishu_app_secret_can_be_kept_or_cleared(client, monkeypatch):
    admin = login(client, 'manager')
    monkeypatch.delenv('FEISHU_APP_SECRET', raising=False)
    first = client.patch('/api/admin/feishu-settings', headers=admin, json={
        'app_id': 'cli_test_app', 'app_secret': 'keep-this-secret',
    })
    assert first.status_code == 200, first.text
    unchanged = client.patch('/api/admin/feishu-settings', headers=admin, json={'app_id': 'cli_updated_app'})
    assert unchanged.status_code == 200 and feishu_settings.credentials()['app_secret'] == 'keep-this-secret'
    cleared = client.patch('/api/admin/feishu-settings', headers=admin, json={'clear_app_secret': True})
    assert cleared.status_code == 200 and cleared.json()['app_secret_configured'] is False
    assert feishu_settings.credentials()['app_secret'] == ''


def test_feishu_app_secret_rejects_conflicting_or_invalid_updates(client):
    admin = login(client, 'manager')
    assert client.patch('/api/admin/feishu-settings', headers=admin,
                        json={'app_secret': 'secret', 'clear_app_secret': True}).status_code == 422
    assert client.patch('/api/admin/feishu-settings', headers=admin,
                        json={'app_secret': 'bad\nsecret'}).status_code == 422
