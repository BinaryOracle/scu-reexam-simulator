"""Stopping is independent of AI; feedback belongs to the expert stage."""
from fastapi import HTTPException
from test_system import client, login
from test_presentations import prepare_intro, draw_questions


def expert_interview(client, monkeypatch):
    from app.services import ai
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    draw_questions(client, iid, headers)
    for stage in range(2, 5):
        assert client.put(f'/api/interviews/{iid}/answers/{stage}', headers=headers,
                          json={'transcript': f'第 {stage} 个回答'}).status_code == 200
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '请解释项目中的技术取舍')
    assert client.post(f'/api/interviews/{iid}/teacher-question', headers=headers).status_code == 200
    return headers, iid


def test_stop_preserves_answers_without_ai_and_locks_all_writes(client, monkeypatch):
    from app.services import ai
    def forbidden(prompt, **kwargs):
        raise AssertionError('Ending an interview must not call AI')
    monkeypatch.setattr(ai, 'chat', forbidden)
    alice, bob = [login(client, name) for name in ['alice', 'bob']]
    iid = client.post('/api/interviews', headers=alice).json()['id']
    prepare_intro(client, iid, alice)
    draw_questions(client, iid, alice)
    client.put(f'/api/interviews/{iid}/answers/2', headers=alice, json={'transcript':'提前结束前保存'})
    url = f'/api/interviews/{iid}/stop'
    assert client.post(url).status_code == 401
    assert client.post(url, headers=bob).status_code == 404
    result = client.post(url, headers=alice)
    assert result.status_code == 200, result.text
    item = result.json()
    assert item['status'] == 'finished' and item['feedback'] is None
    assert item['ended_at'] < item['deadline_at']
    assert item['answers'][1]['transcript'] == '提前结束前保存'
    assert client.post(url, headers=alice).json()['ended_at'] == item['ended_at']
    assert client.put(f'/api/interviews/{iid}/answers/2', headers=alice,
                      json={'transcript':'结束后修改'}).status_code == 409
    assert client.post(f'/api/interviews/{iid}/answers/2/audio', headers=alice,
                       files={'file':('a.webm', b'audio')}).status_code == 409
    for path in ['start', 'teacher-question', 'finish']:
        assert client.post(f'/api/interviews/{iid}/{path}', headers=alice).status_code == 409


def test_preparation_can_be_ended_without_starting_timer(client):
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    result = client.post(f'/api/interviews/{iid}/stop', headers=headers)
    assert result.status_code == 200
    assert result.json()['status'] == 'finished'
    assert result.json()['started_at'] is None and result.json()['feedback'] is None


def test_record_summaries_expose_feedback_presence_without_review_content(client, monkeypatch):
    from app.services import ai
    headers, iid = expert_interview(client, monkeypatch)
    before = next(row for row in client.get('/api/interviews', headers=headers).json() if row['id'] == iid)
    assert before['has_feedback'] is False and 'feedback' not in before
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: 'Detailed private review')
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 200
    after = next(row for row in client.get('/api/interviews', headers=headers).json() if row['id'] == iid)
    assert after['has_feedback'] is True and 'feedback' not in after


def test_feedback_is_blocked_before_expert_even_after_timeout(client, monkeypatch):
    from app.services import ai, interview_clock
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    prepare_intro(client, iid, headers)
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    calls = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: calls.append(prompt) or '点评')
    monkeypatch.setattr(interview_clock, 'timestamp', lambda: item['deadline_at'])
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 409
    stopped = client.post(f'/api/interviews/{iid}/stop', headers=headers).json()
    assert stopped['ended_at'] == item['deadline_at']
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 409
    assert calls == []


def test_stopped_expert_can_retry_feedback_without_reopening_interview(client, monkeypatch):
    from app.services import ai
    headers, iid = expert_interview(client, monkeypatch)
    item = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert item['expert_stage'] == 5
    assert client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=headers).status_code == 200
    def forbidden(prompt, **kwargs):
        raise AssertionError('Stopping at expert stage must not generate feedback')
    monkeypatch.setattr(ai, 'chat', forbidden)
    stopped = client.post(f'/api/interviews/{iid}/stop', headers=headers).json()
    assert stopped['status'] == 'finished' and stopped['feedback'] is None
    assert client.post(f'/api/interviews/{iid}/stop', headers=headers).json()['feedback'] is None
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['feedback'] is None
    assert client.get('/api/interviews', headers=headers).status_code == 200
    def unavailable(prompt, **kwargs):
        raise HTTPException(503, 'AI 暂不可用')
    monkeypatch.setattr(ai, 'chat', unavailable)
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 503
    result = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert result['status'] == 'finished' and result['feedback'] is None
    assert result['ended_at'] == stopped['ended_at']
    calls = []
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: calls.append(prompt) or '基于已保存内容的点评')
    result = client.post(f'/api/interviews/{iid}/finish', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['feedback'] == '基于已保存内容的点评'
    assert result.json()['ended_at'] == stopped['ended_at']
    assert '未完成' in calls[0]
    assert client.post(f'/api/interviews/{iid}/finish', headers=headers).status_code == 200
    assert len(calls) == 1
