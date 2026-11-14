"""Software-engineering bank import preserves personal and editorial history."""
import json
from pathlib import Path
from test_system import client, login
from test_training import post

ASSET = Path(__file__).parents[1] / 'app/assets/training/written-software.json'


def test_software_section_training_and_admin_editing(client):
    a, b, manager = [login(client, name) for name in ('alice', 'bob', 'manager')]
    home = client.get('/api/training/home?section_id=written_c', headers=a).json()
    section = next(s for s in home['sections'] if s['id'] == 'written_c')
    assert section['name'] == '笔试-软件工程篇'
    assert section['count'] >= 100
    own = post(client, '/training/questions', a, {'collection_id': 'se_testing', 'question': '自己的测试复习题', 'answer': '自己的答案'}).json()
    other = post(client, '/training/questions', b, {'collection_id': 'se_testing', 'question': '别人的私人题'}).json()
    round = post(client, '/training/sessions', a, {'section_id': 'written_c', 'mode': 'sequential', 'question_count': 'all'})
    assert round.status_code == 201, round.text
    data = round.json()
    assert {c['section_id'] for c in data['cards']} == {'written_c'}
    ids = {c['question_id'] for c in data['cards']}
    assert own['id'] in ids and other['id'] not in ids
    card = data['cards'][0]
    completed = post(client, f"/training/sessions/{data['id']}/cards/{card['id']}/complete", a, {'rating': 'again'})
    assert completed.status_code == 200 and completed.json()['completed'] == 1
    listed = client.get('/api/admin/training/questions?section_id=written_c&collection_id=se_testing', headers=manager).json()
    item = listed['items'][0]
    edited = client.patch(f"/api/admin/training/questions/{item['id']}", headers=manager,
        json={'collection_id': item['collection_id'], 'question': item['question'], 'answer': '管理员修改答案', 'version': item['version'], 'active': True})
    assert edited.status_code == 200 and edited.json()['answer'] == '管理员修改答案'


def test_version21_upgrade_preserves_legacy_c_records_and_no_reseed(client):
    from app.db import connect, initialize
    a, manager = login(client, 'alice'), login(client, 'manager')
    old = post(client, '/training/questions', a, {'collection_id': 'c_programming', 'question': '旧C语言私人题', 'answer': '历史答案'}).json()
    official = post(client, '/admin/training/questions', manager, {'collection_id': 'c_programming', 'question': '旧公开题'}).json()
    client.put(f"/api/training/questions/{old['id']}/favorite", headers=a, json={'favorite': True})
    s = post(client, '/training/sessions', a, {'section_id': 'written_c', 'collection_id': 'c_programming', 'source': 'favorites', 'mode': 'sequential', 'question_count': 1}).json()
    post(client, f"/training/sessions/{s['id']}/cards/{s['cards'][0]['id']}/complete", a, {'rating': 'again'})
    tables = ('training_sessions', 'training_session_cards', 'training_mastery', 'training_sequential_progress', 'training_favorites')
    with connect() as db:
        db.execute("DELETE FROM training_questions WHERE source_key LIKE 'written-software-v1:%'")
        db.execute("UPDATE training_collections SET name='C 程序设计' WHERE id='c_programming'")
        before = {t: [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}
        db.execute('PRAGMA user_version=21')
    initialize()
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 22
        assert db.execute("SELECT name FROM training_collections WHERE id='c_programming'").fetchone()[0] == '综合与历年题'
        assert db.execute('SELECT answer FROM training_questions WHERE id=?', (old['id'],)).fetchone()[0] == '历史答案'
        assert db.execute('SELECT question FROM training_questions WHERE id=?', (official['id'],)).fetchone()[0] == '旧公开题'
        for t, expected in before.items():
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {t} ORDER BY rowid')] == expected
        seeded = db.execute("SELECT id FROM training_questions WHERE source_key LIKE 'written-software-v1:%' LIMIT 1").fetchone()[0]
        count = db.execute('SELECT COUNT(*) FROM training_questions').fetchone()[0]
        db.execute("UPDATE training_questions SET answer='保留的管理员编辑',deleted=1 WHERE id=?", (seeded,))
    initialize(); initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_questions').fetchone()[0] == count
        assert tuple(db.execute('SELECT answer,deleted FROM training_questions WHERE id=?', (seeded,)).fetchone()) == ('保留的管理员编辑', 1)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_software_assets_have_sources_complete_conditions_and_editorial_notes():
    assert ASSET.is_file()
    bank = json.loads(ASSET.read_text())
    assert len(bank) >= 100
    assert len({x['source_key'] for x in bank}) == len(bank)
    assert len({x['question'] for x in bank}) == len(bank)
    for item in bank:
        assert len(item['answer']) > 35
        assert '\u200b' not in item['question'] + item['answer']
        source = item['source']
        assert source['kind'] == 'curated' and source['editorial_note']
        assert source['references'] and source['origins']
        for origin in source['origins']:
            limit = 28 if '个人复习笔记' in origin['file'] else 9
            assert 1 <= origin['page_start'] <= origin['page_end'] <= limit
    assert {x['collection_id'] for x in bank} == {'se_fundamentals', 'se_requirements', 'se_design', 'se_testing', 'se_management', 'c_programming'}
    embedded = [x for x in bank if x['source'].get('embedded_number')]
    assert {x['source']['embedded_number'] for x in embedded} == set(range(1, 8))
    assert any(x['source'].get('reconstructed') for x in bank)
    assert any('E−N+2P' in x['answer'] for x in bank)
    assert any('2/81' in x['answer'] for x in bank)
