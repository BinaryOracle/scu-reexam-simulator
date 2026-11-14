"""Superadministrator identity, account isolation, deletion, and dynamic packages."""
import time
from test_system import client
from test_admin_permissions import login


def actors(c):
    return login(c, 'root', 'root'), login(c, 'manager'), login(c, 'alice')


def test_root_identity_survives_rename_and_migration(client):
    from app.db import initialize, connect
    root, manager, _ = actors(client)
    account = client.get('/api/me', headers=root).json()
    assert account['is_superadmin'] is True
    assert client.get('/api/me', headers=manager).json()['is_superadmin'] is False
    assert client.post(f"/api/admin/users/{account['id']}/username", headers=root,
        json={'username': 'owner'}).status_code == 200
    initialize(); initialize()
    assert client.get('/api/me', headers=root).json()['is_superadmin'] is True
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM users WHERE is_superadmin=1').fetchone()[0] == 1
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert client.delete(f"/api/admin/users/{account['id']}", headers=root).status_code == 409
    for change in ({'is_admin': False}, {'is_active': False}):
        assert client.patch(f"/api/admin/users/{account['id']}", headers=root, json=change).status_code == 409
    assert client.post(f"/api/admin/users/{account['id']}/password", headers=root,
        json={'password': '1'}).status_code == 200
    assert client.get('/api/me', headers=root).status_code == 401
    assert client.get('/api/me', headers=login(client, 'owner', '1')).json()['is_superadmin'] is True


def test_ordinary_admin_cannot_discover_or_modify_administrators(client):
    root, manager, _ = actors(client)
    all_users = client.get('/api/admin/users', headers=root).json()
    assert {row['username'] for row in client.get('/api/admin/users', headers=manager).json()} == {'alice', 'bob'}
    for account in (row for row in all_users if row['is_admin']):
        uid = account['id']
        for method, suffix, payload in [
            ('post', '/reveal-password', None), ('post', '/username', {'username': 'hacked'}),
            ('post', '/password', {'password': 'hacked'}), ('patch', '', {'is_active': False}),
            ('delete', '', None),
        ]:
            assert getattr(client, method)(f'/api/admin/users/{uid}{suffix}', headers=manager,
                **({'json': payload} if payload is not None else {})).status_code == 404
    assert client.post('/api/admin/users', headers=manager,
        json={'username': 'escape', 'password': '1', 'is_admin': True}).status_code == 403
    alice = next(row for row in all_users if row['username'] == 'alice')
    assert client.patch(f"/api/admin/users/{alice['id']}", headers=manager, json={'is_admin': True}).status_code == 403
    mid = next(row['id'] for row in all_users if row['username'] == 'manager')
    assert client.post(f'/api/admin/users/{mid}/username', headers=root, json={'username': 'staff'}).status_code == 200
    assert client.post(f'/api/admin/users/{mid}/password', headers=root, json={'password': 'x'}).status_code == 200
    assert login(client, 'staff', 'x')
    assert client.delete(f'/api/admin/users/{mid}', headers=root).status_code == 204


def test_administrator_records_are_hidden_from_ordinary_admin(client, tmp_path):
    root, manager, _ = actors(client)
    iid = client.post('/api/interviews', headers=root).json()['id']
    from app.db import connect
    slide = tmp_path / 'slides'; slide.mkdir()
    audio = tmp_path / 'r.webm'; audio.write_bytes(b'audio')
    with connect() as db:
        db.execute('INSERT INTO presentations VALUES (?,?,?,?)', (iid, str(slide), 'test', 1))
        db.execute('UPDATE answers SET audio_path=? WHERE interview_id=? AND stage=1', (str(audio), iid))
        db.execute('INSERT INTO interview_recordings(id,interview_id,created,audio_path) VALUES (?,?,?,?)',
            ('private', iid, time.time(), str(audio)))
    assert client.get('/api/admin/interviews', headers=manager).json() == []
    for path in ('', '/answers/1/audio', '/recordings/private', '/presentation/pages/1'):
        assert client.get(f'/api/admin/interviews/{iid}{path}', headers=manager).status_code == 404
    assert client.get(f'/api/admin/interviews/{iid}', headers=root).status_code == 200


