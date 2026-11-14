"""Subject-card question selection stays owned, persisted, and limited to one change."""
from test_presentations import prepare_intro
from test_system import client, login


def started_with_intro(client):
    alice = login(client, 'alice')
    item = client.post('/api/interviews', headers=alice).json()
    prepare_intro(client, item['id'], alice)
    return alice, item['id']


def test_subject_card_draws_and_persists_one_question(client, monkeypatch):
    from app.services import question_bank
    monkeypatch.setattr(question_bank, 'choose_question', lambda *args: {'id': 1, 'content': 'Explain a linked list.'})
    alice, iid = started_with_intro(client)
    response = client.post(f'/api/interviews/{iid}/professional-question', headers=alice,
                           json={'subject': 'data_structures'})
    assert response.status_code == 200
    answer = response.json()['answers'][1]
    assert answer['subject'] == 'data_structures'
    assert answer['question'] == 'Explain a linked list.'
    assert answer['question_choices'] == 1


def test_question_change_must_use_a_different_subject_and_is_available_once(client, monkeypatch):
    from app.services import question_bank
    monkeypatch.setattr(question_bank, 'choose_question', lambda db, category, subject='': {'id': 1, 'content': f'Question from {subject}'})
    alice, iid = started_with_intro(client)
    path = f'/api/interviews/{iid}/professional-question'
    assert client.post(path, headers=alice, json={'subject': 'data_structures'}).status_code == 200
    assert client.post(path, headers=alice, json={'subject': 'data_structures'}).status_code == 409
    changed = client.post(path, headers=alice, json={'subject': 'operating_systems'})
    assert changed.status_code == 200
    answer = changed.json()['answers'][1]
    assert answer['subject'] == 'operating_systems'
    assert answer['question_choices'] == 2
    assert client.post(path, headers=alice, json={'subject': 'computer_networks'}).status_code == 409


def test_question_change_clears_prior_transcript_and_remains_private(client, monkeypatch):
    from app.services import question_bank
    monkeypatch.setattr(question_bank, 'choose_question', lambda *args: {'id': 1, 'content': 'A persisted question'})
    alice, iid = started_with_intro(client)
    bob = login(client, 'bob')
    path = f'/api/interviews/{iid}/professional-question'
    assert client.post(path, headers=alice, json={'subject': 'data_structures'}).status_code == 200
    assert client.put(f'/api/interviews/{iid}/answers/2', headers=alice,
                      json={'transcript': 'I can answer this'}).status_code == 200
    changed = client.post(path, headers=alice, json={'subject': 'computer_networks'})
    assert changed.status_code == 200
    assert changed.json()['answers'][1]['transcript'] == ''
    assert client.post(path, headers=bob, json={'subject': 'computer_networks'}).status_code == 404


def test_question_bank_files_have_subject_lists_and_combined_catalog():
    import json
    from pathlib import Path
    root = Path('app/assets/question-bank')
    names = ['data-structures', 'operating-systems', 'computer-networks']
    counts = [33, 29, 34]
    combined = json.loads((root / 'questions.json').read_text())
    for name, count in zip(names, counts, strict=True):
        rows = json.loads((root / f'{name}.json').read_text())
        assert len(rows) == count
        assert rows == combined[name.replace('-', '_')]
        assert all(row['id'] and row['question'].strip() for row in rows)
