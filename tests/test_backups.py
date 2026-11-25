"""Complete credential exports, isolated restore validation, and failure rollback."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from test_system import client, login


@pytest.fixture(autouse=True)
def no_background_writes(monkeypatch):
    from app.services import leaderboard_scheduler, trend_scheduler
    monkeypatch.setattr(leaderboard_scheduler, 'start', lambda: None)
    monkeypatch.setattr(trend_scheduler, 'start', lambda: None)


def root(client):
    response = client.post('/api/login', json={'username': 'root', 'password': 'root'})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def export(client, headers, modules=None):
    from app.services.backups import module_ids
    response = client.post('/api/admin/backups/export', headers=headers,
                           json={'modules': sorted(module_ids()) if modules is None else modules})
    assert response.status_code == 200, response.text
    return response.content


def preview(client, headers, content):
    return client.post('/api/admin/backups/preview', headers=headers,
                       files={'file': ('backup.zip', content, 'application/zip')})


def restore(client, headers, content, *, confirmation='RESTORE', digest=None):
    return client.post('/api/admin/backups/restore', headers=headers,
                       files={'file': ('backup.zip', content, 'application/zip')},
                       data={'confirmation': confirmation, 'sha256': digest or hashlib.sha256(content).hexdigest()})


def rewrite(content, change):
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        files = {name: bundle.read(name) for name in bundle.namelist()}
    manifest = json.loads(files.pop('manifest.json'))
    change(files, manifest)
    manifest['entries'] = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as bundle:
        for name, value in files.items():
            bundle.writestr(name, value)
        bundle.writestr('manifest.json', json.dumps(manifest))
    return output.getvalue()


def test_backups_are_superadmin_only_including_upload_and_restore(client):
    owner, manager, student = root(client), login(client, 'manager'), login(client, 'alice')
    for actor in (manager, student, {}):
        expected = 403 if actor else 401
        assert client.get('/api/admin/backups/modules', headers=actor).status_code == expected
        assert client.post('/api/admin/backups/export', headers=actor, json={'modules': ['accounts']}).status_code == expected
        assert preview(client, actor, b'invalid').status_code == expected
        assert restore(client, actor, b'invalid').status_code == expected
    catalog = client.get('/api/admin/backups/modules', headers=owner).json()
    assert len(catalog) == 12
    assert next(m for m in catalog if m['id'] == 'accounts')['rows'] == 4


def test_archive_keeps_passwords_and_key_but_excludes_live_sessions(client):
    from app.db import connect
    from app.services.password_vault import decrypt_password
    owner = root(client)
    content = export(client, owner, ['accounts', 'settings'])
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        manifest = json.loads(bundle.read('manifest.json'))
        users = json.loads(bundle.read('accounts/users.json'))['rows']
        saved = next(user for user in users if user['username'] == 'root')
        with connect() as db:
            current = db.execute("SELECT * FROM users WHERE username='root'").fetchone()
            assert saved['password'] == current['password']
            assert saved['password_ciphertext'] == current['password_ciphertext']
        assert decrypt_password(saved['password_ciphertext']) == 'root'
        assert 'credentials/password-view.key' in bundle.namelist()
        assert not any('sessions.json' in n or 'playback' in n for n in bundle.namelist())
        assert manifest['format'] == 'scu-reexam-backup-v2'
        assert {m['id'] for m in manifest['modules']} == {'accounts', 'credits', 'settings'}
        assert 'no-store' in client.post('/api/admin/backups/export', headers=owner,
                                         json={'modules': ['settings']}).headers['cache-control']


def test_full_roundtrip_restores_login_password_view_settings_and_wallet(client):
    from app.db import connect
    from app.services.password_vault import encrypt_password, decrypt_password
    from app.services.security import hash_password
    owner = root(client)
    with connect() as db:
        db.execute("UPDATE users SET password=?,password_ciphertext=?,points=42 WHERE username='alice'",
                   (hash_password('原密码 中文 '), encrypt_password('原密码 中文 ')))
        saved_key = encrypt_password('provider-secret')
        db.execute("INSERT INTO app_settings VALUES ('ai_model_settings',?)",
                   (json.dumps({'interview': {'model': 'restored-model', 'api_key_encrypted': saved_key}}),))
    content = export(client, owner, ['accounts', 'settings'])
    with connect() as db:
        db.execute("UPDATE users SET password=?,password_ciphertext=?,points=0 WHERE username='alice'",
                   (hash_password('changed'), encrypt_password('changed')))
        db.execute("UPDATE app_settings SET value='9' WHERE key='interview_points_cost'")
    response = preview(client, owner, content)
    assert response.status_code == 200, response.text
    assert response.json()['includes_passwords'] is True
    assert '原密码' not in response.text and 'provider-secret' not in response.text
    with connect() as db:
        assert db.execute("SELECT points FROM users WHERE username='alice'").fetchone()[0] == 0
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    assert response.json()['requires_login'] is True
    assert client.get('/api/me', headers=owner).status_code == 401
    login_response = client.post('/api/login', json={'username': 'alice', 'password': '原密码 中文 '})
    assert login_response.status_code == 200
    owner = root(client)
    uid = client.get('/api/me', headers={'Authorization': 'Bearer ' + login_response.json()['token']}).json()['id']
    assert client.post(f'/api/admin/users/{uid}/reveal-password', headers=owner).json()['password'] == '原密码 中文 '
    with connect() as db:
        assert db.execute('SELECT points FROM users WHERE id=?', (uid,)).fetchone()[0] == 42
        assert db.execute("SELECT value FROM app_settings WHERE key='interview_points_cost'").fetchone()[0] == '1'
        settings = json.loads(db.execute("SELECT value FROM app_settings WHERE key='ai_model_settings'").fetchone()[0])
        assert decrypt_password(settings['interview']['api_key_encrypted']) == 'provider-secret'
    from app.config import load_config
    safety = Path(load_config()['backups']['directory']) / response.json()['safety_backup']
    assert (safety / 'database.sqlite3').is_file() and (safety / 'password-view.key').is_file()
    assert (safety / 'database.sqlite3').stat().st_mode & 0o777 == 0o600


def test_restore_reencrypts_for_current_deployment_key(client):
    from app.db import connect
    from app.config import load_config
    from app.services.password_vault import decrypt_password, encrypt_password
    owner = root(client)
    with connect() as db:
        db.execute("INSERT INTO app_settings VALUES ('ai_model_settings',?)",
                   (json.dumps({'asr': {'api_key_encrypted': encrypt_password('asr-secret')}}),))
        db.execute("INSERT INTO app_settings VALUES ('feishu_credentials',?)",
                   (json.dumps({'app_id': 'cli_backup', 'app_secret_encrypted': encrypt_password('feishu-secret')}),))
    content = export(client, owner, ['accounts', 'settings'])
    key_path = Path(load_config()['security']['password_key_file'])
    target_key = Fernet.generate_key()
    key_path.write_bytes(target_key)
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    assert key_path.read_bytes() == target_key
    with connect() as db:
        assert decrypt_password(db.execute("SELECT password_ciphertext FROM users WHERE username='root'").fetchone()[0]) == 'root'
        config = json.loads(db.execute("SELECT value FROM app_settings WHERE key='ai_model_settings'").fetchone()[0])
        assert decrypt_password(config['asr']['api_key_encrypted']) == 'asr-secret'
        feishu = json.loads(db.execute("SELECT value FROM app_settings WHERE key='feishu_credentials'").fetchone()[0])
        assert decrypt_password(feishu['app_secret_encrypted']) == 'feishu-secret'
    assert root(client)


def test_partial_restore_preserves_unselected_accounts_and_requires_new_session(client):
    from app.db import connect
    owner = root(client)
    content = export(client, owner, ['announcements'])
    with connect() as db:
        db.execute("UPDATE users SET points=123 WHERE username='alice'")
        db.execute("UPDATE announcements SET title='changed' WHERE id=(SELECT MIN(id) FROM announcements)")
    assert restore(client, owner, content).status_code == 200
    with connect() as db:
        assert db.execute("SELECT points FROM users WHERE username='alice'").fetchone()[0] == 123
        assert not db.execute("SELECT 1 FROM announcements WHERE title='changed'").fetchone()


def test_media_restore_maps_paths_to_current_roots_and_deduplicates_nested_directories(client, monkeypatch, tmp_path):
    from app.db import connect
    from app.services import backups
    owner = root(client)
    source = tmp_path / 'source'
    (source / 'nested').mkdir(parents=True)
    (source / 'nested' / 'sample.txt').write_text('original')
    monkeypatch.setattr(backups, 'media_roots', lambda: {'audio': source, 'courses': source / 'nested'})
    with connect() as db:
        db.execute("INSERT INTO interviews(user_id,created) VALUES (1,1)")
        iid = db.execute('SELECT MAX(id) FROM interviews').fetchone()[0]
        db.execute('INSERT INTO presentations VALUES (?,?,?,?)', (iid, str(source / 'nested'), 'demo.pptx', 1))
    content = export(client, owner, ['interviews', 'media'])
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        assert bundle.namelist().count('media/courses/sample.txt') == 1
        assert not any(n == 'media/audio/nested/sample.txt' for n in bundle.namelist())
    target = tmp_path / 'target'
    monkeypatch.setattr(backups, 'media_roots', lambda: {'audio': target, 'courses': target / 'nested'})
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    assert (target / 'nested' / 'sample.txt').read_text() == 'original'
    with connect() as db:
        assert db.execute('SELECT directory FROM presentations WHERE interview_id=?', (iid,)).fetchone()[0] == str(target / 'nested')


def test_restore_media_failure_rolls_back_database_and_already_replaced_files(client, monkeypatch, tmp_path):
    from app.db import connect
    from app.services import backups, backup_restore
    owner = root(client)
    media = tmp_path / 'media'
    media.mkdir()
    (media / 'a.txt').write_text('saved a')
    (media / 'b.txt').write_text('saved b')
    monkeypatch.setattr(backups, 'media_roots', lambda: {'audio': media})
    content = export(client, owner, ['accounts', 'media'])
    (media / 'a.txt').write_text('current a')
    (media / 'b.txt').write_text('current b')
    with connect() as db:
        db.execute("UPDATE users SET points=567 WHERE username='alice'")
    replace = backup_restore.os.replace
    def fail_second(source, target):
        if Path(target).name == 'b.txt':
            raise OSError('simulated disk failure')
        return replace(source, target)
    monkeypatch.setattr(backup_restore.os, 'replace', fail_second)
    response = restore(client, owner, content)
    assert response.status_code == 503
    assert (media / 'a.txt').read_text() == 'current a'
    assert (media / 'b.txt').read_text() == 'current b'
    assert client.get('/api/me', headers=owner).status_code == 200
    with connect() as db:
        assert db.execute("SELECT points FROM users WHERE username='alice'").fetchone()[0] == 567


@pytest.mark.parametrize('kind', ['version', 'traversal', 'tampered', 'old', 'foreign_key', 'missing_key', 'columns'])
def test_invalid_archives_are_rejected_without_changes(client, kind):
    from app.db import connect
    owner = root(client)
    content = export(client, owner, ['accounts', 'settings'])
    def change(files, manifest):
        if kind == 'version': manifest['database_version'] += 1
        if kind == 'traversal': files['media/audio/../../bad'] = b'invalid'
        if kind == 'old': manifest['format'] = 'scu-reexam-backup-v1'
        if kind == 'missing_key': files.pop('credentials/password-view.key')
        if kind in ('foreign_key', 'columns'):
            doc = json.loads(files['accounts/users.json'])
            if kind == 'foreign_key': doc['rows'] = [r for r in doc['rows'] if r['is_superadmin']]
            if kind == 'columns': doc['columns'].append('arbitrary_sql')
            files['accounts/users.json'] = json.dumps(doc).encode()
    content = rewrite(content, change)
    if kind == 'tampered':
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(content)) as bundle, zipfile.ZipFile(output, 'w') as rewritten:
            for name in bundle.namelist():
                rewritten.writestr(name, b'{}' if name == 'accounts/users.json' else bundle.read(name))
        content = output.getvalue()
    # Ensure an external reference exists for the orphan-account case.
    with connect() as db:
        uid = db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        db.execute('INSERT INTO interviews(user_id,created) VALUES (?,1)', (uid,))
    assert preview(client, owner, content).status_code == 422
    assert restore(client, owner, content).status_code == 422
    assert client.get('/api/me', headers=owner).status_code == 200
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 4


def test_restore_requires_confirmation_and_unchanged_file(client):
    owner = root(client)
    content = export(client, owner, ['announcements'])
    assert restore(client, owner, content, confirmation='').status_code == 422
    assert restore(client, owner, content, digest='0' * 64).status_code == 409
    assert client.get('/api/me', headers=owner).status_code == 200


def test_exports_reject_empty_unknown_or_duplicate_modules(client):
    owner = root(client)
    for modules in ([], ['unknown'], ['accounts', 'accounts']):
        assert client.post('/api/admin/backups/export', headers=owner, json={'modules': modules}).status_code == 422


def test_restore_refuses_ongoing_interviews(client):
    import time
    from app.db import connect
    owner = root(client)
    content = export(client, owner, ['announcements'])
    with connect() as db:
        db.execute('INSERT INTO interviews(user_id,created,started_at,deadline_at) VALUES (1,?,?,?)',
                   (time.time(), time.time(), time.time() + 300))
    assert restore(client, owner, content).status_code == 409
    assert client.get('/api/me', headers=owner).status_code == 200


def test_complete_backup_covers_all_persistent_tables_and_restores_them(client):
    from app.db import connect
    from app.services import backups
    owner = root(client)
    content = export(client, owner)
    with connect() as db:
        existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    exported = {t for m in backups.MODULES for t in m['tables']}
    assert existing == exported | set(backups.TRANSIENT_TABLES)
    response = preview(client, owner, content)
    assert response.status_code == 200, response.text
    assert response.json()['files'] > 0  # The default course assets are included.
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    assert root(client)


def test_media_links_duplicates_and_size_limits_are_rejected(client, monkeypatch, tmp_path):
    from app.services import backups, backup_restore
    owner = root(client)
    content = export(client, owner, ['media'])
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret').write_text('never change')
    media = tmp_path / 'root'
    media.mkdir()
    (media / 'linked').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(backups, 'media_roots', lambda: {'audio': media})
    attack = rewrite(content, lambda files, manifest: files.update({'media/audio/linked/secret': b'overwritten'}))
    assert preview(client, owner, attack).status_code == 422
    assert (outside / 'secret').read_text() == 'never change'
    original = backup_restore.load_config
    def limited():
        config = original()
        config['backups']['max_expanded_mb'] = 1
        return config
    monkeypatch.setattr(backup_restore, 'load_config', limited)
    attack = rewrite(export(client, owner, ['media']), lambda files, manifest: files.update({'media/audio/large': b'0' * (2 * 1024 * 1024)}))
    assert preview(client, owner, attack).status_code == 422


def test_restore_maintenance_refuses_other_inflight_requests(client):
    from app.services import backup_maintenance as gate
    owner = root(client)
    content = export(client, owner, ['announcements'])
    assert gate.enter_request()
    try:
        response = restore(client, owner, content)
        assert response.status_code == 409
    finally:
        gate.leave_request()
    with gate.exclusive_restore():
        assert client.get('/api/me', headers=owner).status_code == 503
    assert client.get('/api/me', headers=owner).status_code == 200


def test_roundtrip_supports_wal_database_and_self_contained_safety_snapshot(client):
    import sqlite3
    from app.db import connect
    from app.config import load_config
    owner = root(client)
    with connect() as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        db.execute("UPDATE users SET points=8 WHERE username='alice'")
    content = export(client, owner, ['accounts'])
    with connect() as db:
        db.execute("UPDATE users SET points=9 WHERE username='alice'")
    assert preview(client, owner, content).status_code == 200
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    safety = Path(load_config()['backups']['directory']) / response.json()['safety_backup'] / 'database.sqlite3'
    with sqlite3.connect(safety) as db:
        assert db.execute("SELECT points FROM users WHERE username='alice'").fetchone()[0] == 9
    with connect() as db:
        assert db.execute("SELECT points FROM users WHERE username='alice'").fetchone()[0] == 8


def test_partial_restore_rejects_different_account_with_same_id(client):
    from app.db import connect
    owner = root(client)
    content = export(client, owner, ['courses'])
    with connect() as db:
        db.execute("UPDATE users SET username='different-owner' WHERE username='root'")
    response = preview(client, owner, content)
    assert response.status_code == 422
    assert '关联账号' in response.json()['detail']
    assert client.get('/api/me', headers=owner).json()['username'] == 'different-owner'


def test_restore_preserves_id_highwater_even_for_records_deleted_before_backup(client):
    from app.db import connect, allocate_user_id
    owner = root(client)
    with connect() as db:
        db.execute("UPDATE sqlite_sequence SET seq=999999 WHERE name='training_questions'")
        db.execute("UPDATE app_settings SET value='500' WHERE key='user_id_highwater'")
    content = export(client, owner, ['accounts', 'training'])
    with connect() as db:
        db.execute("UPDATE sqlite_sequence SET seq=0 WHERE name='training_questions'")
        db.execute("UPDATE app_settings SET value='10' WHERE key='user_id_highwater'")
    response = restore(client, owner, content)
    assert response.status_code == 200, response.text
    with connect() as db:
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='training_questions'").fetchone()[0] == 999999
        assert allocate_user_id(db) == 501
