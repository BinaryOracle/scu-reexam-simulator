"""Shared grants, contest rosters and published homepage edits remain authoritative."""
import time
from test_system import client, login


def test_practice_grant_applies_to_both_modules_and_revokes_live_sessions(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    started = client.post('/api/training/sessions', headers=alice, json={'collection_id': 'data_structures'}).json()
    assert 'id' in started
    assert client.patch('/api/admin/users/3', headers=manager, json={'can_practice': False}).status_code == 200
    for path in ['/api/training/home', '/api/coding/home', '/api/training/questions?mine=true', '/api/coding/questions?mine=true']:
        assert client.get(path, headers=alice).status_code == 200
    for path in ['/api/training/questions', '/api/coding/questions', f"/api/training/sessions/{started['id']}"]:
        assert client.get(path, headers=alice).status_code == 403
    for path in ['/api/training/sessions', '/api/training/checkin', '/api/coding/daily', '/api/coding/checkin']:
        assert client.post(path, headers=alice, json={}).status_code == 403
    public = client.get('/api/coding/questions', headers=manager).json()['items'][0]['id']
    assert client.get(f'/api/coding/questions/{public}', headers=alice).status_code == 403
    assert client.post(f'/api/coding/questions/{public}/submissions', headers=alice, json={'source':'print(1)', 'language':'python3'}).status_code == 403
    assert client.patch('/api/admin/users/3', headers=manager, json={'can_practice': True}).json()['can_practice']
    assert client.get(f"/api/training/sessions/{started['id']}", headers=alice).status_code == 200


def test_training_and_coding_permissions_are_independent(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    assert client.patch(f'/api/admin/users/{uid}', headers=manager,
                        json={'can_training': True, 'can_coding': False}).status_code == 200
    profile = client.get('/api/me', headers=alice).json()
    assert profile['can_training'] is True
    assert profile['can_coding'] is False
    assert client.post('/api/training/sessions', headers=alice,
                       json={'collection_id': 'data_structures'}).status_code == 201
    assert client.post('/api/coding/daily', headers=alice).status_code == 403

    assert client.patch(f'/api/admin/users/{uid}', headers=manager,
                        json={'can_training': False, 'can_coding': True}).status_code == 200
    profile = client.get('/api/me', headers=alice).json()
    assert profile['can_training'] is False
    assert profile['can_coding'] is True
    assert client.post('/api/training/sessions', headers=alice,
                       json={'collection_id': 'data_structures'}).status_code == 403
    assert client.post('/api/coding/daily', headers=alice).status_code in (200, 409)


def test_new_accounts_default_to_no_practice_and_admin_has_effective_grant(client):
    manager = login(client, 'manager')
    new = client.post('/api/admin/users', headers=manager, json={'username':'new', 'password':'x'}).json()
    assert new['can_practice'] is False
    from app.db import connect
    with connect() as db:
        db.execute('UPDATE users SET can_practice=0 WHERE id=2')
    assert client.get('/api/me', headers=manager).json()['can_practice'] is True
    assert client.post('/api/coding/daily', headers=manager).status_code == 200


def test_selected_contest_roster_protects_details_and_guessed_apis(client):
    manager, alice, bob = (login(client, name) for name in ['manager','alice','bob'])
    now = time.time()
    payload = {'title':'指定用户赛', 'starts':now-10, 'ends':now+1000, 'participant_ids':[3],
               'problems':[{'title':'加法', 'statement':'加法', 'remote_problem_id':'P1001'}]}
    created = client.post('/api/admin/contests', headers=manager, json=payload).json()
    cid, pid = created['id'], created['problem_ids'][0]
    assert client.get('/api/contests', headers=bob).json()[0]['can_access'] is False
    for suffix in ['', '/problems', '/ranking']:
        assert client.get(f'/api/contests/{cid}{suffix}', headers=bob).status_code == 403
        assert client.get(f'/api/contests/{cid}{suffix}', headers=alice).status_code == 200
    assert client.post(f'/api/problems/{pid}/submissions', headers=bob, json={'source':'pass'}).status_code == 403
    sid = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source':'pass'}).json()['id']
    assert client.put(f'/api/admin/contests/{cid}', headers=manager, json={**payload,'participant_ids':[4]}).status_code == 200
    assert client.get(f'/api/submissions/{sid}', headers=alice).status_code == 403
    assert client.get('/api/submissions', headers=alice).json()['total'] == 0
    assert client.post(f'/api/submissions/{sid}/remote-result', headers=alice, json={'status':'Judging','remote_submission_id':'123'}).status_code == 403
    assert client.get(f'/api/contests/{cid}', headers=bob).status_code == 200
    assert client.get(f'/api/contests/{cid}', headers=manager).status_code == 200
    assert client.get(f'/api/admin/contests/{cid}/participants', headers=manager).json()['participant_ids'] == [4]
    assert client.put(f'/api/admin/contests/{cid}', headers=manager, json={**payload,'participant_ids':[99999]}).status_code == 422
    assert client.get(f'/api/admin/contests/{cid}/participants', headers=manager).json()['participant_ids'] == [4]


def test_new_empty_roster_denies_normal_users_and_ended_contests_require_membership(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    payload = {'title':'结束的比赛', 'starts':now-100, 'ends':now-10,
               'problems':[{'title':'题目','statement':'描述','remote_problem_id':'P1001'}]}
    cid = client.post('/api/admin/contests', headers=manager, json=payload).json()['id']
    assert client.get(f'/api/contests/{cid}', headers=alice).status_code == 403
    assert client.get('/api/contests', headers=alice).json()[0]['title'] == '结束的比赛'
    assert client.get('/api/admin/contest-participants', headers=alice).status_code == 403


def test_home_layout_order_visibility_validation_and_conflicting_save(client):
    manager, alice = login(client,'manager'), login(client,'alice')
    original = client.get('/api/admin/home-layout', headers=manager).json()
    assert original['blocks'][0]['type'] == 'roadmap'
    assert client.get('/api/home/layout').status_code == 401
    assert client.get('/api/admin/home-layout', headers=alice).status_code == 403
    original['blocks'].reverse()
    original['blocks'][0]['title'] = '自定义资料'
    original['blocks'][0]['items'][0]['enabled'] = False
    original['blocks'][1]['enabled'] = False
    saved = client.put('/api/admin/home-layout', headers=manager, json=original)
    assert saved.status_code == 200, saved.text
    public = client.get('/api/home/layout', headers=alice).json()
    assert public['blocks'][0]['title'] == '自定义资料'
    assert len(public['blocks']) == len(original['blocks']) - 1
    assert len(public['blocks'][0]['items']) == len(original['blocks'][0]['items']) - 1
    assert client.put('/api/admin/home-layout', headers=manager, json=original).status_code == 409
    broken = saved.json()
    broken['blocks'][0]['items'][0]['url'] = 'javascript:alert(1)'
    broken['blocks'][0]['items'][0]['kind'] = 'external'
    assert client.put('/api/admin/home-layout', headers=manager, json=broken).status_code == 422
    from app.db import initialize
    initialize()
    assert client.get('/api/home/layout', headers=alice).json() == public


def test_migration_preserves_existing_permissions_and_contests(client):
    from app.db import connect, initialize
    with connect() as db:
        db.execute('ALTER TABLE users DROP COLUMN can_practice')
        db.execute('DROP TABLE contest_participants')
        db.execute('ALTER TABLE contests DROP COLUMN access_mode')
        db.execute("INSERT INTO contests(title,starts,ends) VALUES ('旧比赛',0,1)")
        db.execute('PRAGMA user_version=27')
    initialize()
    alice = login(client, 'alice')
    assert client.get('/api/me', headers=alice).json()['can_practice']
    assert client.get('/api/contests', headers=alice).json()[0]['can_access']
    assert client.get('/api/contests/1', headers=alice).status_code == 200
