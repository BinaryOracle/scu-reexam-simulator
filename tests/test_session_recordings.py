"""Whole-session audio is private, checkpointed and finalizable after the deadline."""
from test_system import client, login
from test_presentations import upload, draw_questions


def started(client):
    headers = login(client, 'alice')
    item = client.post('/api/interviews', headers=headers).json()
    assert upload(client, item['id'], headers).status_code == 200
    return headers, client.post(f"/api/interviews/{item['id']}/start", headers=headers).json()


def save(client, base, headers, data=b'whole audio', final=False):
    return client.put(base, headers=headers, files={'file': ('session.webm', data, 'audio/webm')},
                      data={'final': str(final).lower()})


def test_session_checkpoint_unlocks_intro_without_manual_transcript(client):
    headers, item = started(client)
    iid = item['id']
    assert item['workflow_version'] == 5
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 409
    part = client.post(f'/api/interviews/{iid}/recordings', headers=headers)
    assert part.status_code == 201
    base = f"/api/interviews/{iid}/recordings/{part.json()['id']}"
    assert save(client, base, headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 200
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert item['recordings'][0]['has_audio'] and not item['recordings'][0]['finalized']
    assert 'audio_path' not in str(item['recordings'])
    assert client.get(base, headers=headers).content == b'whole audio'
    assert client.get(base, headers=login(client, 'bob')).status_code == 404
    assert save(client, base, login(client, 'bob')).status_code == 404
    admin = base.replace('/api/', '/api/admin/', 1)
    assert client.get(admin, headers=login(client, 'manager')).content == b'whole audio'
    assert client.get(admin, headers=login(client, 'bob')).status_code == 403


def test_final_audio_allowed_in_grace_but_no_new_recording_or_answers(client, monkeypatch):
    from app.services import interview_clock
    headers, item = started(client)
    iid = item['id']
    part = client.post(f'/api/interviews/{iid}/recordings', headers=headers).json()['id']
    base = f'/api/interviews/{iid}/recordings/{part}'
    assert save(client, base, headers, b'checkpoint').status_code == 200
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
    assert save(client, base, headers).status_code == 409
    assert client.post(f'/api/interviews/{iid}/recordings', headers=headers).status_code == 409
    assert client.put(f'/api/interviews/{iid}/answers/1', headers=headers, json={'transcript':'late'}).status_code == 409
    assert save(client, base, headers, b'complete recording', final=True).status_code == 200
    assert save(client, base, headers, b'complete recording', final=True).status_code == 200
    assert save(client, base, headers, b'changed', final=True).status_code == 409
    assert client.get(base, headers=headers).content == b'complete recording'
    assert client.post(f'/api/interviews/{iid}/stop', headers=headers).json()['ended_at'] == item['deadline_at']


def test_early_stop_finalizes_existing_recording_and_rejects_late_upload(client, monkeypatch):
    from app.services import interview_clock
    headers, item = started(client)
    iid = item['id']
    rid = client.post(f'/api/interviews/{iid}/recordings', headers=headers).json()['id']
    base = f'/api/interviews/{iid}/recordings/{rid}'
    stopped = client.post(f'/api/interviews/{iid}/stop', headers=headers).json()
    assert save(client, base, headers, final=True).status_code == 200
    assert save(client, base, headers).status_code == 409
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: stopped['ended_at'] + item['recording_options']['finalize_grace_seconds'] + 1)
    assert save(client, base, headers, b'late', final=True).status_code == 409


def test_recording_transcript_informs_expert_and_review(client, monkeypatch):
    from app.services import ai
    headers, item = started(client)
    iid = item['id']
    rid = client.post(f'/api/interviews/{iid}/recordings', headers=headers).json()['id']
    base = f'/api/interviews/{iid}/recordings/{rid}'
    assert save(client, base, headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 200
    monkeypatch.setattr(ai, 'transcribe', lambda path: '全程语音：介绍与项目研究')
    assert client.post(f'/api/interviews/{iid}/recordings/transcribe', headers=headers).status_code == 200
    prompts = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: prompts.append(prompt) or '专家内容')
    draw_questions(client, iid, headers)
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    assert '全程语音：介绍与项目研究' in prompts[0]
    assert client.post(f'/api/interviews/{iid}/stop', headers=headers).status_code == 200
    assert save(client, base, headers, b'final', final=True).status_code == 200
    monkeypatch.setattr(ai, 'transcribe', lambda path: '最终全场语音：包含专家回答')
    assert client.post(f'/api/interviews/{iid}/recordings/transcribe', headers=headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 200
    assert '最终全场语音：包含专家回答' in prompts[-1]
    assert save(client, base, headers, b'new', final=True).status_code == 409


def test_preparing_cannot_open_recording_and_invalid_audio_preserves_checkpoint(client):
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    assert client.post(f'/api/interviews/{iid}/recordings', headers=headers).status_code == 409
    headers, item = started(client)
    rid = client.post(f"/api/interviews/{item['id']}/recordings", headers=headers).json()['id']
    base = f"/api/interviews/{item['id']}/recordings/{rid}"
    assert save(client, base, headers, b'valid').status_code == 200
    assert save(client, base, headers, b'').status_code == 400
    assert client.get(base, headers=headers).content == b'valid'


def test_live_transcription_is_private_and_rechecks_deadline(client, monkeypatch):
    from app.services import ai, interview_clock
    from app.config import load_config
    from pathlib import Path
    headers, item = started(client)
    iid = item['id']
    path = f'/api/interviews/{iid}/answers/1/live-transcribe'
    files = {'file': ('speech.webm', b'speech', 'audio/webm')}
    calls = []
    monkeypatch.setattr(ai, 'transcribe', lambda path: calls.append(path) or '实时回答')
    assert client.post(path, files=files).status_code == 401
    assert client.post(path, headers=login(client, 'bob'), files=files).status_code == 404
    assert client.post(path, headers=headers, files=files).json()['transcript'] == '实时回答'
    assert not calls[0].exists()
    def slow(source):
        monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
        return '迟到的识别结果'
    monkeypatch.setattr(ai, 'transcribe', slow)
    assert client.post(path, headers=headers, files=files).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['answers'][0]['transcript'] == ''
    assert not list(Path(load_config()['app']['upload_dir']).glob('*.webm'))
