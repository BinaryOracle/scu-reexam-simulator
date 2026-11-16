"""Active accounts share module access while administrator roles remain isolated."""
import sqlite3
import time
from pathlib import Path
import pytest


@pytest.fixture
def legacy_client(tmp_path, monkeypatch):
    path = tmp_path / 'app.db'
    config = Path('config.example.toml').read_text().replace('data/app.db', str(path)).replace('data/audio', str(tmp_path / 'audio')).replace('data/presentations', str(tmp_path / 'presentations'))
    (tmp_path / 'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(tmp_path / 'config.toml'))
    from app.services.security import hash_password
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL)')
        for name, role in [('manager', 'teacher'), ('alice', 'student'), ('bob', 'student')]:
            db.execute('INSERT INTO users(username,password,role) VALUES (?,?,?)', (name, hash_password('password123'), role))
    from app.db import initialize
    initialize()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        yield client


def login(client, username, password='password123'):
    response = client.post('/api/login', json={'username': username, 'password': password})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}


def test_legacy_accounts_migrate_once_without_teacher_role(legacy_client):
    from app.db import connect, initialize
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    admin = legacy_client.get('/api/me', headers=manager).json()
    user = legacy_client.get('/api/me', headers=alice).json()
    assert admin['is_admin'] is True
    assert admin['can_interview'] and admin['can_exam']
    assert user['can_interview'] and user['can_exam']
    assert 'role' not in admin
    with connect() as db:
        assert 'role' not in {r['name'] for r in db.execute('PRAGMA table_info(users)')}
        db.execute('UPDATE users SET can_exam=0 WHERE username=?', ('alice',))
    initialize()
    assert legacy_client.get('/api/me', headers=alice).json()['can_exam'] is False
    assert legacy_client.get('/api/contests', headers=alice).status_code == 403


def test_only_admin_can_manage_users(legacy_client):
    alice = login(legacy_client, 'alice')
    assert legacy_client.get('/api/admin/users').status_code == 401
    assert legacy_client.get('/api/admin/users', headers=alice).status_code == 403
    assert legacy_client.post('/api/admin/users', headers=alice, json={'username': 'eve', 'password': 'password123', 'is_admin': True}).status_code == 403
    manager = login(legacy_client, 'manager')
    rows = legacy_client.get('/api/admin/users', headers=manager).json()
    assert len(rows) == 3
    assert all('password' not in row and 'token' not in row for row in rows)


def test_account_creation_defaults_and_duplicate_validation(legacy_client):
    manager = login(legacy_client, 'manager')
    payload = {'username': 'new-user', 'password': 'password123'}
    response = legacy_client.post('/api/admin/users', headers=manager, json=payload)
    assert response.status_code == 201
    row = response.json()
    assert not row['is_admin'] and row['is_active']
    assert row['can_interview'] and row['can_exam']
    assert legacy_client.post('/api/admin/users', headers=manager, json=payload).status_code == 409
    assert legacy_client.post('/api/admin/users', headers=manager, json={'username':'short', 'password':'123'}).status_code == 201
    user = login(legacy_client, 'new-user')
    assert legacy_client.get('/api/interviews', headers=user).status_code == 200
    assert legacy_client.get('/api/contests', headers=user).status_code == 200


def test_module_flags_restrict_active_sessions(legacy_client):
    from app.db import connect
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    iid = legacy_client.post('/api/interviews', headers=alice).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET can_interview=0,can_exam=0 WHERE id=?', (uid,))
    assert legacy_client.get('/api/interviews', headers=alice).status_code == 403
    assert legacy_client.get(f'/api/interviews/{iid}', headers=alice).status_code == 403
    assert legacy_client.get('/api/contests', headers=alice).status_code == 403
    assert legacy_client.get('/api/submissions', headers=alice).status_code == 403
    assert legacy_client.get('/api/admin/users', headers=alice).status_code == 403
    for flag in ('can_interview', 'can_exam'):
        assert legacy_client.patch(f'/api/admin/users/{uid}', headers=manager,
            json={flag: True}).status_code == 200


