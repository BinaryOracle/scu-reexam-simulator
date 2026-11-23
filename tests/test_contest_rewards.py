"""Per-contest awards use final rankings and one atomic, durable settlement."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_system import client, login


def seed_contest(db, *, pending=False, ranking_rule='score', ends=None):
    from app.services.security import hash_password
    now = time.time()
    if not db.execute("SELECT 1 FROM users WHERE username='carol'").fetchone():
        db.execute("INSERT INTO users(username,password) VALUES ('carol',?)", (hash_password('x'),))
    cid = db.execute('INSERT INTO contests(title,starts,ends,ranking_rule) VALUES (?,?,?,?)',
                     ('奖励模拟赛', now - 100, ends or now + 10, ranking_rule)).lastrowid
    db.execute("UPDATE contests SET access_mode='all' WHERE id=?", (cid,))
    pid = db.execute("""INSERT INTO problems(contest_id,title,statement,sample_input,sample_output,tests)
        VALUES (?,'题目','题目','','','[]')""", (cid,)).lastrowid
    for name, status, detail in [('manager', 'Accepted', ''), ('alice', 'Accepted', ''),
                                ('bob', 'Wrong Answer', '通过测试点数：2 / 3'),
                                ('carol', 'Judging' if pending else 'Wrong Answer', '通过测试点数：1 / 3')]:
        uid = db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()[0]
        db.execute("""INSERT INTO submissions(user_id,problem_id,language,source,status,created,detail)
            VALUES (?,?,'python3','print(1)',?,?,?)""", (uid, pid, status, now - 1, detail))
    return cid, pid, now + 20


def test_contest_award_rules_default_configure_and_permissions(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/admin/credit-settings', headers=admin).json()['reward_rules']['contest_rewards'] == [9, 6, 3]
    payload = {'contest_rewards': [12, 8, 0]}
    assert client.patch('/api/admin/credit-settings', headers=alice, json=payload).status_code == 403
    result = client.patch('/api/admin/credit-settings', headers=admin, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['reward_rules']['contest_rewards'] == [12, 8, 0]
    for invalid in ([1, 2], [1, 2, 3, 4], [-1, 2, 3], [True, 2, 3], [1.5, 2, 3], [1000001, 2, 3]):
        assert client.patch('/api/admin/credit-settings', headers=admin,
                            json={'contest_rewards': invalid}).status_code == 422


def test_completed_contest_grants_nine_six_three_once_and_retains_history(client):
    from app.db import connect, initialize
    from app.services import contest_rewards
    with connect() as db:
        cid, pid, after = seed_contest(db)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert contest_rewards.settle_due(db) == 0
        assert contest_rewards.settle_due(db, now=after) == 1
        assert contest_rewards.settle_due(db, now=after) == 0
        assert [db.execute('SELECT points FROM users WHERE username=?', (name,)).fetchone()[0]
                for name in ('alice', 'bob', 'carol', 'manager')] == [9, 6, 3, 0]
        assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE kind='contest_reward'").fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM contest_reward_grants WHERE contest_id=?', (cid,)).fetchone()[0] == 3
    initialize()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert contest_rewards.settle_due(db, now=after) == 0
        # Deleting a recipient or a contest must not reactivate its paid awards.
        from app.services.account_deletion import delete_account
        delete_account(db, db.execute("SELECT * FROM users WHERE username='alice'").fetchone())
        assert db.execute('SELECT user_id FROM contest_reward_grants WHERE contest_id=? AND rank=1', (cid,)).fetchone()[0] is None
        db.execute('DELETE FROM submissions WHERE problem_id=?', (pid,))
        db.execute('DELETE FROM problems WHERE id=?', (pid,))
        db.execute('DELETE FROM contests WHERE id=?', (cid,))
        assert db.execute('SELECT COUNT(*) FROM contest_reward_grants WHERE contest_id=?', (cid,)).fetchone()[0] == 3
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []


def test_pending_judges_delay_settlement_and_rules_are_read_at_settlement(client):
    from app.db import connect
    from app.services import contest_rewards
    admin = login(client, 'manager')
    with connect() as db:
        cid, pid, after = seed_contest(db, pending=True)
        assert contest_rewards.settle_due(db, now=after) == 0
    assert client.patch('/api/admin/credit-settings', headers=admin,
                        json={'contest_rewards': [7, 4, 0]}).status_code == 200
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE submissions SET status='Wrong Answer' WHERE problem_id=? AND status='Judging'", (pid,))
        assert contest_rewards.settle_due(db, now=after) == 1
        assert [r[0] for r in db.execute('SELECT points FROM contest_reward_grants WHERE contest_id=? ORDER BY rank', (cid,))] == [7, 4]
        assert contest_rewards.settle_due(db, now=after) == 0


def test_no_retroactive_awards_and_no_zero_score_or_out_of_time_winners(client):
    from app.db import connect
    from app.services import contest_rewards
    with connect() as db:
        old, _, after = seed_contest(db, ends=time.time() - 200)
        cid, pid, _ = seed_contest(db)
        db.execute("UPDATE submissions SET status='Wrong Answer',detail='' WHERE problem_id=?", (pid,))
        # An out-of-time accepted record must not affect final rankings or delay settlement.
        uid = db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        db.execute("""INSERT INTO submissions(user_id,problem_id,language,source,status,created)
            VALUES (?,?,'python3','x','Accepted',?)""", (uid, pid, after + 10))
        assert contest_rewards.settle_due(db, now=after) == 1
        assert db.execute('SELECT COUNT(*) FROM contest_reward_settlements WHERE contest_id=?', (old,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM contest_reward_grants').fetchone()[0] == 0


def test_concurrent_settlement_and_acm_ranking_share_one_result(client):
    from app.db import connect
    from app.services import contest_rewards, contest_scoring
    with connect() as db:
        cid, _, after = seed_contest(db, ranking_rule='acm')
        contest = db.execute('SELECT * FROM contests WHERE id=?', (cid,)).fetchone()
        assert [r['username'] for r in contest_scoring.ranked_rows(db, contest)] == ['alice', 'bob', 'carol']
    def settle(_):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return contest_rewards.settle_due(db, now=after)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(settle, range(2))) == [0, 1]
    with connect() as db:
        assert db.execute('SELECT SUM(delta) FROM points_ledger').fetchone()[0] == 18


def test_ranking_endpoint_settles_and_reports_receipts_without_repeat_payout(client):
    from app.db import connect
    alice, admin = login(client, 'alice'), login(client, 'manager')
    with connect() as db:
        cid, _, _ = seed_contest(db)
        db.execute('UPDATE contests SET ends=? WHERE id=?', (time.time(), cid))
    result = client.get(f'/api/contests/{cid}/ranking', headers=alice)
    assert result.status_code == 200, result.text
    awards = result.json()['rewards']
    assert awards['amounts'] == [9, 6, 3] and awards['settled'] and awards['eligible']
    assert [r['points'] for r in awards['grants']] == [9, 6, 3]
    assert [r['username'] for r in result.json()['rows']] == ['alice', 'bob', 'carol']
    for _ in range(2):
        assert client.get(f'/api/contests/{cid}/ranking', headers=alice).json()['rewards'] == awards
    profile = client.get('/api/profile', headers=alice).json()
    assert profile['points'] == 9
    assert len([r for r in profile['points_history'] if r['kind'] == 'contest_reward']) == 1
    assert client.patch('/api/admin/credit-settings', headers=admin,
                        json={'contest_rewards': [90, 60, 30]}).status_code == 200
    assert client.get(f'/api/contests/{cid}/ranking', headers=alice).json()['rewards'] == awards
    with connect() as db:
        db.execute('UPDATE contests SET show_ranking=0 WHERE id=?', (cid,))
    hidden = client.get(f'/api/contests/{cid}/ranking', headers=alice).json()
    assert hidden['visible'] is False and hidden['rewards']['grants'] == []
    assert client.delete(f'/api/admin/contests/{cid}', headers=admin).status_code == 204
    created = client.post('/api/admin/contests', headers=admin, json={
        'title': '新比赛', 'starts': time.time(), 'ends': time.time() + 100,
        'judge_mode': 'docker', 'participant_ids': [],
        'problems': [{'title': '题目', 'statement': '题目', 'tests': [{'input': '', 'output': '1'}]}]})
    assert created.status_code == 200, created.text
    assert created.json()['id'] > cid


def test_wallet_failure_rolls_back_settlement_and_all_awards(client, monkeypatch):
    from app.db import connect
    from app.services import contest_rewards, points
    with connect() as db:
        cid, _, after = seed_contest(db)
    original = points.adjust
    def fail_second(db, uid, delta, **kwargs):
        if delta == 6:
            raise RuntimeError('wallet unavailable')
        return original(db, uid, delta, **kwargs)
    monkeypatch.setattr(points, 'adjust', fail_second)
    with pytest.raises(RuntimeError, match='wallet unavailable'):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            contest_rewards.settle_due(db, now=after)
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM contest_reward_settlements WHERE contest_id=?', (cid,)).fetchone()[0] == 0
        assert db.execute('SELECT SUM(points) FROM users').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE kind='contest_reward'").fetchone()[0] == 0
    monkeypatch.setattr(points, 'adjust', original)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        assert contest_rewards.settle_due(db, now=after) == 1
