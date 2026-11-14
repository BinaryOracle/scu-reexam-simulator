"""PPT-first expert questioning, multimodal reviews and private speech playback."""
from pathlib import Path
from fastapi import HTTPException
import pytest
from test_system import client, login
from test_presentations import prepare_intro, draw_questions


def ready(client, monkeypatch):
    from app.services import ai
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    draw_questions(client, iid, headers)
    monkeypatch.setattr(ai, 'media_audio', lambda paths: [{'type': 'input_audio', 'input_audio': {'data': 'candidate-recording'}}], raising=False)
    return headers, iid


def test_expert_question_uses_candidate_ppt_and_audio_without_requiring_asr(client, monkeypatch):
    from app.services import ai
    headers, iid = ready(client, monkeypatch)
    calls = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: calls.append((prompt, kwargs)) or 'Your research project uses which isolation strategy?')
    response = client.post(f'/api/interviews/{iid}/teacher-question', headers=headers)
    assert response.status_code == 200, response.text
    prompt, kwargs = calls[0]
    assert 'Research project' in prompt and 'Self introduction' in prompt
    assert 'PPT' in kwargs['system'] and '第一' in kwargs['system'] and '不可信' in kwargs['system']
    assert len([part for part in kwargs['media'] if part['type'] == 'image_url']) == 2
    assert len([part for part in kwargs['media'] if part['type'] == 'input_audio']) == 1
    result = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert len(result['answers']) == 5 and result['feedback'] is None
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).json() == response.json()
    assert len(calls) == 1


def test_question_model_request_does_not_hold_sqlite_write_lock_and_allows_audio_checkpoint(client, monkeypatch, tmp_path):
    from app.services import ai
    from app.db import connect
    headers, iid = ready(client, monkeypatch)
    def chat(prompt, **kwargs):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE interviews SET title=? WHERE id=?', ('while AI is waiting', iid))
            db.execute("UPDATE answers SET transcript='实时转写补充' WHERE interview_id=? AND stage=4", (iid,))
            db.execute('INSERT INTO interview_recordings(id,interview_id,created,digest) VALUES (?,?,?,?)', ('live-checkpoint', iid, 1, 'new-digest'))
        return '请解释你的项目设计'
    monkeypatch.setattr(ai, 'chat', chat)
    result = client.post(f'/api/interviews/{iid}/teacher-question', headers=headers)
    assert result.status_code == 200, result.text


@pytest.mark.parametrize('change', ['deleted', 'deadline', 'presentation', 'question'])
def test_question_rejects_results_when_source_or_interview_is_invalidated(client, monkeypatch, change):
    from app.services import ai, interview_clock
    from app.db import connect
    headers, iid = ready(client, monkeypatch)
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    def chat(prompt, **kwargs):
        if change == 'deadline':
            monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
        elif change == 'deleted':
            assert client.delete(f'/api/interviews/{iid}', headers=headers).status_code == 204
        else:
            with connect() as db:
                if change == 'presentation':
                    source = Path(db.execute('SELECT directory FROM presentations WHERE interview_id=?', (iid,)).fetchone()[0]) / 'source.pdf'
                    source.write_bytes(source.read_bytes() + b'\n% changed')
                else:
                    db.execute("UPDATE answers SET question='Changed question' WHERE interview_id=? AND stage=2", (iid,))
        return '不应保存的问题'
    monkeypatch.setattr(ai, 'chat', chat)
    result = client.post(f'/api/interviews/{iid}/teacher-question', headers=headers)
    assert result.status_code == (404 if change == 'deleted' else 409), result.text
    if change != 'deleted':
        assert len(client.get(f'/api/interviews/{iid}', headers=headers).json()['answers']) == 4


