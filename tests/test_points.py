"""Points purchases, historical package retirement and weekly reward accounting."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from test_system import client, login

SHANGHAI = ZoneInfo('Asia/Shanghai')


def _fund(client, amount):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    assert client.patch(f'/api/admin/users/{uid}', headers=admin, json={'points': amount}).status_code == 200
    return admin, alice, uid


def _buy(client, alice, key, quantity=1, cost=1):
    return client.post('/api/profile/purchases', headers=alice, json={
        'product': 'interview', 'quantity': quantity, 'idempotency_key': key, 'expected_unit_cost': cost})


def test_purchase_deducts_points_not_money_and_retries_once(client):
    admin, alice, uid = _fund(client, 6)
    assert client.patch('/api/admin/credit-settings', headers=admin, json={'interview_points_cost': 2}).status_code == 200
    stale = _buy(client, alice, 'old-price-001', cost=1)
    assert stale.status_code == 409
    assert client.get('/api/profile', headers=alice).json()['points'] == 6
    first = _buy(client, alice, 'new-price-001', quantity=2, cost=2)
    assert first.status_code == 200, first.text
    assert first.json()['points'] == 2 and first.json()['remaining'] == 3
    retry = _buy(client, alice, 'new-price-001', quantity=2, cost=2)
    assert retry.json()['already_purchased'] is True
    assert retry.json()['points'] == 2 and retry.json()['remaining'] == 3
    assert _buy(client, alice, 'new-price-001', quantity=1, cost=2).status_code == 409
    assert client.get('/api/profile', headers=alice).json()['redeemed_amount_fen'] == 0
    from app.db import connect
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM points_purchases WHERE user_id=?', (uid,)).fetchone()[0] == 1
        assert db.execute("SELECT SUM(delta) FROM points_ledger WHERE user_id=? AND kind='purchase_interview'", (uid,)).fetchone()[0] == -4


def test_concurrent_purchases_cannot_overspend(client):
    _, alice, _ = _fund(client, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda n: _buy(client, alice, f'purchase-key-{n}'), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    profile = client.get('/api/profile', headers=alice).json()
    assert profile['points'] == 0 and profile['remaining'] == 2
    assert len(client.get('/api/profile/shop', headers=alice).json()['purchases']) == 1


def test_package_deletion_permanently_removes_issued_codes_and_history(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    package = client.post('/api/admin/voucher-packages', headers=admin, json={'price_fen': 1234, 'credits': 8}).json()['id']
    cards = client.post('/api/admin/vouchers', headers=admin, json={'package': package, 'count': 2}).json()
    card = cards[0]
    redeemed = client.post('/api/profile/redeem', headers=alice, json={'code': card['code']})
    assert redeemed.status_code == 200 and redeemed.json()['points'] == 8
    assert client.delete(f'/api/admin/voucher-packages/{package}', headers=alice).status_code == 403
    assert client.delete(f'/api/admin/voucher-packages/{package}', headers=admin).status_code == 204
    settings = client.get('/api/admin/credit-settings', headers=admin).json()
    assert package not in {p['id'] for p in settings['packages']}
    assert client.post('/api/admin/vouchers', headers=admin, json={'package': package, 'count': 1}).status_code == 422
    assert client.get('/api/admin/vouchers', headers=admin, params={'package': package}).json()['total'] == 0
    assert client.get('/api/admin/vouchers/export', headers=admin, params={'package': package}).text == ''
    for item in cards:
        assert client.post('/api/profile/redeem', headers=alice, json={'code': item['code']}).status_code == 404
    profile = client.get('/api/profile', headers=alice).json()
    assert profile['points'] == 8 and profile['redemptions'] == [] and profile['redeemed_amount_fen'] == 0
    recreated = client.post('/api/admin/voucher-packages', headers=admin, json={'price_fen': 1234, 'credits': 8})
    assert recreated.status_code == 201
    assert client.post('/api/admin/vouchers', headers=admin, json={'package': recreated.json()['id'], 'count': 1}).status_code == 201


def test_legacy_retired_packages_are_purged_during_migration(client):
    from app.db import connect
    from app.services.points import initialize
    admin = login(client, 'manager')
    package = client.post('/api/admin/voucher-packages', headers=admin,
                          json={'price_fen': 876, 'credits': 4}).json()['id']
    client.post('/api/admin/vouchers', headers=admin, json={'package': package, 'count': 1})
    with connect() as db:
        db.execute('UPDATE voucher_packages SET deleted=1 WHERE id=?', (package,))
        initialize(db)
        assert db.execute('SELECT 1 FROM voucher_packages WHERE id=?', (package,)).fetchone() is None
        assert db.execute('SELECT COUNT(*) FROM vouchers WHERE package=?', (package,)).fetchone()[0] == 0


def test_points_migration_preserves_existing_allowances_and_account_deletion(client):
    admin, alice, uid = _fund(client, 9)
    _buy(client, alice, 'delete-test-001')
    from app.db import initialize, connect
    initialize(); initialize()
    profile = client.get('/api/profile', headers=alice).json()
    assert profile['points'] == 8 and profile['remaining'] == 2
    assert client.delete(f'/api/admin/users/{uid}', headers=admin).status_code == 204
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM points_ledger WHERE user_id=?', (uid,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM points_purchases WHERE user_id=?', (uid,)).fetchone()[0] == 0
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_admin_can_configure_all_points_reward_sources_in_one_place(client):
    admin = login(client, 'manager')
    alice = login(client, 'alice')
    response = client.patch('/api/admin/credit-settings', headers=admin, json={
        'invite_signup_points': 5,
        'training_checkin_points_per_week': 2,
        'coding_checkin_points_per_week': 4,
        'training_questions_per_reward': 3,
        'training_contribution_points': 2,
        'coding_questions_per_reward': 4,
        'coding_contribution_points': 3,
        'leaderboard_rewards': [6, 4, 2],
    })
    assert response.status_code == 200, response.text
    rules = response.json()['reward_rules']
    assert rules == {
        'invite_signup_points': 5,
        'training_checkin_points_per_week': 2,
        'coding_checkin_points_per_week': 4,
        'training_questions_per_reward': 3,
        'training_contribution_points': 2,
        'coding_questions_per_reward': 4,
        'coding_contribution_points': 3,
        'leaderboard_rewards': [6, 4, 2],
    }
    training_home = client.get('/api/training/home', headers=alice).json()
    coding_home = client.get('/api/coding/home', headers=alice).json()
    assert training_home['checkin_points_per_week'] == 2
    assert training_home['next_reward'] == 2
    assert coding_home['daily']['checkin_points_per_week'] == 4
    assert coding_home['daily']['next_reward'] == 4
    assert client.get('/api/leaderboard', headers=alice).json()['rewards'] == [6, 4, 2]


def _seed_boards(db, username, value, *, day='2026-11-20'):
    uid = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()[0]
    questions = [r[0] for r in db.execute('SELECT id FROM training_questions ORDER BY id LIMIT ?', (value,))]
    coding = [r[0] for r in db.execute('SELECT id FROM coding_questions ORDER BY id LIMIT ?', (value,))]
    for index in range(value):
        date = f'2026-11-{20-index}' if day == '2026-11-20' else day
        db.execute('INSERT INTO training_checkins(user_id,date,streak,streak_start) VALUES (?,?,1,?)', (uid, date, date))
        db.execute('INSERT INTO coding_checkins(user_id,date,streak,credits) VALUES (?,?,1,0)', (uid, date))
        db.execute('INSERT INTO training_daily_questions(user_id,date,question_id) VALUES (?,?,?)', (uid, date, questions[index]))
        # A repeated accepted submission is one passed problem in each ranking period.
        for _ in range(2):
            db.execute('''INSERT INTO coding_submissions(user_id,question_id,question_version,question_content_version,
                question_title,judge_mode,language,source,status,created,completed_date)
                VALUES (?,?,1,1,'题目','samples','cpp11','int main(){}','Accepted',1,?)''', (uid, coding[index], date))
    return uid


def test_four_weekly_boards_settle_three_two_one_and_only_once(client):
    from app.db import connect
    from app.services import leaderboard
    from app.services.security import hash_password
    with connect() as db:
        db.execute("INSERT INTO users(username,password,is_admin,is_active) VALUES ('carol',?,0,1)", (hash_password('x'),))
        db.execute("INSERT INTO users(username,password,is_admin,is_active) VALUES ('zero',?,0,1)", (hash_password('x'),))
        db.execute("UPDATE app_settings SET value=? WHERE key='leaderboard_rewards_started'", (str(datetime(2026, 11, 14, tzinfo=SHANGHAI).timestamp()),))
        for username, value in [('alice',3), ('bob',2), ('carol',1), ('manager',5)]:
            _seed_boards(db, username, value)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert leaderboard.settle_due(db, datetime(2026,11,20,23,59,59,tzinfo=SHANGHAI)) == 0
        assert leaderboard.settle_due(db, datetime(2026,11,21,0,0,tzinfo=SHANGHAI)) == 1
        assert leaderboard.settle_due(db, datetime(2026,11,21,0,0,tzinfo=SHANGHAI)) == 0
        balances = {r['username']: r['points'] for r in db.execute('SELECT username,points FROM users')}
        assert [balances[n] for n in ('alice','bob','carol','zero','manager')] == [12,8,4,0,0]
        assert db.execute('SELECT COUNT(*) FROM leaderboard_reward_grants').fetchone()[0] == 12
        assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE kind='leaderboard_reward'").fetchone()[0] == 12
        # The new weekly board starts empty after settlement; all-time totals remain.
        user = db.execute("SELECT * FROM users WHERE username='alice'").fetchone()
        now = datetime(2026,11,21,0,0,tzinfo=SHANGHAI)
        weekly = leaderboard.snapshot(db, user, 'coding', 'weekly', now)
        assert next(r['value'] for r in weekly['boards']['coding_solved'] if r['username']=='alice') == 0
        all_time = leaderboard.snapshot(db, user, 'coding', 'all', now)
        assert next(r['value'] for r in all_time['boards']['coding_solved'] if r['username']=='alice') == 3


def test_first_activation_has_no_retroactive_settlements_and_zero_scores_do_not_win(client):
    from app.db import connect
    from app.services import leaderboard
    activated = datetime(2026,11,17,12,tzinfo=SHANGHAI)
    with connect() as db:
        db.execute("UPDATE app_settings SET value=? WHERE key='leaderboard_rewards_started'", (str(activated.timestamp()),))
        _seed_boards(db,'alice',1,day='2026-11-13')
        db.execute('BEGIN IMMEDIATE') if not db.in_transaction else None
        assert leaderboard.settle_due(db,datetime(2026,11,28,0,0,tzinfo=SHANGHAI)) == 2
        assert db.execute('SELECT COUNT(*) FROM leaderboard_reward_grants').fetchone()[0] == 0
        assert db.execute('SELECT SUM(points) FROM users').fetchone()[0] == 0
        assert db.execute('SELECT MIN(period_end) FROM leaderboard_settlements').fetchone()[0].startswith('2026-11-21')
