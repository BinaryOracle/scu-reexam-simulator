"""Verified profile changes retain identity and delete owned account data completely."""
import time
import pytest
from test_system import client, login


@pytest.fixture
def profile_client(client):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes.profile_account import router
    profile_app = FastAPI()
    profile_app.include_router(router)
    with TestClient(profile_app) as result:
        yield result


def test_profile_rename_preserves_email_records_balance_and_current_session(client, profile_client):
    from app.db import connect
    alice = login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    iid = client.post('/api/interviews', headers=alice).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET email=?,interview_credits=7 WHERE id=?', ('alice@example.com', uid))
    changed = profile_client.post('/api/profile/username', headers=alice, json={'username': ' 新 用户/@ '})
    assert changed.status_code == 200
    assert changed.json()['id'] == uid and changed.json()['username'] == ' 新 用户/@ '
    assert changed.json()['email'] == 'alice@example.com' and changed.json()['interview_credits'] == 7
    assert client.get(f'/api/interviews/{iid}', headers=alice).status_code == 200
    renamed = login(client, ' 新 用户/@ ')
    assert client.get('/api/me', headers=alice).status_code == 401
    assert client.get('/api/me', headers=renamed).json()['username'] == ' 新 用户/@ '
    assert client.post('/api/login', json={'username': 'alice', 'password': 'password123'}).status_code == 401
    for payload, status in [({'username': ''}, 422), ({'username': 'bob'}, 409), ({'username': 'new', 'is_admin': True}, 422)]:
        assert profile_client.post('/api/profile/username', headers=renamed, json=payload).status_code == status
    assert profile_client.post('/api/profile/username', json={'username': 'missing'}).status_code == 401


def test_profile_password_reveal_is_explicit_private_and_only_for_current_account(client, profile_client):
    from app.db import connect
    from app.services.password_vault import encrypt_password
    alice, bob = login(client, 'alice'), login(client, 'bob')
    secret = ' 我的密码 <&🙂 '
    with connect() as db:
        db.execute('UPDATE users SET password_ciphertext=? WHERE username=?', (encrypt_password(secret), 'alice'))
    path = '/api/profile/reveal-password'
    assert profile_client.post(path).status_code == 401
    revealed = profile_client.post(path, headers=alice)
    assert revealed.status_code == 200
    assert revealed.json() == {'password': secret}
    assert revealed.headers['cache-control'] == 'no-store'
    assert profile_client.post(path, headers=bob).json() == {'password': 'password123'}
    for endpoint in ('/api/me', '/api/profile'):
        assert not {'password', 'password_ciphertext'} & client.get(endpoint, headers=alice).json().keys()
    with connect() as db:
        db.execute("UPDATE users SET password_ciphertext='' WHERE username='alice'")
    assert profile_client.post(path, headers=alice).status_code == 409
    with connect() as db:
        db.execute("UPDATE users SET is_active=0 WHERE username='bob'")
    assert profile_client.post(path, headers=bob).status_code == 401


def test_profile_password_reveal_rechecks_revoked_session(client, profile_client):
    from app.db import connect
    from app.services.auth import current_user
    alice = login(client, 'alice')
    user = client.get('/api/me', headers=alice).json()
    profile_client.app.dependency_overrides[current_user] = lambda: user
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    assert profile_client.post('/api/profile/reveal-password', headers=alice).status_code == 401


def test_unbound_password_change_requires_old_password_and_revokes_current_session(client, profile_client):
    from app.db import connect
    from app.services.security import verify_password
    from app.services.password_vault import decrypt_password
    alice = login(client, 'alice')
    for payload, status in [({'password': '1'}, 422), ({'password': '1', 'current_password': 'wrong'}, 400), ({'password': '', 'current_password': 'password123'}, 422)]:
        assert profile_client.post('/api/profile/password', headers=alice, json=payload).status_code == status
        assert client.get('/api/me', headers=alice).status_code == 200
    response = profile_client.post('/api/profile/password', headers=alice,
        json={'password': '1', 'current_password': 'password123'})
    assert response.status_code == 200
    assert client.get('/api/me', headers=alice).status_code == 401
    with connect() as db:
        row = db.execute("SELECT password,password_ciphertext FROM users WHERE username='alice'").fetchone()
        assert verify_password('1', row['password']) and decrypt_password(row['password_ciphertext']) == '1'
    assert client.post('/api/login', json={'username': 'alice', 'password': '1'}).status_code == 200


