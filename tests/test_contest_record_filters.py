"""Contest detail drill-downs keep every filter and administrator visibility in sync."""
import time

from test_system import client, login


def records(client):
    from app.db import connect
    manager, alice, bob = (login(client, name) for name in ('manager', 'alice', 'bob'))
    root_response = client.post('/api/login', json={'username': 'root', 'password': 'root'})
    root = {'Authorization': 'Bearer ' + root_response.json()['token']}
    now = time.time()
    response = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids': [3,4], 'title': '筛选比赛', 'starts': now - 60, 'ends': now + 3600,
        'problems': [{'title': '加法', 'statement': '求和', 'remote_problem_id': 'P1001'},
                     {'title': '问候', 'statement': '问候', 'remote_problem_id': 'B2002'}],
    })
    assert response.status_code == 200, response.text
    created = response.json()
    cid, (a, b) = created['id'], created['problem_ids']
    other = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids': [3,4], 'title': '其他比赛', 'starts': now - 60, 'ends': now + 3600,
        'problems': [{'title': '其他题', 'statement': '求和', 'remote_problem_id': 'P1001'}],
    }).json()['problem_ids'][0]
    ids = {}
    with connect() as db:
        users = {row['username']: row['id'] for row in db.execute('SELECT id,username FROM users')}
        for key, username, pid, status in [
            ('alice_a_wrong', 'alice', a, 'Wrong Answer'),
            ('alice_a_ac', 'alice', a, 'Accepted'),
            ('alice_b', 'alice', b, 'Judging'),
            ('bob_a', 'bob', a, 'Accepted'),
            ('manager_a', 'manager', a, 'Accepted'),
            ('root_a', 'root', a, 'Accepted'),
            ('other_contest', 'alice', other, 'Accepted'),
        ]:
            ids[key] = db.execute('''INSERT INTO submissions
                (user_id,problem_id,language,source,status,created,detail)
                VALUES (?,?,?,?,?,?,?)''', (users[username], pid, 'python3', 'print(3)', status, now, '评测信息')).lastrowid
    return manager, alice, root, users, cid, a, b, ids


def test_user_and_problem_drill_downs_are_scoped_and_paginated(client):
    manager, _, _, users, cid, a, _, ids = records(client)
    base = f'/api/admin/submissions?contest_id={cid}&user_id={users["alice"]}&page_size=1'
    first = client.get(base, headers=manager).json()
    assert (first['total'], first['pages']) == (3, 3)
    assert first['items'][0]['id'] == ids['alice_b']
    assert first['stats'] == {'accepted': 1, 'judging': 1}
    second = client.get(base + '&page=2', headers=manager).json()
    assert second['items'][0]['id'] == ids['alice_a_ac']
    problem = client.get(base + f'&problem_id={a}&page_size=10', headers=manager).json()
    assert {item['id'] for item in problem['items']} == {ids['alice_a_wrong'], ids['alice_a_ac']}
    assert problem['total'] == 2


def test_problem_attempt_and_accepted_lists_match_participant_metrics(client):
    _, _, root, _, cid, a, _, ids = records(client)
    overview = client.get(f'/api/contests/{cid}', headers=root).json()['problems'][0]
    base = f'/api/admin/submissions?contest_id={cid}&problem_id={a}&participants_only=true'
    attempts = client.get(base, headers=root).json()
    accepted = client.get(base + '&status=Accepted', headers=root).json()
    assert attempts['total'] == overview['attempt_count'] == 3
    assert accepted['total'] == overview['accepted_count'] == 2
    assert {item['id'] for item in accepted['items']} == {ids['alice_a_ac'], ids['bob_a']}
    assert accepted['stats'] == {'accepted': 2, 'judging': 0}


def test_filters_cannot_expose_administrator_records_to_regular_admins(client):
    manager, alice, root, users, cid, _, _, ids = records(client)
    base = f'/api/admin/submissions?contest_id={cid}'
    assert client.get(base, headers=alice).status_code == 403
    assert client.get(base).status_code == 401
    for name in ('manager', 'root'):
        restricted = client.get(base + f'&user_id={users[name]}', headers=manager).json()
        assert restricted['total'] == 0 and not restricted['items']
    visible = client.get(base, headers=root).json()
    assert visible['total'] == 6
    assert ids['manager_a'] in {item['id'] for item in visible['items']}
    for query in ('user_id=0', 'problem_id=-1', 'status=not-a-verdict'):
        assert client.get(base + '&' + query, headers=root).status_code == 422
