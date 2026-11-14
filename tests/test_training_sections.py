"""Training chapters isolate pools while keeping existing personal progress."""
import json
from pathlib import Path
from test_system import client, login
from test_training import post


def test_chapters_and_default_interview_pool(client):
    auth = login(client, 'alice')
    home = client.get('/api/training/home', headers=auth).json()
    assert [s['id'] for s in home['sections']] == ['interview', 'written_c', 'written_ai']
    result = post(client, '/training/sessions', auth, {'question_count': 'all'}).json()
    assert result['section_id'] == 'interview'
    assert result['total'] == 180
    assert all(c['section_id'] == 'interview' for c in result['cards'])


def test_ai_scope_private_questions_and_empty_c(client):
    a, b = login(client, 'alice'), login(client, 'bob')
    own = post(client, '/training/questions', a, {'collection_id': 'ai_ml', 'question': '私人的机器学习题目', 'answer': '参考答案'}).json()
    other = post(client, '/training/questions', b, {'collection_id': 'ai_ml', 'question': '其他人的题', 'answer': ''}).json()
    result = post(client, '/training/sessions', a, {'section_id': 'written_ai', 'question_count': 'all'})
    assert result.status_code == 201
    data = result.json()
    assert data['total'] > 150
    assert {c['section_id'] for c in data['cards']} == {'written_ai'}
    ids = {c['question_id'] for c in data['cards']}
    assert own['id'] in ids and other['id'] not in ids
    post(client, f"/training/sessions/{data['id']}/end", a)
    software = post(client, '/training/sessions', a, {'section_id': 'written_c', 'question_count': 'all'}).json()
    assert software['total'] >= 100
    post(client, f"/training/sessions/{software['id']}/end", a)
    assert post(client, '/training/sessions', a, {'section_id': 'written_ai', 'collection_id': 'oral'}).status_code == 422
    assert post(client, '/training/sessions', a, {'section_id': 'missing'}).status_code == 422
    listed = client.get('/api/training/questions?section_id=written_ai', headers=a).json()
    assert listed['total'] == data['total']
    assert all(q['section_id'] == 'written_ai' for q in listed['items'])
    software = client.get('/api/training/questions?section_id=written_c', headers=a).json()
    assert software['total'] >= 100
    assert all(item['section_id'] == 'written_c' for item in software['items'])


def test_migration_is_idempotent_and_preserves_edits_and_progress(client):
    from app.db import connect, initialize
    a = login(client, 'alice')
    session = post(client, '/training/sessions', a, {'mode': 'sequential', 'question_count': 1}).json()
    card = session['cards'][0]
    post(client, f"/training/sessions/{session['id']}/cards/{card['id']}/complete", a, {'rating': 'again'})
    client.put(f"/api/training/questions/{card['question_id']}/favorite", headers=a, json={'favorite': True})
    with connect() as db:
        qid = db.execute("SELECT id FROM training_questions WHERE collection_id='ai_ml' LIMIT 1").fetchone()[0]
        db.execute("UPDATE training_questions SET answer='管理员校订答案' WHERE id=?", (qid,))
        before = [tuple(r) for r in db.execute('SELECT * FROM training_sequential_progress')]
        count = db.execute('SELECT COUNT(*) FROM training_questions').fetchone()[0]
        db.execute('PRAGMA user_version=19')
    initialize(); initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_questions').fetchone()[0] == count
        assert db.execute('SELECT answer FROM training_questions WHERE id=?', (qid,)).fetchone()[0] == '管理员校订答案'
        assert [tuple(r) for r in db.execute('SELECT * FROM training_sequential_progress')] == before
        assert db.execute('SELECT COUNT(*) FROM training_favorites').fetchone()[0] == 1
        assert db.execute('SELECT status FROM training_mastery').fetchone()[0] == 'again'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_curated_ai_catalog_has_traceable_sources_and_supplements():
    bank = json.loads((Path(__file__).parents[1] / 'app/assets/training/written-ai.json').read_text())
    from collections import Counter
    assert Counter(x['collection_id'] for x in bank) == {'ai_ml': 44, 'ai_dl': 69, 'ai_llm': 45, 'ai_agent_rag': 44}
    assert sum(x['source']['kind']=='supplement' for x in bank)==25
    assert len({x['source_key'] for x in bank}) == len(bank)
    assert {x['collection_id'] for x in bank} == {'ai_ml', 'ai_dl', 'ai_llm', 'ai_agent_rag'}
    for item in bank:
        assert len(item['question']) > 6 and len(item['answer']) > 25
        assert item['source']['kind'] in ('curated', 'supplement')
        assert item['source']['references']
        if item['source']['kind'] == 'curated':
            assert item['source']['page_start'] >= 1 and item['source']['file'].endswith('.pdf')
    assert any(x['source']['kind'] == 'supplement' and x['collection_id'] == 'ai_ml' for x in bank)


