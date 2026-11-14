"""English translation and oral question banks are selected and administered safely."""
from test_presentations import prepare_intro
from test_system import client, login


def live_interview(client):
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    return headers, iid


def test_translation_and_oral_questions_are_drawn_once_and_persisted(client, monkeypatch):
    from app.services import question_bank
    monkeypatch.setattr(question_bank.random, 'choice', lambda rows: rows[0])
    headers, iid = live_interview(client)
    for stage, expected in [(3, 'translation'), (4, 'oral')]:
        response = client.post(f'/api/interviews/{iid}/draw-question/{stage}', headers=headers)
        assert response.status_code == 200
        answer = response.json()['answers'][stage - 1]
        assert answer['question_choices'] == 1
        assert answer['question']
        assert client.post(f'/api/interviews/{iid}/draw-question/{stage}', headers=headers).json()['answers'][stage - 1]['question'] == answer['question']
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][2]['question']


def test_question_bank_crud_is_admin_only(client):
    admin, user = login(client, 'manager'), login(client, 'alice')
    payload = {'category': 'oral', 'subject': '', 'content': 'What is a database?', 'active': True}
    assert client.get('/api/admin/question-bank', headers=user).status_code == 403
    created = client.post('/api/admin/question-bank', headers=admin, json=payload)
    assert created.status_code == 201
    qid = created.json()['id']
    assert client.get(f'/api/admin/question-bank/{qid}', headers=admin).json()['content'] == payload['content']
    assert client.patch(f'/api/admin/question-bank/{qid}', headers=user, json=payload).status_code == 403
    assert client.delete(f'/api/admin/question-bank/{qid}', headers=user).status_code == 403
    assert any(item['id'] == qid for item in client.get('/api/admin/question-bank?category=oral', headers=admin).json())
    edited = client.patch(f'/api/admin/question-bank/{qid}', headers=admin,
                          json={**payload, 'content': 'What is a relational database?', 'active': False})
    assert edited.status_code == 200 and edited.json()['active'] == 0
    assert client.delete(f'/api/admin/question-bank/{qid}', headers=admin).status_code == 204
    assert client.delete(f'/api/admin/question-bank/{qid}', headers=admin).status_code == 404


def test_empty_bank_stays_empty_after_restart_and_cannot_be_drawn(client):
    from app.db import connect, initialize
    headers, iid = live_interview(client)
    with connect() as db:
        db.execute('DELETE FROM question_bank')
    initialize()
    assert client.get('/api/admin/question-bank', headers=login(client, 'manager')).json() == []
    assert client.post(f'/api/interviews/{iid}/draw-question/3', headers=headers).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][2]['question_choices'] == 0


def test_question_bank_rejects_invalid_category_subject_and_language(client):
    headers = login(client, 'manager')
    for payload in [
        {'category': 'oral', 'content': '   '},
        {'category': 'oral', 'content': '请介绍你自己'},
        {'category': 'translation', 'content': '123'},
        {'category': 'professional', 'subject': 'unknown', 'content': '题目'},
        {'category': 'oral', 'subject': 'data_structures', 'content': 'Introduce yourself.'},
        {'category': 'other', 'content': 'What is AI?'},
    ]:
        assert client.post('/api/admin/question-bank', headers=headers, json=payload).status_code == 422


def test_draws_require_owner_started_intro_and_are_frozen_when_finished(client):
    from app.db import connect
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    path = f'/api/interviews/{iid}/draw-question/4'
    assert client.post(path, headers=headers).status_code == 409
    prepare_intro(client, iid, headers)
    assert client.post(path, headers=login(client, 'bob')).status_code == 404
    assert client.put(f'/api/interviews/{iid}/answers/4', headers=headers, json={'transcript': 'Before drawing'}).status_code == 409
    drawn = client.post(path, headers=headers).json()['answers'][3]['question']
    with connect() as db:
        db.execute("DELETE FROM question_bank WHERE category='oral'")
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][3]['question'] == drawn
    assert client.post(f'/api/interviews/{iid}/stop', headers=headers).status_code == 200
    assert client.post(path, headers=headers).status_code == 409


def test_legacy_interviews_keep_their_questions(client):
    from app.db import connect
    headers, iid = live_interview(client)
    with connect() as db:
        db.execute('UPDATE interviews SET workflow_version=4 WHERE id=?', (iid,))
        db.execute("UPDATE answers SET question='Historical prompt' WHERE interview_id=? AND stage=4", (iid,))
    assert client.post(f'/api/interviews/{iid}/draw-question/4', headers=headers).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][3]['question'] == 'Historical prompt'


def test_seeded_english_bank_contains_translation_and_oral_records():
    import json
    from pathlib import Path
    catalog = json.loads(Path('app/assets/question-bank/catalog.json').read_text())
    translation = [item for item in catalog if item['category'] == 'translation']
    oral = [item for item in catalog if item['category'] == 'oral']
    assert len(translation) == 31
    assert len(oral) == 53
    assert all(not any('\u4e00' <= char <= '\u9fff' for char in item['content'])
               for item in catalog if item['category'] in ('translation', 'oral'))
