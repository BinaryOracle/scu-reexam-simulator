"""Presentation upload, private previews and recorded introduction completion."""
import shutil
import time
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from app.config import load_config
from app.db import connect
from app.services.auth import administrator, interview_user
from app.services.interviews import active_interview, details, interview, seed_answers
from app.services import presentations, presentation_template
from app.services.interview_clock import timestamp
from app.services.credits import charge_interview

router = APIRouter()


@router.get('/api/interview-setup')
def interview_setup(user=Depends(interview_user)):
    """Read preparation settings without allocating an interview or file storage."""
    config = load_config()
    return {'default_presentation': presentation_template.metadata(),
            'presentation_limits': {key: config['presentation'][key] for key in ('max_mb', 'max_pages')},
            'duration_seconds': config['interview']['duration_seconds']}


@router.post('/api/interviews/start', status_code=201)
async def create_started_interview(file: UploadFile = File(...), authorization: str = Header(), user=Depends(interview_user)):
    """Create and charge after conversion only while the original login session remains active."""
    config = load_config()
    limit = config['presentation']['max_mb'] * 1024 * 1024
    content = await file.read(limit + 1)
    if not content or len(content) > limit:
        raise HTTPException(400, '演示文件为空或超出大小限制')
    prepared = await run_in_threadpool(presentations.prepare, content, file.filename or '')
    try:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            session = db.execute('''SELECT 1 FROM sessions JOIN users ON users.id=sessions.user_id
                WHERE sessions.token=? AND users.id=? AND sessions.expires>? AND users.is_active=1''',
                (authorization[7:], user['id'], time.time())).fetchone()
            if session is None:
                raise HTTPException(401, '登录已过期或账号已停用，请重新登录后上传演示文件')
            now = timestamp()
            iid = db.execute('''INSERT INTO interviews(user_id,created,workflow_version,started_at,deadline_at)
                VALUES (?,?,5,?,?)''', (user['id'], now, now, now + config['interview']['duration_seconds'])).lastrowid
            charge_interview(db, iid, user['id'])
            seed_answers(db, iid)
            db.execute('INSERT INTO presentations(interview_id,directory,name,pages) VALUES (?,?,?,?)',
                       (iid, prepared['directory'], prepared['name'], prepared['pages']))
            result = details(db, iid)
    except BaseException:
        shutil.rmtree(prepared['directory'], ignore_errors=True)
        raise
    return result


def editable_presentation(db, iid, user):
    item = active_interview(db, iid, user, preparing=True)
    if item['workflow_version'] >= 3 and item['started_at'] is not None:
        raise HTTPException(409, '面试已开始，不能替换 PPT')
    if item['workflow_version'] < 2 or item['intro_completed']:
        raise HTTPException(409, '本场面试已进入后续环节或使用旧流程，不能替换 PPT')
    return item


@router.post('/api/interviews/{iid}/presentation')
async def upload_presentation(iid: int, file: UploadFile = File(...), user=Depends(interview_user)):
    with connect() as db:
        editable_presentation(db, iid, user)
    limit = load_config()['presentation']['max_mb'] * 1024 * 1024
    content = await file.read(limit + 1)
    if not content or len(content) > limit:
        raise HTTPException(400, '演示文件为空或超出大小限制')
    prepared = await run_in_threadpool(presentations.prepare, content, file.filename or '')
    try:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            editable_presentation(db, iid, user)
            # Replacing slides invalidates the associated introduction recording/text.
            db.execute('''INSERT INTO presentations(interview_id,directory,name,pages) VALUES (?,?,?,?)
                ON CONFLICT(interview_id) DO UPDATE SET directory=excluded.directory,name=excluded.name,pages=excluded.pages''',
                (iid, prepared['directory'], prepared['name'], prepared['pages']))
            db.execute("UPDATE answers SET transcript='',audio_path=NULL WHERE interview_id=? AND stage=1", (iid,))
            result = details(db, iid)
    except BaseException:
        shutil.rmtree(prepared['directory'], ignore_errors=True)
        raise
    return result


@router.get('/api/interviews/{iid}/presentation/pages/{page}')
def get_page(iid: int, page: int, user=Depends(interview_user)):
    with connect() as db:
        item = interview(db, iid, user)
        if item['workflow_version'] >= 3 and item['started_at'] is None:
            raise HTTPException(409, '开始本轮面试后展示个人 PPT')
        return presentations.page_response(db, iid, page)


@router.post('/api/interviews/{iid}/start')
def start_interview(iid: int, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user, preparing=True)
        if item['workflow_version'] < 3:
            raise HTTPException(409, '历史面试使用原流程，无需重新开始')
        if item['started_at'] is None:
            if not db.execute('SELECT 1 FROM presentations WHERE interview_id=?', (iid,)).fetchone():
                raise HTTPException(409, '请先上传自己的复试 PPT')
            now = timestamp()
            charge_interview(db, iid, user['id'])
            db.execute('UPDATE interviews SET started_at=?,deadline_at=? WHERE id=?',
                       (now, now + load_config()['interview']['duration_seconds'], iid))
        return details(db, iid)


@router.get('/api/admin/interviews/{iid}/presentation/pages/{page}')
def admin_page(iid: int, page: int, user=Depends(administrator)):
    from app.services.auth import reviewable_interview
    with connect() as db:
        reviewable_interview(db, iid, user)
        return presentations.page_response(db, iid, page)


@router.post('/api/interviews/{iid}/complete-introduction')
def complete_introduction(iid: int, user=Depends(interview_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = active_interview(db, iid, user)
        if item['workflow_version'] < 2:
            raise HTTPException(409, '历史面试使用原流程')
        row = db.execute('''SELECT transcript,audio_path FROM answers WHERE interview_id=? AND stage=1''', (iid,)).fetchone()
        recorded = db.execute('SELECT 1 FROM interview_recordings WHERE interview_id=? AND audio_path IS NOT NULL', (iid,)).fetchone()
        ready = (recorded or (row and row['audio_path'])) if item['workflow_version'] >= 4 else (row and row['audio_path'] and row['transcript'].strip())
        if not db.execute('SELECT 1 FROM presentations WHERE interview_id=?', (iid,)).fetchone() or not ready:
            raise HTTPException(409, '请先上传 PPT，保存自我介绍录音并转写或填写回答，再完成本环节')
        db.execute('UPDATE interviews SET intro_completed=1 WHERE id=?', (iid,))
        return details(db, iid)


@router.get('/api/presentation-template')
def template_metadata():
    return presentation_template.metadata()


@router.get('/api/presentation-template/download')
def download_template():
    return presentation_template.download()


@router.get('/api/presentation-template/pages/{page}')
def template_page(page: int):
    return presentation_template.page_response(page)