def test_unbound_delete_requires_password_and_removes_private_data_preserving_vouchers(client, profile_client, tmp_path):
    from app.db import connect
    alice, manager = login(client, 'alice'), login(client, 'manager')
    uid = client.get('/api/me', headers=alice).json()['id']
    card = client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 1}).json()[0]
    assert client.post('/api/profile/redeem', headers=alice, json={'code': card['code']}).status_code == 200
    iid = client.post('/api/interviews', headers=alice).json()['id']
    audio = tmp_path/'record.webm'; audio.write_bytes(b'audio')
    slides = tmp_path/'slides'; slides.mkdir(); (slides/'1.png').write_bytes(b'image')
    with connect() as db:
        db.execute('UPDATE answers SET audio_path=? WHERE interview_id=? AND stage=1', (str(audio), iid))
        db.execute('INSERT INTO interview_recordings(id,interview_id,created,audio_path) VALUES (?,?,?,?)', ('self-delete', iid, time.time(), str(audio)))
        db.execute('INSERT INTO presentations VALUES (?,?,?,?)', (iid, str(slides), 'slides.pdf', 1))
        db.execute('INSERT INTO speech_cache VALUES (?,?,?,?)', ('private-speech', iid, b'audio', 'audio/mpeg'))
    for payload, status in [({}, 422), ({'current_password': 'wrong'}, 400)]:
        assert profile_client.request('DELETE', '/api/profile/account', headers=alice, json=payload).status_code == status
        assert client.get('/api/me', headers=alice).status_code == 200 and audio.exists()
    assert profile_client.request('DELETE', '/api/profile/account', headers=alice,
        json={'current_password': 'password123'}).status_code == 204
    assert client.get('/api/me', headers=alice).status_code == 401
    assert not audio.exists() and not slides.exists()
    with connect() as db:
        assert not db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone()
        assert not db.execute('SELECT 1 FROM interviews WHERE id=?', (iid,)).fetchone()
        assert not db.execute('SELECT 1 FROM speech_cache WHERE interview_id=?', (iid,)).fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        voucher = db.execute('SELECT redeemed_at,redeemed_by,redeemed_username FROM vouchers WHERE id=?', (card['id'],)).fetchone()
        assert voucher['redeemed_at'] and voucher['redeemed_by'] is None and voucher['redeemed_username'] == 'alice'
    assert client.post('/api/profile/redeem', headers=login(client, 'bob'), json={'code': card['code']}).status_code == 409


def test_superadmin_cannot_self_delete_and_inactive_sessions_cannot_mutate(client, profile_client):
    from app.db import connect
    root = {'Authorization': 'Bearer ' + client.post('/api/login', json={'username': 'root', 'password': 'root'}).json()['token']}
    assert profile_client.request('DELETE', '/api/profile/account', headers=root,
        json={'current_password': 'root'}).status_code == 409
    alice = login(client, 'alice')
    with connect() as db:
        db.execute("UPDATE users SET is_active=0 WHERE username='alice'")
    for method, path, payload in [('POST', '/api/profile/username', {'username': 'changed'}), ('POST', '/api/profile/password', {'password': '1', 'current_password': 'password123'}), ('DELETE', '/api/profile/account', {'current_password': 'password123'})]:
        assert profile_client.request(method, path, headers=alice, json=payload).status_code == 401


def account_code(uid, purpose, *, code='123456', email='alice@example.com', source_email='alice@example.com'):
    """Seed a delivered purpose-bound code; SMTP delivery is tested by the email suite."""
    from app.db import connect
    from app.services.security import hash_password
    with connect() as db:
        db.execute('''INSERT OR REPLACE INTO account_email_challenges
            (user_id,purpose,email,source_email,challenge_id,code_hash,created,expires,attempts,status)
            VALUES (?,?,?,?,?,?,?,?,0,'ready')''',
            (uid, purpose, email, source_email, purpose, hash_password(code), time.time(), time.time()+3600))


def bound_alice(client):
    from app.db import connect
    headers = login(client, 'alice')
    uid = client.get('/api/me', headers=headers).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET email=? WHERE id=?', ('alice@example.com', uid))
    return headers, uid


