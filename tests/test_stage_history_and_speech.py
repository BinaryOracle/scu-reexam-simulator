"""Question replacement history and private stage introduction speech."""
import json
import pytest
from test_system import client, login
from test_presentations import prepare_intro, upload


def test_replaced_professional_question_retains_both_questions_in_draw_order(client, monkeypatch):
    from app.services import question_bank
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    monkeypatch.setattr(question_bank, 'choose_question', lambda db, category, subject: {'content': f'Question for {subject}'})
    first = client.post(f'/api/interviews/{iid}/professional-question', headers=headers, json={'subject': 'data_structures'})
    expected = [{'question': 'Question for data_structures', 'subject': 'data_structures'}]
    assert first.json()['answers'][1]['question_history'] == expected
    replaced = client.post(f'/api/interviews/{iid}/professional-question', headers=headers, json={'subject': 'operating_systems'})
    expected.append({'question': 'Question for operating_systems', 'subject': 'operating_systems'})
    assert replaced.json()['answers'][1]['question_history'] == expected
    assert client.post(f'/api/interviews/{iid}/professional-question', headers=headers, json={'subject': 'computer_networks'}).status_code == 409
    client.post(f'/api/interviews/{iid}/stop', headers=headers)
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][1]['question_history'] == expected


@pytest.mark.parametrize('choices', [0, 1, 2])
def test_v10_history_migration_preserves_only_known_saved_questions(client, choices):
    from app.db import connect, initialize, SCHEMA_VERSION
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    with connect() as db:
        db.execute('ALTER TABLE answers DROP COLUMN question_history')
        db.execute("UPDATE answers SET question='Only surviving question',subject='operating_systems',question_choices=? WHERE interview_id=? AND stage=2", (choices, iid))
        db.execute('PRAGMA user_version=10')
    initialize()
    expected = [{'question': 'Only surviving question', 'subject': 'operating_systems'}] if choices else []
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][1]['question_history'] == expected
    initialize()
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION > 10
        assert json.loads(db.execute('SELECT question_history FROM answers WHERE interview_id=? AND stage=2', (iid,)).fetchone()[0]) == expected


@pytest.mark.parametrize('stage,text', [
    (1, '当前进入自我介绍环节。'), (2, '当前进入专业课问答环节。'),
    (3, '当前进入英文翻译环节。'), (4, '当前进入英文问答环节。'),
    (5, '当前进入专家问答环节。专家给出的问题为。'),
])
def test_stage_speech_uses_fixed_text_without_question_or_feedback_calls(client, monkeypatch, stage, text):
    from app.services import ai
    from app.db import connect
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    if stage == 5:
        with connect() as db:
            db.execute('INSERT INTO answers(interview_id,stage,question) VALUES (?,5,?)', (iid, 'Saved expert question'))
    spoken = []
    monkeypatch.setattr(ai, 'synthesize', lambda text: spoken.append(text) or (b'RIFFstage', 'audio/wav'))
    monkeypatch.setattr(ai, 'chat', lambda *args, **kwargs: pytest.fail('Stage introductions cannot generate questions or feedback'))
    response = client.post(f'/api/interviews/{iid}/stage-speech/{stage}', headers=headers)
    assert response.status_code == 200 and response.content == b'RIFFstage'
    assert response.headers['cache-control'] == 'private, no-store'
    assert spoken == [text]
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['feedback'] is None


def test_stage_speech_rejects_other_users_and_unavailable_stages_before_tts(client, monkeypatch):
    from app.services import ai
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    monkeypatch.setattr(ai, 'synthesize', lambda text: pytest.fail('Rejected request cannot call TTS'))
    url = f'/api/interviews/{iid}/stage-speech/1'
    assert client.post(url).status_code == 401
    assert client.post(url, headers=login(client, 'bob')).status_code == 404
    assert client.post(url, headers=login(client, 'manager')).status_code == 404
    assert client.post(url, headers=headers).status_code == 409
    assert upload(client, iid, headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/stage-speech/2', headers=headers).status_code == 409
    assert client.post(f'/api/interviews/{iid}/answers/1/audio', headers=headers,
                       files={'file': ('answer.webm', b'audio', 'audio/webm')}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/stage-speech/5', headers=headers).status_code == 409
    assert client.post(f'/api/interviews/{iid}/stage-speech/6', headers=headers).status_code == 404


def test_stage_speech_rechecks_owner_record_after_synthesis(client, monkeypatch):
    from app.services import ai
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    def synthesize(text):
        assert client.delete(f'/api/interviews/{iid}', headers=headers).status_code == 204
        return b'RIFFstage', 'audio/wav'
    monkeypatch.setattr(ai, 'synthesize', synthesize)
    assert client.post(f'/api/interviews/{iid}/stage-speech/1', headers=headers).status_code == 404
