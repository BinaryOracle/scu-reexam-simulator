from test_system import client, login


def test_leaderboard_excludes_admin_and_deduplicates_accepted(client):
    alice = login(client, 'alice')
    bob = login(client, 'bob')
    manager = login(client, 'manager')
    from app.db import connect

    with connect() as db:
        ids = {name: db.execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()[0]
               for name in ('alice', 'bob', 'manager')}
        training_question = db.execute('SELECT id FROM training_questions LIMIT 1').fetchone()[0]
        coding_question = db.execute('SELECT id FROM coding_questions LIMIT 1').fetchone()[0]
        for table in ('training_checkins', 'coding_checkins', 'training_daily_questions', 'coding_submissions'):
            db.execute(f'DELETE FROM {table} WHERE user_id IN (?,?,?)', tuple(ids.values()))
        for day in ('2026-11-15', '2026-11-16'):
            db.execute(
                'INSERT INTO training_checkins(user_id,date,streak,streak_start) VALUES (?,?,?,?)',
                (ids['alice'], day, 1, day),
            )
        db.execute(
            'INSERT INTO coding_checkins(user_id,date,streak,credits) VALUES (?,?,?,?)',
            (ids['bob'], '2026-11-16', 1, 0),
        )
        db.execute(
            'INSERT INTO training_daily_questions(user_id,date,question_id) VALUES (?,?,?)',
            (ids['alice'], '2026-11-16', training_question),
        )
        for created in (1, 2):
            db.execute('''INSERT INTO coding_submissions(
                user_id,question_id,question_version,question_content_version,question_title,
                judge_mode,remote_problem_id,language,source,status,created,completed_date
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
                ids['alice'], coding_question, 1, 1, '题目', 'samples', '', 'cpp11',
                'int main(){}', 'Accepted', created, '2026-11-16',
            ))

    response = client.get('/api/leaderboard?scope=training&range=all', headers=alice)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload['boards']) == {'training_checkins', 'training_questions'}
    assert all(item['username'] != 'manager' for board in payload['boards'].values() for item in board)
    assert next(item for item in payload['boards']['training_checkins'] if item['username'] == 'alice')['value'] == 2
    assert next(item for item in payload['boards']['training_questions'] if item['username'] == 'alice')['value'] == 1
    coding = client.get('/api/leaderboard?scope=coding&range=all', headers=alice).json()
    assert set(coding['boards']) == {'coding_checkins', 'coding_solved'}
    assert next(item for item in coding['boards']['coding_solved'] if item['username'] == 'alice')['value'] == 1
    assert coding['me']['coding_solved'] == 1
    assert client.get('/api/leaderboard?scope=training&range=all', headers=bob).json()['me']['training_checkins'] == 2
    assert client.get('/api/leaderboard?scope=training&range=all', headers=manager).json()['me'] is None


def test_leaderboard_ties_are_sorted_by_username(client):
    alice = login(client, 'alice')
    bob = login(client, 'bob')
    response = client.get('/api/leaderboard?scope=training&range=all', headers=alice)
    assert response.status_code == 200
    rows = response.json()['boards']['training_questions']
    assert [row['username'] for row in rows[:2]] == ['alice', 'bob']
    assert [row['rank'] for row in rows[:2]] == [1, 2]