def test_delete_user_cleans_private_data_but_never_reactivates_used_voucher(client, tmp_path):
    from app.db import connect
    root, manager, alice = actors(client)
    uid = client.get('/api/me', headers=alice).json()['id']
    cards = client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 1}).json()
    assert client.post('/api/profile/redeem', headers=alice, json={'code': cards[0]['code']}).status_code == 200
    iid = client.post('/api/interviews', headers=alice).json()['id']
    audio = tmp_path/'r.webm'; audio.write_bytes(b'audio')
    slides = tmp_path/'slides'; slides.mkdir(); (slides/'1.png').write_bytes(b'image')
    with connect() as db:
        db.execute('UPDATE answers SET audio_path=? WHERE interview_id=?', (str(audio), iid))
        db.execute('INSERT INTO presentations VALUES (?,?,?,?)', (iid, str(slides), 'p', 1))
        db.execute('INSERT INTO interview_recordings(id,interview_id,created,audio_path) VALUES (?,?,?,?)',
            ('record', iid, time.time(), str(audio)))
    assert client.delete(f'/api/admin/users/{uid}', headers=alice).status_code == 403
    assert client.delete(f'/api/admin/users/{uid}', headers=manager).status_code == 204
    assert client.get('/api/me', headers=alice).status_code == 401
    assert not audio.exists() and not slides.exists()
    with connect() as db:
        assert not db.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone()
        assert not db.execute('SELECT 1 FROM interviews WHERE user_id=?', (uid,)).fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    bob = login(client, 'bob')
    assert client.post('/api/profile/redeem', headers=bob, json={'code': cards[0]['code']}).status_code == 409
    used = client.get('/api/admin/vouchers?status=redeemed', headers=root).json()
    assert used['total'] == 1 and 'alice' in used['items'][0]['redeemed_by']
    assert client.get('/api/admin/vouchers?status=unused', headers=root).json()['total'] == 0


def test_dynamic_packages_can_be_created_generated_exported_and_redeemed(client):
    from app.db import initialize
    root, manager, alice = actors(client)
    response = client.post('/api/admin/voucher-packages', headers=manager, json={'price_fen': 350, 'credits': 6})
    assert response.status_code == 201
    package = response.json()['id']
    assert client.post('/api/admin/voucher-packages', headers=alice, json={'price_fen': 350, 'credits': 6}).status_code == 403
    for payload in ({'price_fen': 0, 'credits': 1}, {'price_fen': 100.5, 'credits': 2}, {'price_fen': 100, 'credits': True}):
        assert client.post('/api/admin/voucher-packages', headers=manager, json=payload).status_code == 422
    assert client.post('/api/admin/voucher-packages', headers=manager, json={'price_fen': 350, 'credits': 6}).status_code == 409
    initialize()
    assert package in {p['id'] for p in client.get('/api/admin/credit-settings', headers=manager).json()['packages']}
    cards = client.post('/api/admin/vouchers', headers=manager, json={'package': package, 'count': 2})
    assert cards.status_code == 201
    codes = [c['code'] for c in cards.json()]
    assert client.get(f'/api/admin/vouchers?package={package}', headers=manager).json()['total'] == 2
    assert client.get(f'/api/admin/vouchers/export?package={package}', headers=manager).text.splitlines() == codes
    redeemed = client.post('/api/profile/redeem', headers=alice, json={'code': codes[0]})
    assert redeemed.json()['remaining'] == 7 and redeemed.json()['redeemed_amount_fen'] == 350