def test_feedback_is_manual_covers_audio_and_keeps_original_end_after_failure(client, monkeypatch):
    from app.services import ai
    from app.db import connect
    headers, iid = ready(client, monkeypatch)
    calls = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: calls.append((prompt, kwargs)) or '请解释项目的取舍')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    assert len(calls) == 1
    monkeypatch.setattr(ai, 'transcribe', lambda path: (_ for _ in ()).throw(AssertionError('ASR cannot gate feedback')))
    def unavailable(prompt, **kwargs):
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE interviews SET title='feedback retry' WHERE id=?", (iid,))
        raise HTTPException(503, 'model temporarily unavailable')
    monkeypatch.setattr(ai, 'chat', unavailable)
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 503
    stopped = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert stopped['status'] == 'finished' and stopped['feedback'] is None
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: calls.append((prompt, kwargs)) or '整场评价')
    result = client.post(f'/api/interviews/{iid}/finish', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['feedback'] == '整场评价'
    assert result.json()['ended_at'] == stopped['ended_at']
    assert 'Research project' in calls[-1][0] and '证据不足' in calls[-1][1]['system']
    assert any(part['type'] == 'input_audio' for part in calls[-1][1]['media'])
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).json()['feedback'] == '整场评价'
    assert len(calls) == 2


def test_feedback_rejects_changed_saved_answer_and_can_retry(client, monkeypatch):
    from app.services import ai
    from app.db import connect
    headers, iid = ready(client, monkeypatch)
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '请说明项目')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    def changed(prompt, **kwargs):
        with connect() as db:
            db.execute("UPDATE answers SET transcript='更新内容' WHERE interview_id=? AND stage=5", (iid,))
        return '过期评价'
    monkeypatch.setattr(ai, 'chat', changed)
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 409
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['feedback'] is None
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '基于新材料的评价')
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).json()['feedback'] == '基于新材料的评价'


def test_expert_speech_is_private_and_only_reads_the_saved_question(client, monkeypatch):
    from app.services import ai
    headers, iid = ready(client, monkeypatch)
    url = f'/api/interviews/{iid}/expert-speech'
    spoken = []
    monkeypatch.setattr(ai, 'synthesize', lambda text: spoken.append(text) or (b'RIFFspoken-wave', 'audio/wav'), raising=False)
    assert client.post(url, headers=headers).status_code == 409
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '你在项目中如何处理事务隔离？')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    assert client.post(url).status_code == 401
    assert client.post(url, headers=login(client, 'bob')).status_code == 404
    assert client.post(url, headers=login(client, 'manager')).status_code == 404
    result = client.post(url, headers=headers)
    assert result.status_code == 200 and result.content == b'RIFFspoken-wave'
    assert result.headers['cache-control'] == 'private, no-store'
    assert spoken == ['你在项目中如何处理事务隔离？']
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['feedback'] is None


@pytest.mark.parametrize('change', ['deleted', 'recording', 'presentation'])
def test_feedback_does_not_commit_a_result_for_changed_or_deleted_evidence(client, monkeypatch, change):
    from app.services import ai
    from app.db import connect
    headers, iid = ready(client, monkeypatch)
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '请解释项目')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    def changed(prompt, **kwargs):
        if change == 'deleted':
            assert client.delete(f'/api/interviews/{iid}', headers=headers).status_code == 204
        else:
            with connect() as db:
                if change == 'recording':
                    db.execute('INSERT INTO interview_recordings(id,interview_id,created,digest) VALUES (?,?,?,?)',
                               ('final-upload', iid, 1, 'new-final-digest'))
                else:
                    directory = db.execute('SELECT directory FROM presentations WHERE interview_id=?', (iid,)).fetchone()[0]
                    source = Path(directory) / 'source.pdf'
                    source.write_bytes(source.read_bytes() + b'\n% newer-material')
        return '不应落库的旧材料点评'
    monkeypatch.setattr(ai, 'chat', changed)
    response = client.post(f'/api/interviews/{iid}/finish', headers=headers)
    assert response.status_code == (404 if change == 'deleted' else 409), response.text
    if change != 'deleted':
        assert client.get(f'/api/interviews/{iid}', headers=headers).json()['feedback'] is None


def test_speech_service_failure_leaves_expert_question_and_review_action_available(client, monkeypatch):
    from app.services import ai
    headers, iid = ready(client, monkeypatch)
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '请解释你的项目中最重要的技术取舍？')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    def unavailable(text):
        raise HTTPException(502, '语音合成暂不可用，可阅读专家问题')
    monkeypatch.setattr(ai, 'synthesize', unavailable)
    assert client.post(f'/api/interviews/{iid}/expert-speech', headers=headers).status_code == 502
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert item['answers'][-1]['question'] == '请解释你的项目中最重要的技术取舍？'
    assert item['status'] == 'active' and item['feedback'] is None
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 200
