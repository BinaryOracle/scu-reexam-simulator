"""Quota charging, administrator grants, and single-use voucher redemption."""
from concurrent.futures import ThreadPoolExecutor
from test_system import client, login


def test_configurable_default_and_administrator_numeric_allowance(client):
    manager = login(client, 'manager')
    profile = client.get('/api/profile', headers=manager).json()
    assert profile['is_admin'] is True and profile['remaining'] is None
    assert client.get('/api/me', headers=manager).json()['interview_credits'] is None
    settings = client.get('/api/admin/credit-settings', headers=manager)
    assert settings.json()['default_credits'] == 1
    assert client.patch('/api/admin/credit-settings', headers=manager, json={'default_credits': 4}).status_code == 200
    user = client.post('/api/admin/users', headers=manager, json={'username': 'new', 'password': 'a'}).json()
    assert user['interview_credits'] == 4
    specified = client.post('/api/admin/users', headers=manager,
        json={'username': 'specified', 'password': 'a', 'interview_credits': 7}).json()
    assert specified['interview_credits'] == 7
    assert client.patch(f"/api/admin/users/{user['id']}", headers=manager, json={'interview_credits': 2}).json()['interview_credits'] == 2
    for invalid in (-1, True, 1.5):
        assert client.patch('/api/admin/credit-settings', headers=manager, json={'default_credits': invalid}).status_code == 422


def test_administrator_start_paths_keep_999999_without_charges(client):
    from test_presentations import deck_bytes, upload
    from app.db import connect
    from test_admin_permissions import login as role_login
    creator = role_login(client, 'root', 'root')
    account = client.post('/api/admin/users', headers=creator,
        json={'username': 'quota-admin', 'password': 'password123', 'is_admin': True}).json()
    manager = login(client, 'quota-admin')
    direct = client.post('/api/interviews/start', headers=manager,
        files={'file': ('intro.pdf', deck_bytes(), 'application/pdf')})
    assert direct.status_code == 201
    iid = client.post('/api/interviews', headers=manager).json()['id']
    assert upload(client, iid, manager).status_code == 200
    for _ in range(2):
        assert client.post(f'/api/interviews/{iid}/start', headers=manager).status_code == 200
    assert client.get('/api/profile', headers=manager).json()['remaining'] is None
    assert client.get('/api/me', headers=manager).json()['interview_credits'] is None
    with connect() as db:
        assert db.execute('SELECT interview_credits FROM users WHERE id=?', (account['id'],)).fetchone()[0] == 999999
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='interview'").fetchone()[0] == 0


def test_quota_charged_only_once_after_start_and_not_refunded_by_deletion(client):
    from test_presentations import upload
    alice = login(client, 'alice')
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 1
    iid = client.post('/api/interviews', headers=alice).json()['id']
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 1
    assert client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 409
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 1
    assert upload(client, iid, alice).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 200
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 0
    assert client.delete(f'/api/interviews/{iid}', headers=alice).status_code == 204
    next_id = client.post('/api/interviews', headers=alice).json()['id']
    assert upload(client, next_id, alice).status_code == 200
    assert client.post(f'/api/interviews/{next_id}/start', headers=alice).status_code == 409


def test_vouchers_are_unique_separate_packages_and_redeemed_atomically(client):
    manager, alice, bob = [login(client, name) for name in ('manager', 'alice', 'bob')]
    created = client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 3})
    assert created.status_code == 201
    codes = [row['code'] for row in created.json()]
    assert len(set(codes)) == 3
    assert all(len(code.split('-')) == 6 for code in codes)
    assert client.post('/api/admin/vouchers', headers=manager, json={'package': 'ten', 'count': 2}).status_code == 201
    assert client.get('/api/admin/vouchers?package=three&status=unused', headers=manager).json()['total'] == 3
    assert client.get('/api/admin/vouchers?package=ten', headers=manager).json()['total'] == 2
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda headers: client.post('/api/profile/redeem', headers=headers,
            json={'code': codes[0].lower().replace('-', ' ')}), [alice, bob]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    profiles = [client.get('/api/profile', headers=headers).json() for headers in (alice, bob)]
    assert sorted(profile['remaining'] for profile in profiles) == [1, 4]
    assert sum(profile['redeemed_amount_fen'] for profile in profiles) == 200
    used = client.get('/api/admin/vouchers?package=three&status=redeemed', headers=manager).json()['items']
    assert len(used) == 1 and used[0]['redeemed_by'] in ('alice', 'bob')
    assert client.post('/api/profile/redeem', headers=alice, json={'code': codes[0]}).status_code == 409
    assert client.get('/api/admin/vouchers', headers=alice).status_code == 403
    assert client.get('/api/admin/credit-settings', headers=alice).status_code == 403
    assert client.post('/api/profile/redeem', headers=alice, json={'code': 'bad'}).status_code == 422
    assert client.post('/api/admin/vouchers', headers=manager, json={'package': 'unknown', 'count': 1}).status_code == 422
    assert client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 0}).status_code == 422


