"""Administrator reveal never exposes password material through public APIs."""
import pytest
from test_admin_permissions import legacy_client, login


def test_password_reveal_is_admin_only_and_never_in_account_lists(legacy_client):
    manager = login(legacy_client, 'manager')
    alice = login(legacy_client, 'alice')
    uid = legacy_client.get('/api/me', headers=alice).json()['id']
    path = f'/api/admin/users/{uid}/reveal-password'
    assert legacy_client.post(path).status_code == 401
    assert legacy_client.post(path, headers=alice).status_code == 403
    revealed = legacy_client.post(path, headers=manager)
    assert revealed.status_code == 200
    assert revealed.json() == {'password': 'password123'}
    assert revealed.headers['cache-control'] == 'no-store'
    for row in legacy_client.get('/api/admin/users', headers=manager).json():
        assert not {'password', 'password_ciphertext'} & row.keys()
        assert 'password_available' in row
    assert 'password' not in legacy_client.get('/api/me', headers=alice).json()


def test_new_and_reset_passwords_can_be_revealed_and_remain_hashed(legacy_client):
    from app.db import connect
    from app.services.security import verify_password
    manager = login(legacy_client, 'manager')
    secret = ' 密码🙂 <& '
    created = legacy_client.post('/api/admin/users', headers=manager,
        json={'username': '任意账号', 'password': secret})
    assert created.status_code == 201
    uid = created.json()['id']
    path = f'/api/admin/users/{uid}/reveal-password'
    assert legacy_client.post(path, headers=manager).json() == {'password': secret}
    with connect() as db:
        row = db.execute('SELECT password,password_ciphertext FROM users WHERE id=?', (uid,)).fetchone()
        assert verify_password(secret, row['password'])
        assert secret not in row['password_ciphertext']
    assert legacy_client.post(f'/api/admin/users/{uid}/password', headers=manager,
        json={'password': 'x'}).status_code == 200
    assert legacy_client.post(path, headers=manager).json() == {'password': 'x'}
    login(legacy_client, '任意账号', 'x')


def test_legacy_password_cannot_be_recovered_until_reset_or_successful_login(legacy_client):
    manager = login(legacy_client, 'manager')
    rows = legacy_client.get('/api/admin/users', headers=manager).json()
    bob = next(row for row in rows if row['username'] == 'bob')
    assert bob['password_available'] is False
    path = f"/api/admin/users/{bob['id']}/reveal-password"
    assert legacy_client.post(path, headers=manager).status_code == 409
    login(legacy_client, 'bob')
    assert legacy_client.post(path, headers=manager).json() == {'password': 'password123'}
    assert legacy_client.post('/api/admin/users/9999/reveal-password', headers=manager).status_code == 404


def test_missing_or_incorrect_encryption_key_fails_without_changing_password(legacy_client):
    from app.config import load_config
    from pathlib import Path
    from cryptography.fernet import Fernet
    manager = login(legacy_client, 'manager')
    uid = legacy_client.get('/api/me', headers=manager).json()['id']
    key_path = Path(load_config()['security']['password_key_file'])
    key = key_path.read_bytes()
    assert key_path.stat().st_mode & 0o077 == 0
    try:
        for replacement in (None, Fernet.generate_key()):
            if replacement is None:
                key_path.unlink()
            else:
                key_path.write_bytes(replacement)
            response = legacy_client.post(f'/api/admin/users/{uid}/reveal-password', headers=manager)
            assert response.status_code == 503
            assert 'password' not in response.json()
    finally:
        key_path.write_bytes(key)
    assert legacy_client.post(f'/api/admin/users/{uid}/reveal-password', headers=manager).json()['password'] == 'password123'
