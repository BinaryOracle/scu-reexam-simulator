"""Server-owned interview deadlines and explicit preparation/start separation."""
from test_system import client, login
from test_presentations import upload


def test_preparation_does_not_create_record_and_explicit_start_creates_complete_session(client):
    from test_presentations import deck_bytes
    alice, bob = login(client, 'alice'), login(client, 'bob')
    setup = client.get('/api/interview-setup', headers=alice)
    assert setup.status_code == 200
    assert setup.json()['duration_seconds'] == 600
    assert client.get('/api/interviews', headers=alice).json() == []
    started = client.post('/api/interviews/start', headers=alice,
        files={'file': ('我的复试.pdf', deck_bytes(), 'application/pdf')})
    assert started.status_code == 201
    item = started.json()
    assert item['status'] == 'active'
    assert item['presentation']['name'] == '我的复试.pdf'
    assert item['deadline_at'] - item['started_at'] == 600
    assert len(item['answers']) == 4
    assert len(client.get('/api/interviews', headers=alice).json()) == 1
    assert client.get(f"/api/interviews/{item['id']}", headers=bob).status_code == 404


def test_failed_start_does_not_leave_empty_interview_record(client):
    alice = login(client, 'alice')
    response = client.post('/api/interviews/start', headers=alice,
        files={'file': ('bad.pptx', b'invalid', 'application/octet-stream')})
    assert response.status_code == 400
    assert client.get('/api/interviews', headers=alice).json() == []
    assert client.post('/api/interviews/start', files={'file': ('bad.pptx', b'invalid')}).status_code == 401


def test_upload_waits_for_explicit_start_and_blocks_early_answers(client):
    headers = login(client, 'alice')
    item = client.post('/api/interviews', headers=headers).json()
    iid = item['id']
    assert item['workflow_version'] == 5
    assert item['status'] == 'preparing'
    assert item['started_at'] is None and item['deadline_at'] is None
    assert item['duration_seconds'] == 600
    assert client.post(f'/api/interviews/{iid}/start', headers=headers).status_code == 409
    uploaded = upload(client, iid, headers)
    assert uploaded.status_code == 200
    assert uploaded.json()['started_at'] is None
    assert client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=headers).status_code == 409
    assert client.put(f'/api/interviews/{iid}/answers/1', headers=headers,
                      json={'transcript': '提前回答'}).status_code == 409
    assert client.post(f'/api/interviews/{iid}/answers/1/audio', headers=headers,
                       files={'file': ('a.webm', b'audio')}).status_code == 409
    started = client.post(f'/api/interviews/{iid}/start', headers=headers)
    assert started.status_code == 200
    item = started.json()
    assert item['status'] == 'active'
    assert item['deadline_at'] - item['started_at'] == 600
    assert item['remaining_seconds'] == 600
    assert client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=headers).status_code == 200
    assert upload(client, iid, headers).status_code == 409


def test_start_is_owner_only_and_repeated_request_keeps_deadline(client):
    alice, bob = [login(client, name) for name in ['alice', 'bob']]
    manager = {'Authorization': 'Bearer ' + client.post('/api/login', json={'username': 'root', 'password': 'root'}).json()['token']}
    iid = client.post('/api/interviews', headers=alice).json()['id']
    assert upload(client, iid, alice).status_code == 200
    url = f'/api/interviews/{iid}/start'
    assert client.post(url).status_code == 401
    assert client.post(url, headers=bob).status_code == 404
    assert client.post(url, headers=manager).status_code == 404
    first = client.post(url, headers=alice)
    assert first.status_code == 200
    second = client.post(url, headers=alice)
    assert second.status_code == 200
    assert second.json()['started_at'] == first.json()['started_at']
    assert second.json()['deadline_at'] == first.json()['deadline_at']


def started_interview(client):
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    assert upload(client, iid, headers).status_code == 200
    item = client.post(f'/api/interviews/{iid}/start', headers=headers).json()
    return headers, item


def test_deadline_survives_reloads_config_changes_and_exact_expiry(client, monkeypatch):
    from pathlib import Path
    import os
    from app.services import interview_clock
    headers, item = started_interview(client)
    iid, deadline = item['id'], item['deadline_at']
    config = Path(os.environ['SCU_CONFIG'])
    config.write_text(config.read_text().replace('duration_seconds = 600', 'duration_seconds = 1200'))
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: deadline - 60)
    current = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert current['remaining_seconds'] == 60 and current['duration_seconds'] == 600
    assert current['deadline_at'] == deadline
    assert client.post(f'/api/interviews/{iid}/start', headers=headers).json()['deadline_at'] == deadline
    assert client.put(f'/api/interviews/{iid}/answers/1', headers=headers,
                      json={'transcript': '截止前保存'}).status_code == 200
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: deadline)
    current = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert current['status'] == 'expired' and current['remaining_seconds'] == 0
    assert client.get('/api/interviews', headers=headers).json()[0]['status'] == 'expired'
    for method, path, kwargs in [
        ('put', '/answers/1', {'json': {'transcript': '截止后覆盖'}}),
        ('post', '/answers/1/audio', {'files': {'file': ('a.webm', b'late')}}),
        ('post', '/answers/1/transcribe', {}),
        ('post', '/teacher-question', {}),
        ('post', '/complete-introduction', {}),
    ]:
        assert getattr(client, method)(f'/api/interviews/{iid}{path}', headers=headers, **kwargs).status_code == 409
    assert upload(client, iid, headers).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][0]['transcript'] == '截止前保存'
    assert client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=headers).status_code == 200


def test_expired_incomplete_interview_can_get_feedback_and_retry_after_ai_failure(client, monkeypatch):
    from fastapi import HTTPException
    from app.services import ai, interview_clock
    from test_interview_completion import expert_interview
    headers, iid = expert_interview(client, monkeypatch)
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert client.put(f'/api/interviews/{iid}/answers/5', headers=headers,
                      json={'transcript': '已保存的部分回答'}).status_code == 200
    # An earlier fixed answer remains incomplete when the expert stage times out.
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE answers SET transcript='' WHERE interview_id=? AND stage=4", (iid,))
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
    def unavailable(prompt, **kwargs):
        raise HTTPException(503, 'AI 暂不可用')
    monkeypatch.setattr(ai, 'chat', unavailable)
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 503
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['status'] == 'expired'
    prompts = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: prompts.append(prompt) or '基于部分回答的点评')
    response = client.post(f'/api/interviews/{iid}/finish', headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'finished' and result['timed_out']
    assert result['ended_at'] == item['deadline_at']
    assert result['answers'][4]['transcript'] == '已保存的部分回答'
    assert '限时' in prompts[0] and '未完成' in prompts[0]
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).json()['feedback'] == result['feedback']
    assert len(prompts) == 1


def test_asr_result_finishing_after_deadline_cannot_replace_answer(client, monkeypatch):
    from app.services import ai, interview_clock
    headers, item = started_interview(client)
    iid = item['id']
    client.put(f'/api/interviews/{iid}/answers/1', headers=headers, json={'transcript': '原回答'})
    assert client.post(f'/api/interviews/{iid}/answers/1/audio', headers=headers,
                       files={'file': ('a.webm', b'saved')}).status_code == 200
    def slow_transcribe(path):
        monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
        return '超时才返回的转写'
    monkeypatch.setattr(ai, 'transcribe', slow_transcribe)
    assert client.post(f'/api/interviews/{iid}/answers/1/transcribe', headers=headers).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][0]['transcript'] == '原回答'
    assert client.get(f'/api/interviews/{iid}/answers/1/audio', headers=headers).content == b'saved'
