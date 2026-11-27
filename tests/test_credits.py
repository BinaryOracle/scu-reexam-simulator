"""Quota charging, administrator grants, and single-use voucher redemption."""
from concurrent.futures import ThreadPoolExecutor
from test_system import client, login


def test_configurable_initial_points_and_administrator_allowance(client):
    manager = login(client, 'manager')
    profile = client.get('/api/profile', headers=manager).json()
    assert profile['is_admin'] is True and profile['remaining'] is None
    assert client.get('/api/me', headers=manager).json()['interview_credits'] is None
    settings = client.get('/api/admin/credit-settings', headers=manager).json()
    assert settings['default_points'] == 3
    assert 'default_credits' not in settings
    first = client.post('/api/admin/users', headers=manager,
        json={'username': 'default-points', 'password': 'a'}).json()
    assert first['points'] == 3 and first['interview_credits'] == 0
    assert client.patch('/api/admin/credit-settings', headers=manager, json={'default_points': 4}).status_code == 200
    user = client.post('/api/admin/users', headers=manager, json={'username': 'new', 'password': 'a'}).json()
    assert user['points'] == 4 and user['interview_credits'] == 0
    for value in (0, 7):
        specified = client.post('/api/admin/users', headers=manager,
            json={'username': f'specified-{value}', 'password': 'a', 'points': value}).json()
        assert specified['points'] == value and specified['interview_credits'] == 0
    existing = next(row for row in client.get('/api/admin/users', headers=manager).json() if row['id'] == first['id'])
    assert existing['points'] == 3 and existing['interview_credits'] == 0
    assert client.patch(f"/api/admin/users/{user['id']}", headers=manager, json={'interview_credits': 2}).json()['interview_credits'] == 2
    for invalid in (-1, True, 1.5, 1000001):
        assert client.patch('/api/admin/credit-settings', headers=manager, json={'default_points': invalid}).status_code == 422
    assert client.patch('/api/admin/credit-settings', headers=login(client, 'alice'), json={'default_points': 9}).status_code == 403
    assert client.patch('/api/admin/credit-settings', headers=manager, json={'default_points': 0}).status_code == 200
    zero = client.post('/api/admin/users', headers=manager, json={'username': 'zero-default', 'password': 'a'}).json()
    assert zero['points'] == 0
    from app.db import connect
    with connect() as db:
        ledger = db.execute('SELECT delta,kind FROM points_ledger WHERE user_id=?', (user['id'],)).fetchall()
        assert [(row['delta'], row['kind']) for row in ledger] == [(4, 'initial')]


def test_initial_points_migration_preserves_balances_and_saved_default(client):
    from app.db import connect, initialize, SCHEMA_VERSION
    with connect() as db:
        db.execute("UPDATE users SET points=8,interview_credits=6 WHERE username='alice'")
        db.execute("UPDATE app_settings SET value='0' WHERE key='default_points'")
        db.execute('PRAGMA user_version=45')
    initialize()
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert db.execute("SELECT value FROM app_settings WHERE key='default_points'").fetchone()[0] == '3'
        user = db.execute("SELECT points,interview_credits FROM users WHERE username='alice'").fetchone()
        assert tuple(user) == (8, 6)
        db.execute("UPDATE app_settings SET value='0' WHERE key='default_points'")
    initialize()
    with connect() as db:
        assert db.execute("SELECT value FROM app_settings WHERE key='default_points'").fetchone()[0] == '0'
        db.execute("UPDATE app_settings SET value='9' WHERE key='default_points'")
        db.execute('PRAGMA user_version=45')
    initialize()
    with connect() as db:
        assert db.execute("SELECT value FROM app_settings WHERE key='default_points'").fetchone()[0] == '9'


def test_console_user_receives_current_initial_points(client, monkeypatch):
    from app.db import connect
    from scripts import create_user
    with connect() as db:
        db.execute("UPDATE app_settings SET value='5' WHERE key='default_points'")
    monkeypatch.setattr('sys.argv', ['create_user', 'console-student'])
    monkeypatch.setattr(create_user, 'getpass', lambda _: 'password123')
    create_user.main()
    with connect() as db:
        user = db.execute("SELECT id,points,interview_credits FROM users WHERE username='console-student'").fetchone()
        assert (user['points'], user['interview_credits']) == (5, 0)
        assert db.execute('SELECT delta FROM points_ledger WHERE user_id=?', (user['id'],)).fetchone()[0] == 5


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
    assert [profile['remaining'] for profile in profiles] == [1, 1]
    assert sorted(profile['points'] for profile in profiles) == [0, 3]
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
    assert profile['remaining'] == 1 and profile['points'] == 10 and profile['redeemed_amount_fen'] == 500
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
    search_code = client.get('/api/admin/vouchers/export', headers=manager, params={'package': 'three', 'status': 'all', 'q': first[1]['code'][-8:]})
    assert search_code.text.splitlines() == [first[1]['code']]
    search_user = client.get('/api/admin/vouchers/export', headers=manager, params={'package': 'three', 'status': 'all', 'q': 'alice'})
    assert search_user.text.splitlines() == [first[0]['code']]
    no_match = client.get('/api/admin/vouchers/export', headers=manager, params={'package': 'three', 'q': 'no-such-code'})
    assert no_match.text == ''
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
