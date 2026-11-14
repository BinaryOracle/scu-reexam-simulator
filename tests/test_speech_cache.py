"""Persistent speech reuse, private lifetimes, and concurrent misses."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
import pytest
from fastapi import HTTPException
from test_system import client, login
from test_presentations import prepare_intro


def test_fixed_stage_audio_is_reused_across_interviews_and_service_reloads(client, monkeypatch):
    from app.services import ai, speech
    import importlib
    headers = login(client, 'alice')
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE users SET interview_credits=2 WHERE username='alice'")
    spoken = []
    monkeypatch.setattr(ai, 'synthesize', lambda text: spoken.append(text) or (b'RIFFstage', 'audio/wav'))
    for _ in range(2):
        iid = client.post('/api/interviews', headers=headers).json()['id']
        prepare_intro(client, iid, headers)
        assert client.post(f'/api/interviews/{iid}/stage-speech/1', headers=headers).content == b'RIFFstage'
        importlib.reload(speech)
    assert spoken == ['当前进入自我介绍环节。']


def test_concurrent_cache_misses_only_synthesize_once(client, monkeypatch):
    from app.services import ai, speech
    entered, release = Event(), Event()
    spoken = []
    def synthesize(text):
        spoken.append(text)
        entered.set()
        assert release.wait(5)
        return b'RIFFonce', 'audio/wav'
    monkeypatch.setattr(ai, 'synthesize', synthesize)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(speech.cached, '同一提示语') for _ in range(3)]
        assert entered.wait(5)
        # A slow synthesis must not block unrelated database writes.
        from app.db import connect
        with connect() as db:
            db.execute("UPDATE users SET interview_credits=8 WHERE username='alice'")
        release.set()
        assert [f.result() for f in futures] == [(b'RIFFonce', 'audio/wav')] * 3
    assert spoken == ['同一提示语']


def test_voice_change_invalidates_cache_and_disabled_tts_does_not_serve_cached_audio(client, monkeypatch):
    from app.services import ai, speech
    spoken = []
    monkeypatch.setattr(ai, 'synthesize', lambda text: spoken.append(text) or (b'RIFFvoice', 'audio/wav'))
    assert speech.cached('提示') == (b'RIFFvoice', 'audio/wav')
    import os
    path = Path(os.environ['SCU_CONFIG'])
    path.write_text(path.read_text().replace('voice = "longanhuan_v3.1"', 'voice = "another-voice"'))
    assert speech.cached('提示') == (b'RIFFvoice', 'audio/wav')
    assert len(spoken) == 2
    path.write_text(path.read_text().replace('enabled = true', 'enabled = false'))
    with pytest.raises(HTTPException) as failure:
        speech.cached('提示')
    assert failure.value.status_code == 503


def test_failed_synthesis_is_not_cached(client, monkeypatch):
    from app.services import ai, speech
    def fail(text):
        raise HTTPException(502, 'temporary failure')
    monkeypatch.setattr(ai, 'synthesize', fail)
    with pytest.raises(HTTPException):
        speech.cached('需要重试')
    monkeypatch.setattr(ai, 'synthesize', lambda text: (b'RIFFretry', 'audio/wav'))
    assert speech.cached('需要重试') == (b'RIFFretry', 'audio/wav')


def test_expert_cache_is_private_and_deleted_with_its_interview(client, monkeypatch):
    from app.services import ai
    from app.db import connect
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    with connect() as db:
        db.execute('INSERT INTO answers(interview_id,stage,question) VALUES (?,5,?)', (iid, '项目的取舍是什么？'))
    spoken = []
    monkeypatch.setattr(ai, 'synthesize', lambda text: spoken.append(text) or (b'RIFFexpert', 'audio/wav'))
    url = f'/api/interviews/{iid}/expert-speech'
    assert client.post(url, headers=headers).content == b'RIFFexpert'
    assert client.post(url, headers=headers).content == b'RIFFexpert'
    assert client.post(url, headers=login(client, 'bob')).status_code == 404
    assert len(spoken) == 1
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM speech_cache WHERE interview_id=?', (iid,)).fetchone()[0] == 1
    assert client.delete(f'/api/interviews/{iid}', headers=headers).status_code == 204
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM speech_cache WHERE interview_id=?', (iid,)).fetchone()[0] == 0


def test_deleted_interview_cannot_publish_late_speech_cache(client, monkeypatch):
    from app.services import ai
    from app.db import connect
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    with connect() as db:
        db.execute('INSERT INTO answers(interview_id,stage,question) VALUES (?,5,?)', (iid, '旧题目'))
    def synthesize(text):
        assert client.delete(f'/api/interviews/{iid}', headers=headers).status_code == 204
        return b'RIFFlate', 'audio/wav'
    monkeypatch.setattr(ai, 'synthesize', synthesize)
    assert client.post(f'/api/interviews/{iid}/expert-speech', headers=headers).status_code == 404
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM speech_cache').fetchone()[0] == 0
