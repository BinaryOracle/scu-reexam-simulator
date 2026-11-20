"""Shared interview reads; ownership and permissions belong to the caller."""
import json
import os
from fastapi import HTTPException
from app.config import load_config
from app.services.presentation_template import metadata as template_metadata
from app.services.interview_clock import timing, require_running
from app.services.feedback import render_feedback
from app.services import model_settings


def seed_answers(db, iid):
    """Create the four fixed stages for a new question-bank interview."""
    questions = [load_config()['interview']['questions'][0], '请选择专业课学科卡片。',
                 '请将以下英文段落翻译为中文。', '请用英文回答问题。']
    for stage, question in enumerate(questions, 1):
        db.execute('INSERT INTO answers(interview_id,stage,question) VALUES (?,?,?)', (iid, stage, question))


def details(db, iid):
    row = db.execute('SELECT * FROM interviews WHERE id=?', (iid,)).fetchone()
    if row is None:
        raise HTTPException(404, '面试不存在')
    result = dict(row)
    result['feedback_html'] = render_feedback(result['feedback'])
    result.update(timing(row))
    presentation = db.execute('SELECT name,pages FROM presentations WHERE interview_id=?', (iid,)).fetchone()
    config = load_config()['presentation']
    result['presentation_limits'] = {key: config[key] for key in ('max_mb', 'max_pages')}
    result['default_presentation'] = template_metadata()
    result['presentation'] = dict(presentation) if presentation else None
    result['intro_completed'] = bool(result['intro_completed'])
    result['recording_options'] = load_config()['recording']
    asr = model_settings.resolve('asr', load_config())
    result['server_asr_available'] = bool(asr['base_url'] and (asr.get('api_key') or os.getenv(asr['api_key_env'])))
    result['recordings'] = [dict(x) for x in db.execute('''SELECT id,created,
        audio_path IS NOT NULL AS has_audio,finalized,transcript FROM interview_recordings
        WHERE interview_id=? ORDER BY created,id''', (iid,))]
    result['expert_stage'] = 5 if row['workflow_version'] >= 5 else len(load_config()['interview']['questions']) + 1
    result['answers'] = [dict(x) for x in db.execute('''SELECT id,stage,question,transcript,subject,question_choices,question_history,
        audio_path IS NOT NULL AS has_audio FROM answers WHERE interview_id=? ORDER BY stage''', (iid,))]
    for answer in result['answers']:
        answer['question_history'] = json.loads(answer['question_history'])
    return result


def require_stage(db, item, stage, *, selecting=False):
    """Enforce the upload and introduction sequence for new interviews."""
    if item['workflow_version'] < 2:
        return
    if not db.execute('SELECT 1 FROM presentations WHERE interview_id=?', (item['id'],)).fetchone():
        raise HTTPException(409, '请先上传复试 PPT，再开始自我介绍')
    if stage > 1 and not item['intro_completed']:
        raise HTTPException(409, '请先录音完成 PPT 自我介绍，并确认进入下一环节')
    if stage == 1 and item['intro_completed']:
        raise HTTPException(409, '自我介绍已完成，请在后续环节继续作答')
    if item['workflow_version'] >= 5 and stage in (2, 3, 4) and not selecting:
        answer = db.execute('SELECT question_choices FROM answers WHERE interview_id=? AND stage=?', (item['id'], stage)).fetchone()
        if not answer or not answer['question_choices']:
            raise HTTPException(409, '请先选择或抽取本环节题目，再开始作答')


def interview(db, iid, user):
    row = db.execute('SELECT * FROM interviews WHERE id=?', (iid,)).fetchone()
    if not row or row['user_id'] != user['id']:
        raise HTTPException(404, '面试不存在')
    return row

def active_interview(db, iid, user, *, preparing=False):
    row = interview(db, iid, user)
    if row['user_id'] != user['id'] or row['status'] != 'active':
        raise HTTPException(409, '面试不可修改')
    if not preparing:
        require_running(row)
    return row


def summary(row):
    """Return list fields with the same derived timeout state as interview details."""
    result = {key: row[key] for key in ('id', 'created', 'title')}
    result['has_feedback'] = row['feedback'] is not None
    result.update(timing(row))
    return result
