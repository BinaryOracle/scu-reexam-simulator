"""Retrying a committed interview start must not charge or allocate again."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from test_system import client, login
from test_presentations import deck_bytes


def start(client, headers, key, content):
    return client.post('/api/interviews/start', headers={**headers, 'Idempotency-Key': key},
                       files={'file': ('intro.pdf', content, 'application/pdf')})


def test_retry_recovers_committed_start_even_after_last_credit_is_spent(client, monkeypatch):
    from app.db import connect
    from app.services import presentations
    headers, key, content = login(client, 'alice'), str(uuid4()), deck_bytes()
    first = start(client, headers, key, content)
    assert first.status_code == 201
    assert client.get('/api/profile', headers=headers).json()['remaining'] == 0
    # A retry should read the committed receipt without converting the deck again.
    monkeypatch.setattr(presentations, 'prepare', lambda *args: (_ for _ in ()).throw(AssertionError('reconverted retry')))
    repeated = start(client, headers, key, content)
    assert repeated.status_code == 201
    assert repeated.json()['id'] == first.json()['id']
    assert repeated.json()['deadline_at'] == first.json()['deadline_at']
    assert len(client.get('/api/interviews', headers=headers).json()) == 1
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='interview'").fetchone()[0] == 1


def test_concurrent_start_retries_share_one_interview_and_one_conversion_directory(client):
    from app.config import load_config
    from pathlib import Path
    headers, key, content = login(client, 'alice'), str(uuid4()), deck_bytes()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: start(client, headers, key, content), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert len({response.json()['id'] for response in responses}) == 1
    assert len(list(Path(load_config()['presentation']['directory']).iterdir())) == 1
    assert client.get('/api/profile', headers=headers).json()['remaining'] == 0


def test_start_keys_are_private_and_changed_files_cannot_reuse_a_committed_key(client):
    alice, bob = login(client, 'alice'), login(client, 'bob')
    key, content = str(uuid4()), deck_bytes()
    first = start(client, alice, key, content)
    other = start(client, bob, key, content)
    assert first.status_code == other.status_code == 201
    assert first.json()['id'] != other.json()['id']
    conflict = start(client, alice, key, content + b'\n')
    assert conflict.status_code == 409
    assert len(client.get('/api/interviews', headers=alice).json()) == 1


def test_failed_conversion_does_not_consume_the_start_key(client):
    headers, key = login(client, 'alice'), str(uuid4())
    assert start(client, headers, key, b'invalid').status_code == 400
    assert start(client, headers, key, deck_bytes()).status_code == 201


def test_start_rejects_invalid_request_keys_before_allocating(client):
    headers = login(client, 'alice')
    assert start(client, headers, 'not-a-uuid', deck_bytes()).status_code == 422
    assert client.get('/api/interviews', headers=headers).json() == []