def test_disabling_account_and_password_reset_invalidate_sessions(legacy_client):
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    assert legacy_client.patch(f'/api/admin/users/{uid}', headers=manager, json={'is_active':False}).status_code == 200
    assert legacy_client.get('/api/me', headers=alice).status_code == 401
    assert legacy_client.get('/api/interviews', headers=alice).status_code == 401
    assert legacy_client.get('/api/contests', headers=alice).status_code == 401
    assert legacy_client.post('/api/login', json={'username':'alice','password':'password123'}).status_code == 401
    legacy_client.patch(f'/api/admin/users/{uid}', headers=manager, json={'is_active':True})
    assert legacy_client.get('/api/me', headers=alice).status_code == 401
    alice = login(legacy_client, 'alice')
    assert legacy_client.post(f'/api/admin/users/{uid}/password', headers=manager, json={'password':'new-password123'}).status_code == 200
    assert legacy_client.get('/api/me', headers=alice).status_code == 401
    assert legacy_client.post('/api/login',json={'username':'alice','password':'password123'}).status_code == 401
    assert login(legacy_client,'alice','new-password123')


def test_administrator_can_use_both_modules_and_be_demoted(legacy_client):
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    legacy_client.patch(f'/api/admin/users/{uid}', headers=manager,json={'is_admin':True})
    assert legacy_client.get('/api/admin/users',headers=alice).status_code == 200
    assert legacy_client.post('/api/interviews',headers=alice).status_code == 200
    assert legacy_client.get('/api/contests',headers=alice).status_code == 200
    assert legacy_client.get('/api/admin/contests',headers=alice).status_code == 200
    legacy_client.patch(f'/api/admin/users/{uid}',headers=manager,json={'is_admin':False})
    assert legacy_client.get('/api/admin/users',headers=alice).status_code == 403
    assert legacy_client.patch(f'/api/admin/users/{uid}',headers=alice,json={'is_admin':True}).status_code == 403


def test_admin_cannot_lock_out_own_account(legacy_client):
    manager = login(legacy_client, 'manager')
    uid = legacy_client.get('/api/me',headers=manager).json()['id']
    for payload in [{'is_admin':False},{'is_active':False}]:
        assert legacy_client.patch(f'/api/admin/users/{uid}',headers=manager,json=payload).status_code == 409
    assert legacy_client.get('/api/admin/users',headers=manager).status_code == 200


def test_admin_management_keeps_user_records_private(legacy_client):
    manager, alice, bob = [login(legacy_client,name) for name in ['manager','alice','bob']]
    iid = legacy_client.post('/api/interviews',headers=alice).json()['id']
    assert legacy_client.get('/api/admin/interviews',headers=manager).status_code == 200
    assert legacy_client.get('/api/admin/interviews',headers=bob).status_code == 403
    assert legacy_client.get(f'/api/admin/interviews/{iid}',headers=manager).status_code == 200
    assert legacy_client.get(f'/api/interviews/{iid}',headers=bob).status_code == 404
    assert legacy_client.get(f'/api/interviews/{iid}',headers=manager).status_code == 404


