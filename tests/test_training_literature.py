"""Literature translations remain a separate, editable written-AI collection."""
import json
from pathlib import Path
from test_system import client, login
from test_training import post

CID = 'ai_literature_translation'


def test_literature_collection_and_private_scope(client):
    a, b = login(client, 'alice'), login(client, 'bob')
    home = client.get('/api/training/home?section_id=written_ai', headers=a).json()
    collection = next((c for c in home['collections'] if c['id'] == CID), None)
    assert collection is not None
    assert collection['category'] == 'translation' and collection['section_id'] == 'written_ai'
    assert collection['count'] == 57
    assert post(client, '/training/questions', a, {'collection_id': CID, 'question': '只有中文的题干'}).status_code == 422
    own = post(client, '/training/questions', a, {'collection_id': CID, 'question': 'An agent retrieves external knowledge.', 'answer': '智能体检索外部知识。'}).json()
    post(client, '/training/questions', b, {'collection_id': CID, 'question': 'A private passage from another user.'})
    round = post(client, '/training/sessions', a, {'section_id': 'written_ai', 'collection_id': CID, 'question_count': 'all', 'mode': 'sequential'}).json()
    assert round['total'] == 58
    assert {c['collection_id'] for c in round['cards']} == {CID}
    assert own['id'] in {c['question_id'] for c in round['cards']}
    assert post(client, '/training/sessions', b, {'collection_id': CID}).status_code == 422
    first = round['cards'][0]
    done = post(client, f"/training/sessions/{round['id']}/cards/{first['id']}/complete", a, {'rating': 'again'}).json()
    assert done['completed'] == 1
    assert done['cards'][0]['mastery']['status'] == 'again'


def test_literature_admin_crud_and_category_metadata(client):
    admin = login(client, 'manager')
    config = client.get('/api/admin/training/settings', headers=admin).json()
    c = next((c for c in config['collections'] if c['id'] == CID), None)
    assert c and c['category'] == 'translation'
    created = post(client, '/admin/training/questions', admin, {'collection_id': CID, 'question': 'Attention captures dependencies between tokens.', 'answer': '注意力捕捉词元之间的依赖关系。'})
    assert created.status_code == 201
    q = created.json()
    edited = client.patch(f"/api/admin/training/questions/{q['id']}", headers=admin, json={'collection_id': CID, 'question': q['question'], 'answer': '校订后的参考译文。', 'version': q['version'], 'active': True})
    assert edited.status_code == 200 and edited.json()['answer'] == '校订后的参考译文。'
    listed = client.get(f'/api/admin/training/questions?section_id=written_ai&collection_id={CID}', headers=admin).json()
    assert listed['total'] == 58
    hidden = post(client, f"/admin/training/questions/{q['id']}/active", admin, {'active': False, 'version': edited.json()['version']})
    assert hidden.status_code == 200
    a = login(client, 'alice')
    assert client.get(f'/api/training/questions?section_id=written_ai&collection_id={CID}', headers=a).json()['total'] == 57


def test_version20_upgrade_adds_literature_without_replacing_existing_work(client):
    from app.db import connect, initialize
    a = login(client, 'alice')
    round = post(client, '/training/sessions', a, {'section_id': 'written_ai', 'collection_id': 'ai_ml', 'question_count': 2, 'mode': 'sequential'}).json()
    first = round['cards'][0]
    post(client, f"/training/sessions/{round['id']}/cards/{first['id']}/complete", a, {'rating': 'known'})
    with connect() as db:
        db.execute("DELETE FROM training_questions WHERE collection_id=?", (CID,))
        db.execute("DELETE FROM training_collections WHERE id=?", (CID,))
        db.execute("UPDATE training_questions SET answer='人工校订版本' WHERE id=?", (first['question_id'],))
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] for table in ('training_sessions', 'training_session_cards', 'training_mastery', 'training_sequential_progress')}
        db.execute('PRAGMA user_version=20')
    initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_questions WHERE collection_id=?', (CID,)).fetchone()[0] == 57
        assert db.execute('SELECT answer FROM training_questions WHERE id=?', (first['question_id'],)).fetchone()[0] == '人工校订版本'
        for table, rows in before.items():
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')] == rows
        item = db.execute('SELECT id FROM training_questions WHERE collection_id=? LIMIT 1', (CID,)).fetchone()[0]
        db.execute("UPDATE training_questions SET answer='管理员新译文',deleted=1 WHERE id=?", (item,))
    initialize()
    with connect() as db:
        assert tuple(db.execute('SELECT answer,deleted FROM training_questions WHERE id=?', (item,)).fetchone()) == ('管理员新译文', 1)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_literature_asset_passages_and_editorial_corrections():
    path = Path(__file__).parents[1] / 'app/assets/training/written-ai-literature.json'
    assert path.is_file()
    bank = json.loads(path.read_text())
    assert len(bank) == 57 and len({x['source_key'] for x in bank}) == 57
    assert len({x['source']['article_id'] for x in bank}) == 18
    for x in bank:
        assert x['collection_id'] == CID and 25 < len(x['question'].split()) < 420
        assert len(x['answer']) > 45 and '\u200b' not in x['question']
        assert not any('\u4e00' <= c <= '\u9fff' for c in x['question'])
        s = x['source']
        assert 1 <= s['page_start'] <= s['page_end'] <= 41
        assert s['kind'] == 'translation' and s['article'] and s['editorial_note']
        assert len(s['glossary']) >= 5 and all(len(pair) == 2 for pair in s['glossary'])
    gemini = next(x for x in bank if x['source']['article_id'] == 'gemini15')
    assert 'Gemini 1.5' in gemini['answer'] and 'Gemini 2.5' not in gemini['answer']
    assert all('AutoGen2' not in x['question'] for x in bank)
    assert all('because' not in x['answer'] for x in bank)
    assert any('更受偏好' in x['answer'] for x in bank if x['source']['article_id'] == 'instructgpt')
    assert any(x['source']['page_end'] == 41 for x in bank)


def test_literature_source_pages_exclude_next_page_translation():
    bank = json.loads((Path(__file__).parents[1] / 'app/assets/training/written-ai-literature.json').read_text())
    for number, pages in {19: (14, 14), 41: (30, 30), 52: (36, 36), 56: (39, 39)}.items():
        source = bank[number - 1]['source']
        assert (source['page_start'], source['page_end']) == pages
