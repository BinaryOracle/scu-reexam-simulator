"""Visibility, review ordering, learning progress and atomic streak credits."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from test_system import client, login


def post(c, path, headers, body=None):
    return c.post('/api' + path, headers=headers, json=body or {})


def start(c, headers, **options):
    response = post(c, '/training/sessions', headers, {'collection_id': 'data_structures', 'mode': 'sequential', **options})
    assert response.status_code == 201, response.text
    return response.json()


def finish(c, headers, session):
    for card in session['cards']:
        response = post(c, f"/training/sessions/{session['id']}/cards/{card['id']}/complete", headers)
        assert response.status_code == 200, response.text
    return response.json()


def create(c, headers, question='自定义问题', collection='data_structures', answer='参考内容'):
    response = post(c, '/training/questions', headers, dict(collection_id=collection, question=question, answer=answer))
    assert response.status_code == 201, response.text
    return response.json()


def test_seed_and_random_round_no_duplicates_and_private_isolation(client):
    a, b = login(client, 'alice'), login(client, 'bob')
    home = client.get('/api/training/home', headers=a).json()
    assert sum(c['count'] for c in home['collections'] if c['section_id']=='interview') == 180
    assert home['goal'] == 5 and home['completed'] == 0 and home['remaining'] == 1
    private = create(client, a)
    assert private['visibility'] == 'private'
    assert client.get('/api/training/questions?mine=true', headers=b).json()['total'] == 0
    assert client.get('/api/training/questions?q=自定义问题', headers=b).json()['total'] == 0
    assert client.put(f"/api/training/questions/{private['id']}/favorite", headers=b, json={'favorite': True}).status_code == 404
    assert client.patch(f"/api/training/questions/{private['id']}", headers=b, json=dict(collection_id='data_structures', question='盗改', version=1)).status_code == 404
    s = start(client, a, mode='random')
    assert len({c['question_id'] for c in s['cards']}) == 5
    assert post(client, '/training/sessions', a).status_code == 409
    assert client.get(f"/api/training/sessions/{s['id']}", headers=b).status_code == 404


def test_sequential_completion_advances_only_completed_cards_and_resumes(client):
    a = login(client, 'alice')
    s = start(client, a)
    first, second = s['cards'][:2]
    assert '时间复杂度' in first['question'] and '空间复杂度' in second['question']
    assert post(client, f"/training/sessions/{s['id']}/cards/{second['id']}/complete", a).status_code == 409
    path = f"/training/sessions/{s['id']}/cards/{first['id']}/complete"
    assert post(client, path, a).json()['completed'] == 1
    assert post(client, path, a).json()['completed'] == 1
    assert client.get('/api/training/home', headers=a).json()['completed'] == 1
    assert client.get(f"/api/training/sessions/{s['id']}", headers=a).json()['completed'] == 1
    assert post(client, f"/training/sessions/{s['id']}/end", a).status_code == 204
    next_round = start(client, a)
    assert next_round['cards'][0]['question_id'] == second['question_id']


def test_favorites_small_pool_and_distinct_daily_goal(client):
    a = login(client, 'alice')
    item = create(client, a)
    assert post(client, '/training/sessions', a, {'source': 'favorites'}).status_code == 409
    client.put(f"/api/training/questions/{item['id']}/favorite", headers=a, json={'favorite': True})
    for _ in range(2):
        s = start(client, a, source='favorites')
        assert s['total'] == 1
        finish(client, a, s)
    assert client.get('/api/training/home', headers=a).json()['completed'] == 1
    assert post(client, '/training/checkin', a).status_code == 409


def test_pending_review_private_and_edit_requires_new_review(client):
    a, b, m = [login(client, n) for n in ('alice', 'bob', 'manager')]
    item = create(client, a)
    assert client.get('/api/admin/training/questions?status=all&q=自定义问题', headers=m).json()['total'] == 0
    assert post(client, f"/admin/training/questions/{item['id']}/review", m, {'version': 1, 'approve': True}).status_code == 404
    pending = post(client, f"/training/questions/{item['id']}/submit", a, {'version': item['version']}).json()
    assert client.get('/api/training/questions?q=自定义问题', headers=b).json()['total'] == 0
    assert client.get('/api/admin/training/questions?status=pending', headers=m).json()['total'] == 1
    assert post(client, f"/admin/training/questions/{item['id']}/review", m, {'version': 1, 'approve': True}).status_code == 409
    approved = post(client, f"/admin/training/questions/{item['id']}/review", m, {'version': pending['version'], 'approve': True}).json()
    assert approved['visibility'] == 'public'
    assert client.get('/api/training/questions?q=自定义问题', headers=b).json()['total'] == 1
    updated = client.patch(f"/api/training/questions/{item['id']}", headers=a, json=dict(collection_id='data_structures', question='修改后问题', answer='新答案', version=approved['version'])).json()
    assert updated['visibility'] == 'private' and updated['review_status'] == 'draft'
    assert client.get('/api/training/questions?q=修改后问题', headers=b).json()['total'] == 0


def test_withdraw_reject_and_administrator_identity_hierarchy(client):
    from test_admin_permissions import login as root_login
    m, a = login(client, 'manager'), login(client, 'alice')
    root = root_login(client, 'root', 'root')
    item = create(client, m)
    pending = post(client, f"/training/questions/{item['id']}/submit", m, {'version': 1}).json()
    assert client.get('/api/admin/training/questions?status=pending', headers=m).json()['total'] == 0
    assert post(client, f"/admin/training/questions/{item['id']}/review", m, {'version': pending['version'], 'approve': True}).status_code == 404
    assert client.get('/api/admin/training/questions?status=pending', headers=root).json()['total'] == 1
    rejection = post(client, f"/admin/training/questions/{item['id']}/review", root, {'version': pending['version'], 'approve': False, 'reason': '请补充来源'}).json()
    assert rejection['review_status'] == 'rejected' and rejection['review_reason'] == '请补充来源'
    assert client.get('/api/admin/training/settings', headers=a).status_code == 403


def test_removed_question_redacted_in_saved_session_and_not_counted(client):
    a, b, m = [login(client, n) for n in ('alice', 'bob', 'manager')]
    item = create(client, a)
    pending = post(client, f"/training/questions/{item['id']}/submit", a, {'version': 1}).json()
    approved = post(client, f"/admin/training/questions/{item['id']}/review", m, {'version': pending['version'], 'approve': True}).json()
    client.put(f"/api/training/questions/{item['id']}/favorite", headers=b, json={'favorite': True})
    s = start(client, b, source='favorites')
    client.patch(f"/api/training/questions/{item['id']}", headers=a, json=dict(collection_id='data_structures', question='撤回稿件', answer='', version=approved['version']))
    card = client.get(f"/api/training/sessions/{s['id']}", headers=b).json()['cards'][0]
    assert card['available'] is False and card['answer'] == '' and '自定义问题' not in card['question']
    finish(client, b, s)
    assert client.get('/api/training/home', headers=b).json()['completed'] == 0


def test_goal_snapshot_and_import_validation_are_atomic(client):
    import io, json
    a, m = login(client, 'alice'), login(client, 'manager')
    assert client.get('/api/training/home', headers=a).json()['goal'] == 5
    start(client, a)
    assert client.patch('/api/admin/training/settings', headers=m, json={'daily_goal': 2, 'round_size': 2}).status_code == 200
    assert client.get('/api/training/home', headers=a).json()['goal'] == 5
    good = dict(collection_id='oral', question='What is a process?', answer='')
    bad = dict(collection_id='oral', question='中文题目', answer='不应有答案')
    preview = client.post('/api/training/import/preview', headers=a,
        files={'file': ('questions.json', io.BytesIO(json.dumps([good,bad]).encode()), 'application/json')}).json()
    assert len(preview['errors']) == 1
    assert post(client, '/training/import', a, {'items': [good,bad]}).status_code == 422
    assert client.get('/api/training/questions?mine=true', headers=a).json()['total'] == 0
    assert post(client, '/training/import', a, {'items': [good]}).json()['created'] == 1


def test_streak_rewards_7_14_21_and_repeat_checkin(client, monkeypatch):
    from app.services import training
    a = login(client, 'alice')
    base = date(2026, 11, 1)
    for n in range(21):
        monkeypatch.setattr(training, 'today', lambda n=n: base + timedelta(days=n))
        while client.get('/api/training/home', headers=a).json()['completed'] < 5:
            finish(client, a, start(client, a))
        response = post(client, '/training/checkin', a)
        assert response.status_code == 200, response.text
        assert response.json()['credits'] == ((n+1)//7 if (n+1)%7 == 0 else 0)
        assert post(client, '/training/checkin', a).json()['already_checked'] is True
    profile = client.get('/api/profile', headers=a).json()
    assert profile['remaining'] == 7 and profile['redeemed_amount_fen'] == 0
    from app.db import connect
    with connect() as db:
        assert [r[0] for r in db.execute("SELECT delta FROM credit_ledger WHERE kind='checkin_reward' ORDER BY id")] == [1,2,3]
    monkeypatch.setattr(training, 'today', lambda: base + timedelta(days=22))
    finish(client, a, start(client, a))
    assert post(client, '/training/checkin', a).json()['home']['streak'] == 1


def test_concurrent_checkin_rewards_once_and_rolls_back_failure(client, monkeypatch):
    from app.services import training, credits
    from app.db import connect
    a = login(client, 'alice')
    day = training.today()
    finish(client, a, start(client, a))
    with connect() as db:
        uid = db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        db.execute('INSERT INTO training_checkins(user_id,date,streak,streak_start) VALUES (?,?,?,?)',
                   (uid, (day-timedelta(days=1)).isoformat(), 6, (day-timedelta(days=6)).isoformat()))
    original = credits.adjust
    def failure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('forced ledger rollback')
    monkeypatch.setattr(credits, 'adjust', failure)
    import pytest
    with pytest.raises(RuntimeError):
        post(client, '/training/checkin', a)
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_checkins WHERE user_id=? AND date=?', (uid, day.isoformat())).fetchone()[0] == 0
        assert db.execute('SELECT interview_credits FROM users WHERE id=?', (uid,)).fetchone()[0] == 1
    monkeypatch.setattr(credits, 'adjust', original)
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: post(client, '/training/checkin', a), range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert sum(not r.json()['already_checked'] for r in responses) == 1
    assert client.get('/api/profile', headers=a).json()['remaining'] == 2


def test_image_requires_auth_and_migration_keeps_admin_edits(client):
    from app.db import initialize, connect
    a = login(client, 'alice')
    s = start(client, a)
    url = s['cards'][0]['images'][0]
    assert client.get(url).status_code == 401
    assert client.get(url, headers=a).headers['content-type'] == 'image/jpeg'
    with connect() as db:
        db.execute("UPDATE training_questions SET answer='管理员校订' WHERE id=?", (s['cards'][0]['question_id'],))
    initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_questions WHERE collection_id IN (SELECT id FROM training_collections WHERE section_id="interview")').fetchone()[0] == 180
        assert db.execute('SELECT answer FROM training_questions WHERE id=?', (s['cards'][0]['question_id'],)).fetchone()[0] == '管理员校订'


def test_sequential_tail_wraps_next_round_and_filters_keep_separate_progress(client):
    a=login(client,'alice')
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE training_questions SET active=0 WHERE collection_id='data_structures' AND position>7")
    first=start(client,a);finish(client,a,first)
    tail=start(client,a)
    assert tail['total']==2
    finish(client,a,tail)
    wrapped=start(client,a)
    assert wrapped['cards'][0]['question_id']==first['cards'][0]['question_id']
    post(client,f"/training/sessions/{wrapped['id']}/end",a)
    question=first['cards'][0]['question_id']
    client.put(f'/api/training/questions/{question}/favorite',headers=a,json={'favorite':True})
    favorite=start(client,a,source='favorites')
    assert favorite['total']==1 and favorite['cards'][0]['question_id']==question


def test_training_calendar_is_server_shanghai_midnight(monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime,timezone
    from app.services import training
    timestamp=datetime(2026,11,14,16,1,tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(training,'time',SimpleNamespace(time=lambda:timestamp))
    assert training.today()==date(2026,11,15)


def test_account_deletion_cleans_private_training_and_anonymizes_public(client):
    a,m=login(client,'alice'),login(client,'manager')
    private=create(client,a,'私人内容')
    public=create(client,a,'贡献内容')
    pending=post(client,f"/training/questions/{public['id']}/submit",a,{'version':1}).json()
    post(client,f"/admin/training/questions/{public['id']}/review",m,{'version':pending['version'],'approve':True})
    finish(client,a,start(client,a))
    post(client,'/training/checkin',a)
    uid=client.get('/api/me',headers=a).json()['id']
    assert client.delete(f'/api/admin/users/{uid}',headers=m).status_code==204
    from app.db import connect
    with connect() as db:
        for table in ('training_sessions','training_daily_questions','training_checkins','training_favorites','training_sequential_progress','training_daily_activity'):
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?',(uid,)).fetchone()[0]==0
        row=db.execute('SELECT * FROM training_questions WHERE id=?',(private['id'],)).fetchone()
        assert row['deleted'] and row['question']=='' and row['owner_user_id'] is None
        row=db.execute('SELECT * FROM training_questions WHERE id=?',(public['id'],)).fetchone()
        assert row['visibility']=='public' and row['owner_user_id'] is None


def test_version15_upgrade_seeds_training_without_losing_public_samples(client):
    from app.db import initialize,connect,SCHEMA_VERSION
    with connect() as db:
        db.execute('DELETE FROM training_questions')
        db.execute('PRAGMA user_version=15')
        columns={row['name'] for row in db.execute('PRAGMA table_info(problems)')}
        assert 'samples' in columns
    initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_questions WHERE collection_id IN (SELECT id FROM training_collections WHERE section_id="interview")').fetchone()[0]==180
        assert db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION


def test_answer_repair_preserves_manual_edits_and_updates_old_session_snapshots(client):
    import hashlib, json
    from app.db import connect
    from app.services import training_schema
    old = '首段被错误\n\n断行。'
    good = '首段被错误断行。'
    items = [dict(source_key='computer_networks-17', answer=good),
             dict(source_key='computer_networks-18', answer='新版答案')]
    hashes = {item['source_key']: hashlib.sha256(old.encode()).hexdigest() for item in items}
    a = login(client, 'alice')
    s = start(client, a, collection_id='computer_networks')
    with connect() as db:
        rows = {r['source_key']:r['id'] for r in db.execute('SELECT id,source_key FROM training_questions')}
        db.execute('UPDATE training_questions SET answer=? WHERE id=?',(old, rows['computer_networks-17']))
        db.execute('UPDATE training_questions SET answer=? WHERE id=?',('管理员已修订答案', rows['computer_networks-18']))
        card_id = db.execute('SELECT id FROM training_session_cards WHERE session_id=? ORDER BY position LIMIT 1',(s['id'],)).fetchone()[0]
        snapshot = {'question':'原题', 'answer':old, 'images':[], 'source_info':{}}
        db.execute('UPDATE training_session_cards SET question_id=?,snapshot=? WHERE id=?',
                   (rows['computer_networks-17'],json.dumps(snapshot,ensure_ascii=False),card_id))
        training_schema.repair_answer_format(db,items=items,previous_hashes=hashes)
        assert db.execute('SELECT answer FROM training_questions WHERE id=?',(rows['computer_networks-17'],)).fetchone()[0]==good
        assert db.execute('SELECT answer FROM training_questions WHERE id=?',(rows['computer_networks-18'],)).fetchone()[0]=='管理员已修订答案'
        repaired=json.loads(db.execute('SELECT snapshot FROM training_session_cards WHERE id=?',(card_id,)).fetchone()[0])
        assert repaired==snapshot|{'answer':good}
        version=db.execute('SELECT version FROM training_questions WHERE id=?',(rows['computer_networks-17'],)).fetchone()[0]
        training_schema.repair_answer_format(db,items=items,previous_hashes=hashes)
        assert db.execute('SELECT version FROM training_questions WHERE id=?',(rows['computer_networks-17'],)).fetchone()[0]==version