def test_redemption_history_uses_issue_time_package_value_and_user_isolation(client, monkeypatch):
    manager, alice, bob = [login(client, name) for name in ('manager', 'alice', 'bob')]
    card = client.post('/api/admin/vouchers', headers=manager, json={'package': 'ten', 'count': 1}).json()[0]
    redeemed = client.post('/api/profile/redeem', headers=alice, json={'code': card['code']})
    assert redeemed.status_code == 200
    profile = client.get('/api/profile', headers=alice).json()
    assert profile['remaining'] == 11 and profile['redeemed_amount_fen'] == 500
    assert profile['redemptions'][0]['credits'] == 10
    assert card['code'] not in str(profile)
    assert client.get('/api/profile', headers=bob).json()['redemptions'] == []
    assert client.post('/api/profile/redeem', headers=manager, json={'code': card['code']}).status_code == 409


def test_direct_upload_start_cannot_overspend_and_cleans_failed_storage(client):
    from test_presentations import deck_bytes
    from app.db import connect
    from app.config import load_config
    from pathlib import Path
    alice = login(client, 'alice')
    data = deck_bytes()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post('/api/interviews/start', headers=alice,
            files={'file': ('intro.pdf', data, 'application/pdf')}), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 0
    assert len(client.get('/api/interviews', headers=alice).json()) == 1
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='interview'").fetchone()[0] == 1
    assert len(list(Path(load_config()['presentation']['directory']).iterdir())) == 1


def test_export_is_separated_by_package_status_and_batch(client):
    manager, alice = [login(client, name) for name in ('manager', 'alice')]
    first = client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 2}).json()
    other = client.post('/api/admin/vouchers', headers=manager, json={'package': 'three', 'count': 1}).json()
    ten = client.post('/api/admin/vouchers', headers=manager, json={'package': 'ten', 'count': 1}).json()
    assert client.post('/api/profile/redeem', headers=alice, json={'code': first[0]['code']}).status_code == 200
    exported = client.get(f"/api/admin/vouchers/export?package=three&status=unused&batch={first[0]['batch']}", headers=manager)
    assert exported.status_code == 200
    assert exported.text.splitlines() == [first[1]['code']]
    assert exported.headers['cache-control'] == 'no-store'
    assert client.get('/api/admin/vouchers/export?package=ten', headers=manager).text.splitlines() == [ten[0]['code']]
    assert client.get('/api/admin/vouchers/export?package=three', headers=alice).status_code == 403


def test_repeated_migration_preserves_credits_and_admin_has_numeric_allowance(client):
    from app.db import initialize, connect
    with connect() as db:
        db.execute("UPDATE users SET interview_credits=8 WHERE username='alice'")
    initialize(); initialize()
    assert client.get('/api/profile', headers=login(client, 'alice')).json()['remaining'] == 8
    manager = login(client, 'manager')
    from test_admin_permissions import login as role_login
    root = role_login(client, 'root', 'root')
    admin = client.post('/api/admin/users', headers=root,
        json={'username': 'another-admin', 'password': 'a', 'is_admin': True, 'interview_credits': 1}).json()
    assert admin['interview_credits'] == 999999
    with connect() as db:
        assert db.execute('SELECT interview_credits FROM users WHERE id=?', (admin['id'],)).fetchone()[0] == 999999
