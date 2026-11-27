from app.db import SCHEMA_VERSION
"""Email delivery is mocked; account creation, storage, expiry, and races use SQLite."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import smtplib
import threading

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient


def test_email_defaults_are_disabled_and_use_qq_tls(tmp_path, monkeypatch):
    from app.config import load_config
    path = tmp_path / 'config.toml'
    path.write_text(Path('config.example.toml').read_text())
    monkeypatch.setenv('SCU_CONFIG', str(path))
    config = load_config()['email_auth']
    assert config['enabled'] is False
    assert (config['smtp_host'], config['smtp_port'], config['smtp_security']) == ('smtp.qq.com', 465, 'ssl')


@pytest.fixture
def email_client(tmp_path, monkeypatch):
    from app.config import load_config
    text = Path('config.example.toml').read_text().replace('data/app.db', str(tmp_path / 'email.db'))
    path = tmp_path / 'config.toml'
    path.write_text(text)
    monkeypatch.setenv('SCU_CONFIG', str(path))
    from app.db import initialize
    initialize()
    from app.services import email_auth
    config = load_config()
    settings = config['email_auth']
    settings.update(enabled=True, smtp_username='sender@qq.com', from_email='sender@qq.com', smtp_password='test-smtp-secret')
    monkeypatch.setattr(email_auth, 'load_config', lambda: config)
    clock = [100000.0]
    monkeypatch.setattr(email_auth, '_now', lambda: clock[0])
    delivered, transport = [], []

    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            transport.append(('connect', host, port, kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            transport.append(('ehlo',))

        def starttls(self, **kwargs):
            transport.append(('starttls', kwargs))

        def login(self, username, password):
            transport.append(('login', username, password))

        def send_message(self, message):
            delivered.append(message)
            return {}

    monkeypatch.setattr(email_auth.smtplib, 'SMTP_SSL', FakeSMTP)
    monkeypatch.setattr(email_auth.smtplib, 'SMTP', FakeSMTP)
    from app.routes.email_auth import router
    from app.routes.referrals import router as referrals_router
    from app.services.auth import current_user
    app = FastAPI()
    app.include_router(router)
    app.include_router(referrals_router)

    @app.get('/me')
    def me(user=Depends(current_user)):
        return user

    with TestClient(app) as client:
        yield client, settings, delivered, transport, clock


def send(client, email='student@example.com', **kwargs):
    return client.post('/api/auth/email/code', json={'email': email}, **kwargs)


def code(message):
    return re.search(r'\b[0-9]{6}\b', message.get_content()).group()


def login(client, value, email='student@example.com'):
    return client.post('/api/auth/email/login', json={'email': email, 'code': value})


@pytest.mark.parametrize(('entered_email', 'email'), [
    (' Student@Example.COM ', 'student@example.com'),
    (' 123456789@QQ.COM ', '123456789@qq.com'),
])
def test_email_creates_normal_account_with_current_default_and_single_use(email_client, entered_email, email):
    from app.db import connect
    from app.services.security import verify_password
    client, settings, messages, _, clock = email_client
    with connect() as db:
        db.execute("UPDATE app_settings SET value='4' WHERE key='default_points'")
    sent = send(client, entered_email)
    assert sent.status_code == 200 and sent.json()['retry_after'] == settings['resend_seconds']
    value = code(messages[-1])
    assert len(value) == 6
    with connect() as db:
        challenge = db.execute('SELECT * FROM email_challenges').fetchone()
        assert challenge['code_hash'] != value and len(challenge['code_hash']) > 64
        assert not db.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone()
    result = login(client, value, email)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['is_admin'] is False and body['is_superadmin'] is False
    assert body['can_interview'] is True and body['can_exam'] is True
    assert body['can_training'] is False and body['can_coding'] is False
    assert body['interview_credits'] == 0
    assert body['points'] == 4
    assert body['email'] == email
    assert body['username'] == email
    assert not {'password', 'password_ciphertext', 'code_hash'} & body.keys()
    assert client.get('/me', headers={'Authorization': 'Bearer ' + body['token']}).status_code == 200
    with connect() as db:
        user = db.execute('SELECT * FROM users WHERE id=?', (body['id'],)).fetchone()
        from app.services.password_vault import decrypt_password
        generated = decrypt_password(user['password_ciphertext'])
        assert len(generated) >= 48 and verify_password(generated, user['password'])
        assert generated != value
        ledger = db.execute('SELECT * FROM points_ledger WHERE user_id=?', (body['id'],)).fetchall()
        assert len(ledger) == 1 and ledger[0]['kind'] == 'initial'
        assert ledger[0]['delta'] == 4 and ledger[0]['balance_after'] == 4
    assert login(client, value, email).status_code == 401
    with connect() as db:
        db.execute('UPDATE users SET can_interview=0,can_exam=0,can_training=1,can_coding=1,can_practice=1 WHERE id=?',
                   (body['id'],))
    clock[0] += settings['resend_seconds']
    assert send(client, email).status_code == 200
    again = login(client, code(messages[-1]), email)
    assert again.status_code == 200 and again.json()['id'] == body['id']
    assert again.json()['points'] == 4
    assert again.json()['can_interview'] is False and again.json()['can_exam'] is False
    assert again.json()['can_training'] is True and again.json()['can_coding'] is True
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM points_ledger WHERE user_id=?', (body['id'],)).fetchone()[0] == 1


def test_invite_registration_rewards_referrer_once_and_keeps_referral_history(email_client):
    from app.db import connect
    client, settings, messages, _, clock = email_client
    from app.services.auth import issue_session
    with connect() as db:
        inviter_id = db.execute("SELECT id FROM users WHERE username='root'").fetchone()[0]
        code_value = db.execute('SELECT invite_code FROM users WHERE id=?', (inviter_id,)).fetchone()[0]
        inviter_token = issue_session(db, inviter_id)
    sent = send(client, 'newperson@example.com')
    created = client.post('/api/auth/email/login', json={
        'email': 'newperson@example.com', 'code': code(messages[-1]), 'invitation_code': code_value,
    })
    assert sent.status_code == 200 and created.status_code == 200
    assert client.post('/api/admin/users/' + str(created.json()['id']) + '/package-purchases',
        headers={'Authorization': 'Bearer ' + created.json()['token']}, json={'package_id': 1}).status_code == 403
    clock[0] += settings['resend_seconds']
    assert send(client, 'newperson@example.com').status_code == 200
    repeated = client.post('/api/auth/email/login', json={
        'email': 'newperson@example.com', 'code': code(messages[-1]), 'invitation_code': code_value,
    })
    assert repeated.status_code == 200
    with connect() as db:
        assert db.execute('SELECT referrer_id FROM users WHERE email=?', ('newperson@example.com',)).fetchone()[0] == inviter_id
        assert db.execute("SELECT SUM(delta) FROM points_ledger WHERE user_id=? AND kind='invite_signup'", (inviter_id,)).fetchone()[0] == 3
    headers = {'Authorization': f'Bearer {inviter_token}'}
    referrals = client.get('/api/profile/referrals', headers=headers)
    assert referrals.status_code == 200 and referrals.json()['total_invited'] == 1
    assert referrals.json()['items'][0]['username'] == 'newperson@example.com'
    assert referrals.json()['items'][0]['purchase_total_fen'] == 0
    package = client.post('/api/admin/service-packages', headers=headers,
                         json={'name': '套餐服务', 'price_yuan': '200'}).json()
    changed = client.post('/api/admin/users/' + str(created.json()['id']) + '/package-purchases', headers=headers,
                          json={'package_id': package['id']})
    assert changed.status_code == 201
    item = client.get('/api/profile/referrals', headers=headers).json()['items'][0]
    assert item['purchase_total_fen'] == 20000 and item['rebate_total_fen'] == 1000
    settled = client.patch('/api/admin/users/' + str(created.json()['id']) + '/rebate', headers=headers,
                           json={'redeemed': True})
    assert settled.status_code == 200 and settled.json()['rebate_status'] == 'redeemed'
    assert client.get('/api/profile/referrals', headers=headers).json()['items'][0]['rebate_status'] == 'redeemed'


def test_invalid_invitation_code_does_not_prevent_email_registration(email_client):
    client, _, messages, _, _ = email_client
    send(client, 'plain@example.com')
    result = client.post('/api/auth/email/login', json={
        'email': 'plain@example.com', 'code': code(messages[-1]), 'invitation_code': 'not-a-code',
    })
    assert result.status_code == 422


def test_new_email_login_replaces_the_previous_session(email_client):
    client, settings, messages, _, clock = email_client
    assert send(client).status_code == 200
    first = login(client, code(messages[-1])).json()['token']
    clock[0] += settings['resend_seconds'] + 1
    assert send(client).status_code == 200
    second = login(client, code(messages[-1])).json()['token']

    assert client.get('/me', headers={'Authorization': 'Bearer ' + first}).status_code == 401
    assert client.get('/me', headers={'Authorization': 'Bearer ' + second}).status_code == 200


def test_resend_expiry_attempt_limits_and_header(email_client):
    client, settings, messages, _, clock = email_client
    assert send(client).status_code == 200
    original = code(messages[-1])
    cooldown = send(client)
    assert cooldown.status_code == 429 and int(cooldown.headers['retry-after']) > 0
    assert cooldown.json()['detail'] == f"请求过于频繁，请在 {settings['resend_seconds']} 秒后重试"
    clock[0] += 17
    cooldown = send(client)
    assert cooldown.headers['retry-after'] == str(settings['resend_seconds'] - 17)
    assert cooldown.json()['detail'] == f"请求过于频繁，请在 {settings['resend_seconds'] - 17} 秒后重试"
    for _ in range(settings['max_attempts']):
        assert login(client, '000000' if original != '000000' else '111111').status_code == 401
    assert login(client, original).status_code == 401
    clock[0] += settings['resend_seconds']
    assert send(client).status_code == 200
    latest = code(messages[-1])
    clock[0] += settings['code_ttl_seconds']
    assert login(client, latest).status_code == 401


def test_new_code_invalidates_old_code_and_ignores_forwarded_ip(email_client):
    client, settings, messages, _, clock = email_client
    assert send(client).status_code == 200
    old = code(messages[-1])
    clock[0] += settings['resend_seconds']
    assert send(client).status_code == 200
    new = code(messages[-1])
    if new != old:
        assert login(client, old).status_code == 401
    assert login(client, new).status_code == 200
    settings['max_ip_codes'] = 2
    response = send(client, 'other@example.com', headers={'X-Forwarded-For': '192.0.2.9'})
    assert response.status_code == 429


def test_email_and_ip_rate_limits_survive_new_requests(email_client):
    client, settings, _, _, clock = email_client
    settings['max_email_codes'] = 2
    for _ in range(2):
        assert send(client).status_code == 200
        clock[0] += settings['resend_seconds']
    assert send(client).status_code == 429
    settings['max_ip_attempts'] = 2
    assert login(client, '123456', 'unknown@example.com').status_code == 401
    assert login(client, '123456', 'unknown@example.com').status_code == 401
    assert login(client, '123456', 'other@example.com').status_code == 429
    clock[0] += settings['rate_window_seconds']
    assert send(client).status_code == 200
    assert login(client, '123456', 'unknown@example.com').status_code == 401


def test_disabled_missing_credentials_and_delivery_failure_are_actionable(email_client, monkeypatch):
    from app.services import email_auth
    from app.db import connect
    client, settings, messages, _, _ = email_client
    settings['enabled'] = False
    assert client.get('/api/auth/email/settings').json() == {'enabled': False}
    assert send(client).status_code == 503 and messages == []
    settings['enabled'] = True
    settings['smtp_password'] = ''
    monkeypatch.delenv(settings['smtp_password_env'], raising=False)
    assert send(client).status_code == 503 and messages == []
    monkeypatch.setenv(settings['smtp_password_env'], 'environment-secret')
    assert client.get('/api/auth/email/settings').json() == {'enabled': True}

    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b'environment-secret')

    monkeypatch.setattr(email_auth.smtplib, 'SMTP_SSL', fail)
    result = send(client)
    assert result.status_code == 503
    assert 'environment-secret' not in result.text
    with connect() as db:
        assert db.execute('SELECT status FROM email_challenges').fetchone()[0] == 'failed'
    assert login(client, '123456').status_code == 401


def test_generic_starttls_and_environment_credentials(email_client, monkeypatch):
    client, settings, messages, transport, _ = email_client
    settings.update(smtp_host='smtp.exmail.qq.com', smtp_port=587, smtp_security='starttls', smtp_password='')
    monkeypatch.setenv(settings['smtp_password_env'], 'enterprise-authorization-code')
    assert send(client).status_code == 200
    assert transport[0][1:3] == ('smtp.exmail.qq.com', 587)
    assert any(item[0] == 'starttls' and item[1]['context'].check_hostname for item in transport)
    assert ('login', 'sender@qq.com', 'enterprise-authorization-code') in transport
    assert messages[-1]['To'] == 'student@example.com'
    assert messages[-1]['From'].addresses[0].addr_spec == 'sender@qq.com'


@pytest.mark.parametrize('address', ['', 'not-email', 'a\r\nBcc:x@example.com', 'a b@example.com', 'a..b@example.com', 'a@example', 'a@-bad.example'])
def test_rejects_invalid_email_before_sending(email_client, address):
    client, _, messages, _, _ = email_client
    assert send(client, address).status_code == 422
    assert messages == []


def test_existing_username_or_admin_is_not_attached_and_disabled_email_is_refused(email_client):
    from app.db import connect
    client, _, messages, _, _ = email_client
    assert send(client, 'root@example.com').status_code == 200
    registered = login(client, code(messages[-1]), 'root@example.com')
    assert registered.status_code == 200 and registered.json()['is_admin'] is False
    assert registered.json()['username'] != 'root'
    with connect() as db:
        db.execute("UPDATE users SET is_active=0 WHERE email='root@example.com'")
    assert send(client, 'root@example.com').status_code == 403


def test_disabled_between_send_and_login_cannot_create_session(email_client):
    from app.db import connect
    client, settings, messages, _, clock = email_client
    assert send(client).status_code == 200
    account = login(client, code(messages[-1])).json()
    clock[0] += settings['resend_seconds']
    assert send(client).status_code == 200
    with connect() as db:
        db.execute('UPDATE users SET is_active=0 WHERE id=?', (account['id'],))
        before = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    assert login(client, code(messages[-1])).status_code == 403
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == before


def test_code_can_only_be_consumed_once_concurrently(email_client):
    from app.db import connect
    client, _, messages, _, _ = email_client
    assert send(client).status_code == 200
    value = code(messages[-1])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: login(client, value), range(2)))
    assert sorted(result.status_code for result in results) == [200, 401]
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE email='student@example.com'").fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1


def test_smtp_delivery_has_no_write_transaction_and_pending_codes_are_unusable(email_client, monkeypatch):
    from app.db import connect
    from app.services import email_auth
    client, _, messages, _, _ = email_client
    original = email_auth.smtplib.SMTP_SSL
    entered, release = threading.Event(), threading.Event()

    class BlockingSMTP(original):
        def send_message(self, message):
            messages.append(message)
            entered.set()
            assert release.wait(timeout=5)
            return {}

    monkeypatch.setattr(email_auth.smtplib, 'SMTP_SSL', BlockingSMTP)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(send, client)
        assert entered.wait(timeout=5)
        try:
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE app_settings SET value='2' WHERE key='default_points'")
            assert login(client, code(messages[-1])).status_code == 401
            assert send(client).status_code == 429
        finally:
            release.set()
        assert sending.result().status_code == 200
    assert login(client, code(messages[-1])).status_code == 200


def test_schema_14_migration_is_idempotent_and_email_is_unique(email_client):
    from app.db import initialize, connect
    import sqlite3
    with connect() as db:
        db.execute('PRAGMA user_version=12')
    initialize()
    initialize()
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        db.execute("UPDATE users SET email='root@example.com' WHERE username='root'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO users(username,password,email) VALUES ('duplicate','unused','ROOT@EXAMPLE.COM')")


@pytest.mark.parametrize('key,value', [
    ('enabled', 'true'), ('smtp_port', 0), ('smtp_port', True),
    ('smtp_security', 'plain'), ('smtp_host', 'https://smtp.qq.com'),
    ('smtp_username', 'sender\n@qq.com'), ('from_name', 'App\rBcc:'),
    ('code_ttl_seconds', 0), ('code_ttl_seconds', 30), ('max_attempts', 11), ('timeout_seconds', 60),
])
def test_invalid_email_config_fails_at_load(tmp_path, monkeypatch, key, value):
    import json
    from app.config import load_config
    text = Path('config.example.toml').read_text()
    start = text.index('[email_auth]')
    end = text.index('\n[', start + 1)
    section = [line for line in text[start:end].splitlines() if not line.startswith(key + ' =')]
    section.append(f'{key} = {json.dumps(value)}')
    path = tmp_path / 'bad.toml'
    path.write_text(text[:start] + '\n'.join(section) + '\n' + text[end:])
    monkeypatch.setenv('SCU_CONFIG', str(path))
    with pytest.raises(ValueError, match=r'email_auth\.' + key):
        load_config()


def test_two_simultaneous_sends_deliver_only_one_email(email_client):
    client, _, messages, _, _ = email_client
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(client), range(2)))
    assert sorted(result.status_code for result in results) == [200, 429]
    assert len(messages) == 1


def test_legacy_schema_12_upgrade_preserves_account_and_password_login(email_client):
    from app.db import initialize, connect
    from app.services.security import hash_password, verify_password
    with connect() as db:
        db.execute("INSERT INTO users(username,password,interview_credits) VALUES ('legacy',?,7)", (hash_password('old-password'),))
        previous = dict(db.execute("SELECT * FROM users WHERE username='legacy'").fetchone())
        db.execute('DROP TABLE email_challenges')
        db.execute('DROP TABLE email_auth_limits')
        db.execute('DROP INDEX users_email')
        db.execute('ALTER TABLE users DROP COLUMN email')
        db.execute('PRAGMA user_version=12')
    initialize()
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username='legacy'").fetchone()
        assert row['id'] == previous['id'] and row['email'] is None
        assert row['interview_credits'] == 7 and row['password'] == previous['password']
        assert verify_password('old-password', row['password'])
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_provisioned_email_preserves_user_identity_and_role(email_client):
    from app.db import connect
    client, _, messages, _, _ = email_client
    with connect() as db:
        db.execute("UPDATE users SET email='owner@example.com' WHERE username='root'")
        uid = db.execute("SELECT id FROM users WHERE username='root'").fetchone()[0]
    assert send(client, 'OWNER@example.com').status_code == 200
    result = login(client, code(messages[-1]), 'owner@example.com')
    assert result.status_code == 200
    assert result.json()['id'] == uid and result.json()['is_superadmin'] is True


def authenticated(client, messages, email='student@example.com'):
    assert send(client, email).status_code == 200
    result = login(client, code(messages[-1]), email)
    assert result.status_code == 200
    return result.json(), {'Authorization': 'Bearer ' + result.json()['token']}


def test_email_username_collision_fails_without_link_or_rename(email_client):
    from app.db import connect
    client, _, messages, _, _ = email_client
    with connect() as db:
        db.execute("INSERT INTO users(username,password) VALUES ('student@example.com','existing')")
    assert send(client).status_code == 200
    result = login(client, code(messages[-1]))
    assert result.status_code == 409 and '管理员' in result.json()['detail']
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE username='student@example.com'").fetchone()
        assert row['email'] is None and row['password'] == 'existing'
        assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0


def test_rebind_requires_auth_new_mailbox_and_preserves_identity(email_client):
    from app.db import connect
    client, settings, messages, _, clock = email_client
    account, headers = authenticated(client, messages)
    original_session = headers
    clock[0] += settings['resend_seconds']
    assert send(client).status_code == 200
    old_value = code(messages[-1])
    current_token = login(client, old_value).json()['token']
    assert client.get('/me', headers=original_session).status_code == 401
    headers = {'Authorization': 'Bearer ' + current_token}
    clock[0] += settings['resend_seconds']
    assert send(client).status_code == 200
    outstanding_old = code(messages[-1])
    assert send(client, 'new@example.com').status_code == 200
    login_value = code(messages[-1])
    assert client.post('/api/profile/email/code', json={'email': 'new@example.com'}).status_code == 401
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new@example.com'}).status_code == 200
    rebind_value = code(messages[-1])
    assert '换绑' in messages[-1]['Subject']
    if login_value != rebind_value:
        assert client.post('/api/profile/email', headers=headers,
                           json={'email': 'new@example.com', 'code': login_value}).status_code == 400
    result = client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': rebind_value})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['id'] == account['id'] and body['email'] == 'new@example.com'
    assert body['username'] == account['username'] and body['interview_credits'] == account['interview_credits']
    assert body['reauth_required'] is False
    assert client.get('/me', headers=headers).status_code == 200
    assert client.get('/me', headers=original_session).status_code == 401
    assert login(client, outstanding_old).status_code == 401
    assert login(client, login_value, 'new@example.com').status_code == 401
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM points_ledger WHERE user_id=?', (account['id'],)).fetchone()[0] == 1


def test_rebind_is_unique_bound_to_user_and_single_use(email_client):
    client, _, messages, _, _ = email_client
    account, first = authenticated(client, messages)
    _, second = authenticated(client, messages, 'other@example.com')
    assert client.post('/api/profile/email/code', headers=first, json={'email': 'other@example.com'}).status_code == 409
    assert client.post('/api/profile/email/code', headers=first, json={'email': 'new@example.com'}).status_code == 200
    value = code(messages[-1])
    assert client.post('/api/profile/email', headers=second, json={'email': 'new@example.com', 'code': value}).status_code == 400
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/api/profile/email', headers=first,
            json={'email': 'new@example.com', 'code': value}), range(2)))
    assert sorted(result.status_code for result in results) == [200, 400]


def test_security_codes_are_purpose_bound_and_attempt_failures_commit(email_client):
    from app.db import connect
    from app.services.email_auth import consume_account_code
    client, settings, messages, _, clock = email_client
    account, headers = authenticated(client, messages)
    assert client.post('/api/profile/security/code', headers=headers, json={'purpose': 'password'}).status_code == 200
    value = code(messages[-1])
    assert login(client, value).status_code == 401
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert consume_account_code(db, account['id'], 'delete', value).status_code == 400
    wrong = '000000' if value != '000000' else '111111'
    for _ in range(settings['max_attempts']):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            assert consume_account_code(db, account['id'], 'password', wrong).status_code == 400
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert consume_account_code(db, account['id'], 'password', value).status_code == 400
    clock[0] += settings['resend_seconds']
    assert client.post('/api/profile/security/code', headers=headers, json={'purpose': 'password'}).status_code == 200
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert consume_account_code(db, account['id'], 'password', code(messages[-1])) is None
    with connect() as db:
        assert consume_account_code(db, account['id'], 'password', code(messages[-1])).status_code == 400


def test_rebind_code_expiry_attempt_limits_and_current_mailbox_snapshot(email_client):
    from app.db import connect
    client, settings, messages, _, clock = email_client
    account, headers = authenticated(client, messages)
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new@example.com'}).status_code == 200
    value = code(messages[-1])
    wrong = '000000' if value != '000000' else '111111'
    for _ in range(settings['max_attempts']):
        assert client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': wrong}).status_code == 400
    assert client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': value}).status_code == 400
    assert client.get('/me', headers=headers).status_code == 200
    clock[0] += settings['resend_seconds']
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new@example.com'}).status_code == 200
    clock[0] += settings['code_ttl_seconds']
    assert client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': code(messages[-1])}).status_code == 400
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new@example.com'}).status_code == 200
    value = code(messages[-1])
    with connect() as db:
        db.execute("UPDATE users SET email='admin-reassigned@example.com' WHERE id=?", (account['id'],))
    assert client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': value}).status_code == 400


def test_rebind_preserves_superadmin_role_and_invalidates_security_codes(email_client):
    from app.db import connect
    from app.services.email_auth import consume_account_code
    client, _, messages, _, _ = email_client
    with connect() as db:
        db.execute("UPDATE users SET email='owner@example.com' WHERE username='root'")
    account, headers = authenticated(client, messages, 'owner@example.com')
    assert client.post('/api/profile/security/code', headers=headers, json={'purpose': 'delete'}).status_code == 200
    delete_code = code(messages[-1])
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new-owner@example.com'}).status_code == 200
    result = client.post('/api/profile/email', headers=headers, json={'email': 'new-owner@example.com', 'code': code(messages[-1])})
    assert result.status_code == 200 and result.json()['is_superadmin'] is True
    assert result.json()['username'] == 'root'
    with connect() as db:
        assert consume_account_code(db, account['id'], 'delete', delete_code).status_code == 400


def test_rebind_delivery_failure_never_activates_code(email_client, monkeypatch):
    from app.db import connect
    from app.services import email_auth
    client, _, messages, _, _ = email_client
    account, headers = authenticated(client, messages)

    def fail(*args, **kwargs):
        raise smtplib.SMTPServerDisconnected('offline')

    monkeypatch.setattr(email_auth.smtplib, 'SMTP_SSL', fail)
    assert client.post('/api/profile/email/code', headers=headers, json={'email': 'new@example.com'}).status_code == 503
    with connect() as db:
        row = db.execute("SELECT status FROM account_email_challenges WHERE user_id=? AND purpose='rebind'", (account['id'],)).fetchone()
        assert row['status'] == 'failed'
    assert client.post('/api/profile/email', headers=headers, json={'email': 'new@example.com', 'code': '123456'}).status_code == 400
    assert client.get('/me', headers=headers).json()['email'] == 'student@example.com'


def test_schema_13_to_14_adds_purpose_codes_without_rewriting_existing_logins(email_client):
    from app.db import connect, initialize
    client, _, messages, _, _ = email_client
    assert send(client).status_code == 200
    value = code(messages[-1])
    with connect() as db:
        before = dict(db.execute('SELECT * FROM email_challenges').fetchone())
        db.execute('DROP TABLE account_email_challenges')
        db.execute('PRAGMA user_version=13')
    initialize()
    initialize()
    with connect() as db:
        assert dict(db.execute('SELECT * FROM email_challenges').fetchone()) == before
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
    assert login(client, value).status_code == 200


def test_security_malformed_code_counts_as_failed_attempt_without_consuming(email_client):
    from app.db import connect
    from app.services.email_auth import consume_account_code
    client, _, messages, _, _ = email_client
    account, headers = authenticated(client, messages)
    assert client.post('/api/profile/security/code', headers=headers, json={'purpose': 'password'}).status_code == 200
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert consume_account_code(db, account['id'], 'password', 'not-six-digits').status_code == 400
    with connect() as db:
        row = db.execute("SELECT * FROM account_email_challenges WHERE user_id=? AND purpose='password'", (account['id'],)).fetchone()
        assert row['attempts'] == 1 and row['status'] == 'ready'
        assert consume_account_code(db, account['id'], 'password', code(messages[-1])) is None


def test_deleted_highest_email_account_id_is_never_reassigned(email_client):
    from app.db import connect, initialize
    from app.services.account_deletion import delete_account
    client, _, messages, _, _ = email_client
    first, _ = authenticated(client, messages)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        delete_account(db, db.execute('SELECT * FROM users WHERE id=?', (first['id'],)).fetchone())
    initialize()
    initialize()
    second, _ = authenticated(client, messages, 'replacement@example.com')
    assert second['id'] > first['id']
    with connect() as db:
        assert int(db.execute("SELECT value FROM app_settings WHERE key='user_id_highwater'").fetchone()[0]) >= second['id']


def test_legacy_highest_id_seeds_durable_highwater_across_reinitialization(email_client):
    from app.db import connect, initialize
    client, _, messages, _, _ = email_client
    with connect() as db:
        db.execute("INSERT INTO users(id,username,password) VALUES (10000,'imported','unused')")
        db.execute("DELETE FROM app_settings WHERE key='user_id_highwater'")
    initialize()
    with connect() as db:
        db.execute('DELETE FROM users WHERE id=10000')
    initialize()
    initialize()
    result, _ = authenticated(client, messages)
    assert result['id'] > 10000


def test_user_id_allocator_handles_manual_imports_and_transaction_rollback(email_client):
    from app.db import connect, allocate_user_id
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        first = allocate_user_id(db)
        db.execute("INSERT INTO users(id,username,password) VALUES (?,'manual-high','unused')", (first + 100,))
        second = allocate_user_id(db)
        assert second > first + 100
    with pytest.raises(RuntimeError):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rolled_back = allocate_user_id(db)
            raise RuntimeError('abort unused allocation')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert allocate_user_id(db) == rolled_back


def test_empty_database_root_seed_respects_retained_user_id_highwater(email_client):
    from app.db import connect, initialize
    with connect() as db:
        db.execute('DELETE FROM users')
        db.execute("UPDATE app_settings SET value='500' WHERE key='user_id_highwater'")
    initialize()
    initialize()
    with connect() as db:
        root = db.execute("SELECT id FROM users WHERE username='root'").fetchone()
        assert root['id'] == 501
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1


def test_email_signup_receives_three_points_by_default(email_client):
    client, _, messages, _, _ = email_client
    assert send(client).status_code == 200
    result = login(client, code(messages[-1]))
    assert result.status_code == 200
    assert result.json()['points'] == 3
    assert result.json()['interview_credits'] == 0
