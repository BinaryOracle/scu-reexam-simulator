"""Expert context uses the candidate's complete private slides and saved audio."""
import base64
from pathlib import Path
import pymupdf
import pytest
from fastapi import HTTPException


def snapshot(tmp_path, version=5):
    deck = tmp_path / 'candidate'
    deck.mkdir()
    with pymupdf.open() as document:
        for text in ['Candidate project: MiniDB', 'Research: transaction isolation']:
            document.new_page().insert_text((50, 80), text)
        document.save(deck / 'source.pdf')
    return {'interview': {'id': 1, 'workflow_version': version, 'status': 'active', 'ended_at': None},
            'presentation': {'directory': str(deck), 'name': 'candidate.pdf', 'pages': 2},
            'answers': [{'id': 1, 'stage': 1, 'question': 'Introduce yourself', 'transcript': '',
                         'audio_path': None, 'subject': '', 'question_choices': 0}],
            'recordings': []}


def test_complete_candidate_ppt_text_and_images_are_untrusted_context(tmp_path, monkeypatch):
    from app.services import expert_context
    item = snapshot(tmp_path)
    result = expert_context.build(item, purpose='question')
    assert 'Candidate project: MiniDB' in result.prompt
    assert 'Research: transaction isolation' in result.prompt
    assert '不可信' in result.prompt
    assert '复试' in expert_context.QUESTION_SYSTEM and '官方' in expert_context.QUESTION_SYSTEM
    assert '第一' in expert_context.QUESTION_SYSTEM and 'PPT' in expert_context.QUESTION_SYSTEM
    images = [part for part in result.media if part['type'] == 'image_url']
    assert len(images) == 2
    assert all(base64.b64decode(part['image_url']['url'].split(',', 1)[1]).startswith(b'\xff\xd8') for part in images)
    assert result.presentation_digest


def test_missing_user_ppt_never_uses_public_template(tmp_path):
    from app.services import expert_context
    item = snapshot(tmp_path)
    Path(item['presentation']['directory'], 'source.pdf').unlink()
    with pytest.raises(HTTPException) as error:
        expert_context.build(item, purpose='question')
    assert error.value.status_code == 503 and '恢复' in error.value.detail
    item['presentation'] = None
    with pytest.raises(HTTPException) as error:
        expert_context.build(item, purpose='question')
    assert error.value.status_code == 409
    item['interview']['workflow_version'] = 1
    result = expert_context.build(item, purpose='question')
    assert '未提供' in result.prompt and result.media == []


def test_corrupt_ppt_and_context_overflow_fail_with_actionable_error(tmp_path, monkeypatch):
    from app.services import expert_context
    item = snapshot(tmp_path)
    real_config = expert_context.load_config
    def small_config():
        config = real_config()
        config['ai']['max_context_chars'] = 10
        return config
    monkeypatch.setattr(expert_context, 'load_config', small_config)
    with pytest.raises(HTTPException) as error:
        expert_context.build(item, purpose='question')
    assert error.value.status_code == 413 and '配置' in error.value.detail
    monkeypatch.setattr(expert_context, 'load_config', real_config)
    Path(item['presentation']['directory'], 'source.pdf').write_bytes(b'broken')
    with pytest.raises(HTTPException) as error:
        expert_context.build(item, purpose='question')
    assert error.value.status_code == 503 and '恢复' in error.value.detail


def test_all_full_session_segments_precede_per_answer_audio_without_duplication(tmp_path, monkeypatch):
    from app.services import ai, expert_context
    item = snapshot(tmp_path)
    for name in ('one.webm', 'two.webm', 'answer.webm'):
        (tmp_path / name).write_bytes(name.encode())
    item['answers'][0]['audio_path'] = str(tmp_path / 'answer.webm')
    item['recordings'] = [
        {'id': 'one', 'created': 1, 'audio_path': str(tmp_path / 'one.webm'), 'digest': 'first', 'transcript': '片段一'},
        {'id': 'two', 'created': 2, 'audio_path': str(tmp_path / 'two.webm'), 'digest': 'second', 'transcript': '片段二'},
        {'id': 'duplicate', 'created': 3, 'audio_path': str(tmp_path / 'two.webm'), 'digest': 'second', 'transcript': ''}]
    calls = []
    monkeypatch.setattr(ai, 'media_audio', lambda paths: calls.append(paths) or [{'type': 'input_audio', 'input_audio': {'data': 'audio'}}], raising=False)
    result = expert_context.build(item, purpose='feedback')
    assert calls == [[tmp_path / 'one.webm', tmp_path / 'two.webm']]
    assert len([part for part in result.media if part['type'] == 'input_audio']) == 1
    assert '片段一' in result.prompt and '片段二' in result.prompt
    assert '证据不足' in expert_context.FEEDBACK_SYSTEM
    item['recordings'] = []
    expert_context.build(item, purpose='feedback')
    assert calls[-1] == [tmp_path / 'answer.webm']


def test_page_limit_rejects_instead_of_omitting_slides(tmp_path, monkeypatch):
    from app.services import expert_context
    item = snapshot(tmp_path)
    real_config = expert_context.load_config
    def small_config():
        config = real_config()
        config['ai']['max_slide_pages'] = 1
        return config
    monkeypatch.setattr(expert_context, 'load_config', small_config)
    with pytest.raises(HTTPException) as error:
        expert_context.build(item, purpose='question')
    assert error.value.status_code == 413 and 'max_slide_pages' in error.value.detail