def test_logout_revokes_server_session_and_frontend_apis_hide_admin_allowance(client):
    root, manager, _ = actors(client)
    assert client.get('/api/profile', headers=root).json()['remaining'] is None
    assert client.get('/api/me', headers=manager).json()['interview_credits'] is None
    root_rows = client.get('/api/admin/users', headers=root).json()
    assert next(row for row in root_rows if row['username'] == 'manager')['interview_credits'] == 999999
    assert client.post('/api/logout', headers=root).status_code == 204
    assert client.get('/api/me', headers=root).status_code == 401


def test_v9_upgrade_preserves_redeemed_cards_balances_and_single_owner(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    from app.services.security import hash_password
    path = tmp_path/'v9.db'
    config = Path('config.example.toml').read_text().replace('data/app.db', str(path))
    config += '\n[credits.packages.custom]\ncredits = 8\nprice_fen = 600\n'
    (tmp_path/'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(tmp_path/'config.toml'))
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,can_interview INTEGER NOT NULL DEFAULT 1,can_exam INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,interview_credits INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE vouchers(id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,package TEXT NOT NULL CHECK(package IN ('three','ten')),
            credits INTEGER NOT NULL,price_fen INTEGER NOT NULL,batch TEXT NOT NULL,created REAL NOT NULL,
            redeemed_by INTEGER REFERENCES users(id),redeemed_at REAL,
            CHECK((redeemed_by IS NULL AND redeemed_at IS NULL) OR (redeemed_by IS NOT NULL AND redeemed_at IS NOT NULL)));
            PRAGMA user_version=9;''')
        for uid, username, admin in ((1,'staff',1),(2,'root',1),(3,'student',0)):
            db.execute('INSERT INTO users(id,username,password,is_admin,interview_credits) VALUES (?,?,?,?,?)',
                (uid, username, hash_password('1'), admin, 999999 if admin else 7))
        db.execute('INSERT INTO vouchers VALUES (1,?,?,?,?,?,?,?,?)', ('AAAA-AAAA-AAAA-AAAA-AAAA-AAAA','three',3,200,'batch',1,3,2))
    from app.db import initialize, connect
    initialize(); initialize()
    with connect() as db:
        assert db.execute('SELECT id FROM users WHERE is_superadmin=1').fetchone()[0] == 2
        assert db.execute("SELECT interview_credits FROM users WHERE id=3").fetchone()[0] == 7
        row = db.execute('SELECT * FROM vouchers').fetchone()
        assert row['redeemed_at'] == 2 and row['redeemed_by'] == 3 and row['redeemed_username'] == 'student'
        assert row['credits'] == 3 and row['price_fen'] == 200
        assert db.execute("SELECT credits FROM voucher_packages WHERE id='custom'").fetchone()[0] == 8
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        db.execute("UPDATE users SET username='owner' WHERE id=2")
        db.execute("INSERT INTO users(username,password,is_admin) VALUES ('root',?,1)", (hash_password('1'),))
    initialize()
    with connect() as db:
        assert db.execute('SELECT id FROM users WHERE is_superadmin=1').fetchone()[0] == 2


def test_interview_archive_owners_use_stable_ids_and_respect_admin_visibility(client):
    from app.db import connect
    root, manager, alice = actors(client)
    for headers in (root, alice, alice):
        client.post('/api/interviews', headers=headers)
    ordinary = client.get('/api/admin/interviews', headers=manager).json()
    assert len(ordinary) == 2 and {x['username'] for x in ordinary} == {'alice'}
    uid = client.get('/api/me', headers=alice).json()['id']
    assert {x['user_id'] for x in ordinary} == {uid}
    assert client.post(f'/api/admin/users/{uid}/username', headers=root, json={'username': 'renamed student'}).status_code == 200
    renamed = client.get('/api/admin/interviews', headers=manager).json()
    assert {x['user_id'] for x in renamed} == {uid}
    assert {x['username'] for x in renamed} == {'renamed student'}
    assert len(client.get('/api/admin/interviews', headers=root).json()) == 3