def test_bound_password_requires_purpose_code_commits_failed_attempts_and_is_single_use(client, profile_client):
    from app.db import connect
    alice, uid = bound_alice(client)
    assert profile_client.post('/api/profile/password', headers=alice,
        json={'password': '1', 'current_password': 'password123'}).status_code == 422
    account_code(uid, 'password')
    wrong = profile_client.post('/api/profile/password', headers=alice, json={'password': '1', 'code': '654321'})
    assert wrong.status_code == 400
    assert client.get('/api/me', headers=alice).status_code == 200
    with connect() as db:
        assert db.execute("SELECT attempts FROM account_email_challenges WHERE user_id=? AND purpose='password'", (uid,)).fetchone()[0] == 1
    response = profile_client.post('/api/profile/password', headers=alice, json={'password': '1', 'code': '123456'})
    assert response.status_code == 200
    assert client.get('/api/me', headers=alice).status_code == 401
    fresh = {'Authorization': 'Bearer ' + client.post('/api/login', json={'username': 'alice', 'password': '1'}).json()['token']}
    assert profile_client.post('/api/profile/password', headers=fresh, json={'password': '2', 'code': '123456'}).status_code == 400
    assert client.get('/api/me', headers=fresh).status_code == 200


def test_delete_code_is_bound_to_account_purpose_and_current_mailbox(client, profile_client):
    from app.db import connect
    alice, uid = bound_alice(client)
    bob = login(client, 'bob')
    bid = client.get('/api/me', headers=bob).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET email=? WHERE id=?', ('bob@example.com', bid))
    account_code(uid, 'password')
    account_code(bid, 'delete', code='654321', email='bob@example.com', source_email='bob@example.com')
    for code in ('123456', '654321'):
        assert profile_client.request('DELETE', '/api/profile/account', headers=alice, json={'code': code}).status_code == 400
    assert client.get('/api/me', headers=alice).status_code == 200
    account_code(uid, 'delete', source_email='old@example.com')
    assert profile_client.request('DELETE', '/api/profile/account', headers=alice, json={'code': '123456'}).status_code == 400
    account_code(uid, 'delete')
    assert profile_client.request('DELETE', '/api/profile/account', headers=alice, json={'code': '123456'}).status_code == 204
    with connect() as db:
        assert not db.execute('SELECT 1 FROM account_email_challenges WHERE user_id=?', (uid,)).fetchone()
    assert client.get('/api/me', headers=bob).status_code == 200


def test_session_is_rechecked_inside_mutation_transaction(client, profile_client):
    from app.db import connect
    from app.services.auth import current_user
    alice = login(client, 'alice')
    user = client.get('/api/me', headers=alice).json()
    profile_client.app.dependency_overrides[current_user] = lambda: user
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    for method, path, payload in [('POST', '/api/profile/username', {'username': 'changed'}), ('POST', '/api/profile/password', {'password': '1', 'current_password': 'password123'}), ('DELETE', '/api/profile/account', {'current_password': 'password123'})]:
        assert profile_client.request(method, path, headers=alice, json=payload).status_code == 401
    with connect() as db:
        assert db.execute('SELECT username FROM users WHERE id=?', (user['id'],)).fetchone()[0] == 'alice'


def test_last_active_admin_cannot_self_delete(client, profile_client):
    from app.db import connect
    manager = login(client, 'manager')
    with connect() as db:
        db.execute('UPDATE users SET is_active=0 WHERE is_superadmin=1')
    response = profile_client.request('DELETE', '/api/profile/account', headers=manager,
        json={'current_password': 'password123'})
    assert response.status_code == 409
    assert client.get('/api/me', headers=manager).status_code == 200


@pytest.mark.parametrize('self_delete', [False, True])
def test_deleted_highest_account_id_is_never_reassigned(client, profile_client, self_delete):
    from app.db import connect
    from app.services.security import hash_password
    with connect() as db:
        db.execute('INSERT INTO users(id,username,password) VALUES (?,?,?)', (1000, 'deleted-highest', hash_password('password123')))
    manager = login(client, 'manager')
    if self_delete:
        account = login(client, 'deleted-highest')
        response = profile_client.request('DELETE', '/api/profile/account', headers=account,
            json={'current_password': 'password123'})
    else:
        response = client.delete('/api/admin/users/1000', headers=manager)
    assert response.status_code == 204
    created = client.post('/api/admin/users', headers=manager,
        json={'username': 'replacement', 'password': '1'})
    assert created.status_code == 201
    assert created.json()['id'] > 1000