def test_old_sessions_and_answers_survive_database_migration(tmp_path, monkeypatch):
    path = tmp_path/'legacy.db'
    config = Path('config.example.toml').read_text().replace('data/app.db',str(path))
    (tmp_path/'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG',str(tmp_path/'config.toml'))
    from app.services.security import hash_password
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL);
        CREATE TABLE sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires REAL NOT NULL);
        CREATE TABLE interviews(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),status TEXT NOT NULL DEFAULT 'active',created REAL NOT NULL,feedback TEXT);
        CREATE TABLE answers(id INTEGER PRIMARY KEY,interview_id INTEGER NOT NULL REFERENCES interviews(id),stage INTEGER NOT NULL,question TEXT NOT NULL,transcript TEXT NOT NULL DEFAULT '',audio_path TEXT,UNIQUE(interview_id,stage));''')
        db.execute('INSERT INTO users VALUES (42,?,?,?)',('old-user',hash_password('password123'),'student'))
        db.execute('INSERT INTO sessions VALUES (?,?,?)',('old-token',42,time.time()+3600))
        db.execute('INSERT INTO interviews VALUES (7,42,?,?,?)',('active',time.time(),None))
        db.execute('INSERT INTO answers VALUES (1,7,1,?,?,?)',('Question','Answer','/old/audio.webm'))
    from app.db import initialize,connect
    initialize();initialize()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response=client.get('/api/interviews/7',headers={'Authorization':'Bearer old-token'})
        assert response.status_code == 200
        assert response.json()['answers'][0]['transcript'] == 'Answer'
        assert response.json()['workflow_version'] == 1
        assert response.json()['presentation'] is None
        assert client.put('/api/interviews/7/answers/1', headers={'Authorization':'Bearer old-token'},
            json={'transcript':'旧流程可继续'}).status_code == 200
    with connect() as db:
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT audio_path FROM answers').fetchone()[0]=='/old/audio.webm'


def test_account_updates_reject_invalid_fields_without_changing_account_state(legacy_client):
    manager = login(legacy_client, 'manager')
    user = login(legacy_client, 'alice')
    before = legacy_client.get('/api/me', headers=user).json()
    for payload in [
        {'can_exam': 'false'}, {'can_interview': '0'}, {'is_active': None},
        {'role': 'teacher'}, {'username': 'changed'}, {},
    ]:
        response = legacy_client.patch(f"/api/admin/users/{before['id']}", headers=manager, json=payload)
        assert response.status_code == 422
    assert legacy_client.get('/api/me', headers=user).json() == before


def test_admin_can_review_audio_through_admin_api(legacy_client):
    manager, alice, bob = [login(legacy_client, name) for name in ['manager', 'alice', 'bob']]
    iid = legacy_client.post('/api/interviews', headers=alice).json()['id']
    from test_presentations import upload
    assert upload(legacy_client, iid, alice).status_code == 200
    assert legacy_client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 200
    content = b'isolated-audio-fixture'
    assert legacy_client.post(f'/api/interviews/{iid}/answers/1/audio', headers=alice,
        files={'file': ('answer.webm', content, 'audio/webm')}).status_code == 200
    path = f'/api/admin/interviews/{iid}/answers/1/audio'
    assert legacy_client.get(path, headers=manager).content == content
    assert legacy_client.get(path, headers=bob).status_code == 403
    assert legacy_client.get(f'/api/interviews/{iid}/answers/1/audio', headers=bob).status_code == 404



def test_new_admin_receives_both_modules_without_feature_flags(legacy_client):
    manager = login(legacy_client, 'manager')
    response = legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'new-admin', 'password': 'password123', 'is_admin': True})
    assert response.status_code == 201
    assert response.json()['can_interview'] and response.json()['can_exam']
    admin = login(legacy_client, 'new-admin')
    assert legacy_client.get('/api/contests', headers=admin).status_code == 200
    assert legacy_client.post('/api/interviews', headers=admin).status_code == 200


def test_v1_admins_gain_module_access_without_changing_ordinary_users(legacy_client):
    from app.db import connect, initialize, SCHEMA_VERSION
    with connect() as db:
        db.execute('PRAGMA user_version=1')
        db.execute('UPDATE users SET can_interview=0,can_exam=0')
    initialize()
    with connect() as db:
        admin = db.execute("SELECT can_interview,can_exam FROM users WHERE username='manager'").fetchone()
        ordinary = db.execute("SELECT can_interview,can_exam FROM users WHERE username='alice'").fetchone()
        assert tuple(admin) == (1, 1)
        assert tuple(ordinary) == (1, 1)
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION


def test_rename_preserves_identity_password_sessions_and_history(legacy_client):
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    iid = legacy_client.post('/api/interviews', headers=alice).json()['id']
    response = legacy_client.post(f'/api/admin/users/{uid}/username', headers=manager,
        json={'username': 'alice-renamed'})
    assert response.status_code == 200
    assert response.json()['id'] == uid and response.json()['username'] == 'alice-renamed'
    assert legacy_client.get('/api/me', headers=alice).json()['username'] == 'alice-renamed'
    assert legacy_client.get(f'/api/interviews/{iid}', headers=alice).status_code == 200
    assert legacy_client.post('/api/login', json={'username': 'alice', 'password': 'password123'}).status_code == 401
    assert login(legacy_client, 'alice-renamed')
    own_id = legacy_client.get('/api/me', headers=manager).json()['id']
    assert legacy_client.post(f'/api/admin/users/{own_id}/username', headers=manager,
        json={'username': 'renamed-manager'}).status_code == 200
    assert legacy_client.get('/api/admin/users', headers=manager).status_code == 200


def test_rename_is_admin_only_and_rejects_duplicate_invalid_names(legacy_client):
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    url = f'/api/admin/users/{uid}/username'
    assert legacy_client.post(url, json={'username': 'changed'}).status_code == 401
    assert legacy_client.post(url, headers=alice, json={'username': 'changed'}).status_code == 403
    assert legacy_client.post(url, headers=manager, json={'username': 'bob'}).status_code == 409
    for value in ['']:
        assert legacy_client.post(url, headers=manager, json={'username': value}).status_code == 422
    assert legacy_client.post('/api/admin/users/9999/username', headers=manager,
        json={'username': 'changed'}).status_code == 404
    assert legacy_client.get('/api/me', headers=alice).json()['username'] == 'alice'


@pytest.mark.parametrize('username,password', [
    ('a', '1'), (' 含 空格/@!<> ', 'root'), ('名'*200, 'p'*300),
])
def test_credentials_have_no_character_complexity_or_length_rules(legacy_client, username, password):
    manager = login(legacy_client, 'manager')
    result = legacy_client.post('/api/admin/users', headers=manager,
        json={'username': username, 'password': password})
    assert result.status_code == 201
    assert result.json()['username'] == username
    user = login(legacy_client, username, password)
    uid = result.json()['id']
    renamed = username + ' ?新'
    result = legacy_client.post(f'/api/admin/users/{uid}/username', headers=manager,
        json={'username': renamed})
    assert result.status_code == 200
    assert login(legacy_client, renamed, password)
    assert legacy_client.post(f'/api/admin/users/{uid}/password', headers=manager,
        json={'password': 'x'}).status_code == 200
    assert legacy_client.get('/api/me', headers=user).status_code == 401
    assert login(legacy_client, renamed, 'x')


def test_empty_credentials_still_require_values(legacy_client):
    manager = login(legacy_client, 'manager')
    for payload in [{'username':'','password':'x'}, {'username':'user','password':''}]:
        assert legacy_client.post('/api/admin/users', headers=manager, json=payload).status_code == 422
    assert legacy_client.post('/api/admin/users/2/password', headers=manager,
        json={'password':''}).status_code == 422


def test_empty_database_bootstraps_root_once(tmp_path, monkeypatch):
    config = Path('config.example.toml').read_text().replace('data/app.db', str(tmp_path/'fresh.db'))
    (tmp_path/'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(tmp_path/'config.toml'))
    from app.db import initialize, connect
    from app.services.security import hash_password
    from fastapi.testclient import TestClient
    from app.main import app
    initialize()
    with TestClient(app) as client:
        headers = login(client, 'root', 'root')
        user = client.get('/api/me', headers=headers).json()
        assert user['is_admin'] and user['is_active']
        assert user['can_interview'] and user['can_exam']
        with connect() as db:
            db.execute('UPDATE users SET username=?,password=? WHERE id=?',
                ('renamed-root',hash_password('1'),user['id']))
        initialize()
        assert login(client, 'renamed-root', '1')
        assert client.post('/api/login', json={'username':'root','password':'root'}).status_code == 401
        with connect() as db:
            assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1


def test_console_creation_accepts_short_password_and_unrestricted_username(legacy_client, monkeypatch):
    from scripts import create_user
    monkeypatch.setattr('sys.argv', ['create_user', ' 用户/@ ', '--admin'])
    monkeypatch.setattr(create_user, 'getpass', lambda prompt: '1')
    create_user.main()
    headers = login(legacy_client, ' 用户/@ ', '1')
    assert legacy_client.get('/api/me', headers=headers).json()['is_admin']


def test_admin_provisioned_email_is_optional_normalized_and_unique(legacy_client):
    manager = login(legacy_client, 'manager')
    response = legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'mail-user', 'password': '1', 'email': ' Person@Example.com '})
    assert response.status_code == 201
    assert response.json()['email'] == 'person@example.com'
    headers = login(legacy_client, 'mail-user', '1')
    assert legacy_client.get('/api/me', headers=headers).json()['email'] == 'person@example.com'
    assert legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'duplicate-mail', 'password': '1', 'email': 'PERSON@example.com'}).status_code == 409
    assert legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'bad-mail', 'password': '1', 'email': 'invalid'}).status_code == 422
    assert legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'no-mail', 'password': '1', 'email': ''}).json()['email'] is None


def test_admin_email_change_preserves_identity_records_balance_and_sessions(legacy_client):
    from app.db import connect
    manager, alice = login(legacy_client, 'manager'), login(legacy_client, 'alice')
    before = legacy_client.get('/api/me', headers=alice).json()
    uid = before['id']
    iid = legacy_client.post('/api/interviews', headers=alice).json()['id']
    url = f'/api/admin/users/{uid}/email'
    associated = legacy_client.post(url, headers=manager, json={'email': ' Old@Example.com '})
    assert associated.status_code == 200
    assert associated.json()['email'] == 'old@example.com'
    with connect() as db:
        for address in ('old@example.com', 'new@example.com', 'other@example.com'):
            db.execute('INSERT INTO email_challenges VALUES (?,?,?,?,?,?,?)',
                (address, address, 'unused-hash', time.time(), time.time()+3600, 0, 'ready'))
        db.execute('''INSERT INTO account_email_challenges
            (user_id,purpose,email,source_email,challenge_id,code_hash,created,expires,attempts,status)
            VALUES (?,'password','old@example.com','old@example.com','admin-test','unused-hash',?,?,0,'ready')''',
            (uid, time.time(), time.time()+3600))
    changed = legacy_client.post(url, headers=manager, json={'email': 'NEW@EXAMPLE.COM'})
    assert changed.status_code == 200
    assert changed.json()['id'] == uid and changed.json()['email'] == 'new@example.com'
    assert changed.json()['interview_credits'] == before['interview_credits']
    assert legacy_client.get('/api/me', headers=alice).json()['email'] == 'new@example.com'
    assert legacy_client.get(f'/api/interviews/{iid}', headers=alice).status_code == 200
    assert login(legacy_client, 'alice')
    with connect() as db:
        assert {row['email'] for row in db.execute('SELECT email FROM email_challenges')} == {'other@example.com'}
        assert not db.execute('SELECT 1 FROM account_email_challenges WHERE user_id=?', (uid,)).fetchone()
    assert legacy_client.post(url, headers=manager, json={'email': ''}).json()['email'] is None
    assert legacy_client.post(url, headers=manager, json={'email': None}).status_code == 200
    assert legacy_client.get('/api/me', headers=alice).status_code == 200


def test_email_management_is_admin_only_and_preserves_mailbox_on_conflicts(legacy_client):
    manager, alice, bob = [login(legacy_client, name) for name in ('manager', 'alice', 'bob')]
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    bid = legacy_client.get('/api/me', headers=bob).json()['id']
    mid = legacy_client.get('/api/me', headers=manager).json()['id']
    url = f'/api/admin/users/{uid}/email'
    assert legacy_client.post(url, json={'email': 'one@example.com'}).status_code == 401
    assert legacy_client.post(url, headers=alice, json={'email': 'one@example.com'}).status_code == 403
    assert legacy_client.post(url, headers=manager, json={'email': 'one@example.com'}).status_code == 200
    assert legacy_client.post(f'/api/admin/users/{bid}/email', headers=manager,
        json={'email': 'ONE@example.com'}).status_code == 409
    for payload in ({'email': 'invalid'}, {}, {'email': True}, {'email': None, 'username': 'changed'}):
        assert legacy_client.post(url, headers=manager, json=payload).status_code == 422
    assert legacy_client.get('/api/me', headers=alice).json()['email'] == 'one@example.com'
    assert legacy_client.get('/api/me', headers=bob).json()['email'] is None
    assert legacy_client.post('/api/admin/users/99999/email', headers=manager,
        json={'email': 'missing@example.com'}).status_code == 404
    legacy_client.post('/api/admin/users', headers=manager,
        json={'username': 'staff', 'password': 'password123', 'is_admin': True})
    staff = login(legacy_client, 'staff')
    assert legacy_client.post(f'/api/admin/users/{mid}/email', headers=staff,
        json={'email': 'hidden@example.com'}).status_code == 404
    assert legacy_client.post(url, headers=staff, json={'email': 'replaced@example.com'}).status_code == 200