def test_real_version19_upgrade_preserves_legacy_session_and_cursor(client):
    from app.db import connect, initialize
    a = login(client, 'alice')
    old = post(client, '/training/sessions', a, {'collection_id': 'data_structures', 'mode': 'sequential', 'question_count': 2}).json()
    card = old['cards'][0]
    post(client, f"/training/sessions/{old['id']}/cards/{card['id']}/complete", a, {'rating': 'again'})
    with connect() as db:
        db.execute("DELETE FROM training_questions WHERE collection_id IN (SELECT id FROM training_collections WHERE section_id!='interview')")
        db.execute("DELETE FROM training_collections WHERE section_id!='interview'")
        for table in ('training_sessions','training_collections'):
            db.execute(f'ALTER TABLE {table} DROP COLUMN section_id')
        for row in db.execute('SELECT id,snapshot FROM training_session_cards').fetchall():
            snap=json.loads(row['snapshot']);snap.pop('section_id',None)
            db.execute('UPDATE training_session_cards SET snapshot=? WHERE id=?',(json.dumps(snap),row['id']))
        expected=[tuple(r) for r in db.execute('SELECT * FROM training_sequential_progress')]
        db.execute('PRAGMA user_version=19')
    initialize()
    restored=client.get(f"/api/training/sessions/{old['id']}",headers=a).json()
    assert restored['section_id']=='interview' and restored['completed']==1
    assert restored['cards'][0]['question_id']==card['question_id']
    with connect() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM training_sequential_progress')]==expected
        assert db.execute("SELECT COUNT(*) FROM training_questions WHERE collection_id='data_structures'").fetchone()[0]==33


def test_sequential_cursors_and_favorites_are_section_scoped(client):
    a=login(client,'alice')
    one=post(client,'/training/sessions',a,{'mode':'sequential','question_count':1}).json()
    c=one['cards'][0]
    post(client,f"/training/sessions/{one['id']}/cards/{c['id']}/complete",a,{'rating':'known'})
    ai=post(client,'/training/sessions',a,{'section_id':'written_ai','mode':'sequential','question_count':1}).json()
    assert ai['cards'][0]['collection_id']=='ai_ml'
    c=ai['cards'][0]
    post(client,f"/training/sessions/{ai['id']}/cards/{c['id']}/complete",a,{'rating':'again'})
    client.put(f"/api/training/questions/{c['question_id']}/favorite",headers=a,json={'favorite':True})
    assert client.get('/api/training/questions?favorites=true',headers=a).json()['total']==0
    assert client.get('/api/training/questions?favorites=true&section_id=written_ai',headers=a).json()['total']==1
    assert client.get('/api/training/home?section_id=written_ai',headers=a).json()['mastery']=={'again':1,'known':0}
    assert client.get('/api/training/home',headers=a).json()['mastery']=={'again':0,'known':1}
    from app.db import connect
    with connect() as db:
        keys={r[0] for r in db.execute('SELECT filter_key FROM training_sequential_progress')}
        assert ':all' in keys and 'written_ai::all' in keys
    manager=login(client,'manager')
    listed=client.get('/api/admin/training/questions?status=public&section_id=written_ai',headers=manager).json()
    assert listed['total']==259 and all(i['section_id']=='written_ai' for i in listed['items'])
    assert client.get('/api/training/home?section_id=invalid',headers=a).status_code==422
