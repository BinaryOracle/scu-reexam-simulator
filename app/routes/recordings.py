"""Continuous interview audio: replaceable checkpoints, immutable final audio and ASR."""
import hashlib
import secrets
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from app.config import load_config
from app.db import connect
from app.services.auth import administrator, interview_user, reviewable_interview
from app.services.interviews import interview, active_interview, require_stage, details
from app.services import ai, interview_clock

router = APIRouter()


def recording(db, iid, rid):
    row = db.execute('SELECT * FROM interview_recordings WHERE interview_id=? AND id=?', (iid, rid)).fetchone()
    if row is None:
        raise HTTPException(404, '录音不存在')
    return row


def require_upload(item, final):
    """Only an existing recording can finalize during a bounded post-end upload window."""
    if item['feedback'] is not None or item['started_at'] is None:
        raise HTTPException(409, '当前面试不接受录音上传')
    if not final:
        if item['status'] != 'active':
            raise HTTPException(409, '面试已结束')
        interview_clock.require_running(item)
    else:
        end = item['ended_at'] if item['ended_at'] is not None else item['deadline_at']
        if interview_clock.timestamp() > end + load_config()['recording']['finalize_grace_seconds']:
            raise HTTPException(409, '录音上传时间已过，请下载并保留本地录音')


@router.post('/api/interviews/{iid}/recordings', status_code=201)
def begin_recording(iid: int, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        active_interview(db, iid, user)
        rid = secrets.token_hex(20)
        db.execute('INSERT INTO interview_recordings(id,interview_id,created) VALUES (?,?,?)',
                   (rid, iid, interview_clock.timestamp()))
        return {'id': rid}


@router.put('/api/interviews/{iid}/recordings/{rid}')
async def upload_recording(iid: int, rid: str, file: UploadFile = File(...),
                           final: bool = Form(False), user=Depends(interview_user)):
    with connect() as db:
        item = interview(db, iid, user)
        recording(db, iid, rid)
        require_upload(item, final)
    content = await file.read(load_config()['app']['max_audio_mb'] * 1024 * 1024 + 1)
    if not content or len(content) > load_config()['app']['max_audio_mb'] * 1024 * 1024:
        raise HTTPException(400, '录音为空或超出大小限制')
    mime = (file.content_type or '').split(';')[0]
    extensions = {'audio/webm': '.webm', 'audio/mp4': '.m4a', 'audio/ogg': '.ogg'}
    if mime not in extensions:
        raise HTTPException(400, '不支持的录音格式')
    digest = hashlib.sha256(content).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = interview(db, iid, user)
        require_upload(item, final)
        old = recording(db, iid, rid)
        if old['finalized']:
            if final and old['digest'] == digest:
                return details(db, iid)
            raise HTTPException(409, '最终录音已保存，不能覆盖')
        directory = Path(load_config()['app']['upload_dir'])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (secrets.token_hex(20) + extensions[mime])
        try:
            path.write_bytes(content)
            require_upload(item, final)
            db.execute('''UPDATE interview_recordings SET audio_path=?,mime_type=?,digest=?,finalized=?,
                transcript=CASE WHEN digest=? THEN transcript ELSE '' END WHERE id=?''',
                (str(path), mime, digest, final, digest, rid))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    if old['audio_path']:
        Path(old['audio_path']).unlink(missing_ok=True)
    with connect() as db:
        return details(db, iid)


def audio_response(db, iid, rid):
    row = recording(db, iid, rid)
    if not row['audio_path'] or not Path(row['audio_path']).is_file():
        raise HTTPException(404, '录音尚未保存')
    return FileResponse(row['audio_path'], media_type=row['mime_type'], headers={'Cache-Control': 'private, no-store'})


@router.get('/api/interviews/{iid}/recordings/{rid}')
def get_recording(iid: int, rid: str, user=Depends(interview_user)):
    with connect() as db:
        interview(db, iid, user)
        return audio_response(db, iid, rid)


@router.get('/api/admin/interviews/{iid}/recordings/{rid}')
def admin_recording(iid: int, rid: str, user=Depends(administrator)):
    with connect() as db:
        reviewable_interview(db, iid, user)
        return audio_response(db, iid, rid)


@router.post('/api/interviews/{iid}/recordings/transcribe')
def transcribe_recordings(iid: int, user=Depends(interview_user)):
    with connect() as db:
        item = interview(db, iid, user)
        if item['feedback'] is not None:
            return details(db, iid)
        rows = db.execute('SELECT * FROM interview_recordings WHERE interview_id=? AND audio_path IS NOT NULL ORDER BY created,id', (iid,)).fetchall()
    for row in rows:
        if row['transcript']:
            continue
        text = ai.transcribe(Path(row['audio_path']))
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current_item = interview(db, iid, user)
            if current_item['feedback'] is not None:
                raise HTTPException(409, '点评已生成，不能再修改转写')
            current = recording(db, iid, row['id'])
            if current['digest'] != row['digest']:
                raise HTTPException(409, '录音已更新，请重试转写')
            db.execute('UPDATE interview_recordings SET transcript=? WHERE id=?', (text, row['id']))
    with connect() as db:
        return details(db, iid)


@router.post('/api/interviews/{iid}/answers/{stage}/live-transcribe')
async def live_transcribe(iid: int, stage: int, file: UploadFile = File(...), user=Depends(interview_user)):
    with connect() as db:
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
        if not db.execute('SELECT 1 FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone():
            raise HTTPException(404, '面试环节不存在')
    content = await file.read(load_config()['app']['max_audio_mb'] * 1024 * 1024 + 1)
    if not content or len(content) > load_config()['app']['max_audio_mb'] * 1024 * 1024:
        raise HTTPException(400, '录音为空或超出大小限制')
    directory = Path(load_config()['app']['upload_dir'])
    directory.mkdir(parents=True, exist_ok=True)
    suffix = '.m4a' if (file.content_type or '').startswith('audio/mp4') else '.webm'
    path = directory / (secrets.token_hex(20) + suffix)
    try:
        path.write_bytes(content)
        text = await run_in_threadpool(ai.transcribe, path)
    finally:
        path.unlink(missing_ok=True)
    with connect() as db:
        item = active_interview(db, iid, user)
        require_stage(db, item, stage)
    return {'transcript': text}
