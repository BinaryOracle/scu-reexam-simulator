"""Authenticated classroom API; media credentials remain on the server."""
import asyncio
from functools import wraps
import hashlib
import secrets
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict, StrictBool, StrictInt
from livekit import api
from app.db import connect
from app.services.auth import current_user, administrator
from app.services import live as store, live_media as media
from app.services import course_learning as learning

router = APIRouter(prefix='/api/live', tags=['live'])
_grant_locks = {}
_media_write_lock = asyncio.Lock()


def serialized_media_write(handler):
    """Queue async writers before opening SQLite so network awaits cannot block its event loop."""
    @wraps(handler)
    async def wrapped(*args, **kwargs):
        async with _media_write_lock:
            return await handler(*args, **kwargs)
    return wrapped


class CourseInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)
    host_id: StrictInt = Field(gt=0)
    member_ids: list[StrictInt] = Field(default_factory=list, max_length=1000)


class LessonInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=100)
    starts_at: float
    description: str = Field(default='', max_length=4000)


class PresenceInput(BaseModel):
    hand: StrictBool | None = None
    request_share: StrictBool | None = None


class GrantInput(BaseModel):
    can_speak: StrictBool | None = None
    can_share: StrictBool | None = None
    muted: StrictBool | None = None


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class RecordingInput(BaseModel):
    action: str = Field(pattern='^(start|stop|reconcile)$')


def course_view(db, row, user):
    return {**row, 'host_name': db.execute('SELECT username FROM users WHERE id=?', (row['host_id'],)).fetchone()[0],
            'can_manage': store.manage(row, user), 'is_host': row['host_id'] == user['id'],
            'member_ids': [item[0] for item in db.execute('SELECT user_id FROM live_members WHERE course_id=?', (row['id'],))],
            'lesson_count': db.execute('SELECT COUNT(*) FROM live_lessons WHERE course_id=?', (row['id'],)).fetchone()[0],
            'live_count': db.execute("SELECT COUNT(*) FROM live_lessons WHERE course_id=? AND status='live'", (row['id'],)).fetchone()[0]}


@router.get('/people')
def people(q: str = Query(default='', max_length=100), user=Depends(administrator)):
    with connect() as db:
        return [dict(row) for row in db.execute('''SELECT id,username FROM users WHERE is_active=1
            AND (is_admin=0 OR ?=1 OR id=?) AND instr(lower(username),lower(?))>0 ORDER BY username LIMIT 100''',
            (user['is_superadmin'], user['id'], q))]


@router.get('/courses')
def courses(user=Depends(current_user)):
    with connect() as db:
        rows = db.execute('''SELECT DISTINCT c.* FROM live_courses c LEFT JOIN live_members m ON m.course_id=c.id
            WHERE m.user_id=? OR c.host_id=? OR (?=1 AND (?=1 OR c.owner_id=?)) ORDER BY c.id DESC''',
            (user['id'], user['id'], user['is_admin'], user['is_superadmin'], user['id']))
        return {'items': [course_view(db, dict(row), user) for row in rows], 'configured': media.configured(),
                'max_participants': media.settings()['max_participants']}


def save_course(db, payload, user, cid=None):
    if not payload.title.strip():
        raise HTTPException(422, '请输入课程名称')
    store.validate_people(db, [payload.host_id, *payload.member_ids], user)
    if cid is None:
        cid = db.execute('INSERT INTO live_courses(title,description,host_id,owner_id) VALUES (?,?,?,?)',
                         (payload.title.strip(), payload.description, payload.host_id, user['id'])).lastrowid
    else:
        row = store.course(db, cid, user)
        if not store.manage(row, user):
            raise HTTPException(403, '需要课程管理权限')
        if db.execute("SELECT 1 FROM live_lessons WHERE course_id=? AND status='live'", (cid,)).fetchone():
            existing_members = {item[0] for item in db.execute(
                'SELECT user_id FROM live_members WHERE course_id=?', (cid,))}
            proposed_members = set([payload.host_id, *payload.member_ids])
            unchanged = (payload.title.strip() == row['title'] and payload.description == row['description'] and
                         payload.host_id == row['host_id'] and proposed_members == existing_members)
            if not unchanged:
                raise HTTPException(409, '直播期间不能修改课程信息、主持人或成员；如需保存，请保持当前设置不变')
            return course_view(db, row, user)
        db.execute('UPDATE live_courses SET title=?,description=?,host_id=? WHERE id=?',
                   (payload.title.strip(), payload.description, payload.host_id, cid))
        db.execute('DELETE FROM live_members WHERE course_id=?', (cid,))
    db.executemany('INSERT INTO live_members(course_id,user_id) VALUES (?,?)',
                   [(cid, uid) for uid in set([payload.host_id, *payload.member_ids])])
    return course_view(db, store.course(db, cid, user), user)


@router.post('/courses')
def create_course(payload: CourseInput, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return save_course(db, payload, user)


@router.patch('/courses/{cid}')
def update_course(cid: int, payload: CourseInput, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return save_course(db, payload, user, cid)


@router.get('/courses/{cid}')
def get_course(cid: int, user=Depends(current_user)):
    with connect() as db:
        row = store.course(db, cid, user)
        return {**course_view(db, row, user), 'lessons': [dict(item) for item in db.execute(
            'SELECT * FROM live_lessons WHERE course_id=? ORDER BY starts_at,id', (cid,))]}


@router.post('/courses/{cid}/lessons')
def create_lesson(cid: int, payload: LessonInput, user=Depends(administrator)):
    with connect() as db:
        parent = store.course(db, cid, user)
        if not store.manage(parent, user):
            raise HTTPException(403, '需要课程管理权限')
        section = db.execute('SELECT id FROM course_sections WHERE course_id=? ORDER BY position,id LIMIT 1', (cid,)).fetchone()
        if not section:
            section_id = db.execute("INSERT INTO course_sections(course_id,title,position) VALUES (?,'直播课程内容',0)", (cid,)).lastrowid
        else:
            section_id = section['id']
        position = db.execute('SELECT COUNT(*) FROM course_lessons WHERE section_id=?', (section_id,)).fetchone()[0]
        course_lesson_id = db.execute('''INSERT INTO course_lessons(course_id,section_id,title,description,position)
            VALUES (?,?,?,?,?)''', (cid, section_id, payload.title, payload.description, position)).lastrowid
        lid = db.execute('''INSERT INTO live_lessons(course_id,title,description,starts_at,course_lesson_id)
            VALUES (?,?,?,?,?)''', (cid, payload.title, payload.description, payload.starts_at, course_lesson_id)).lastrowid
        db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,live_lesson_id)
            VALUES (?,'live',0,?)''', (course_lesson_id, lid))
        row, parent = store.lesson(db, lid, user)
        return store.lesson_view(db, row, parent, user)


@router.patch('/lessons/{lid}')
def update_lesson(lid: int, payload: LessonInput, user=Depends(administrator)):
    with connect() as db:
        row, parent = store.lesson(db, lid, user, manager=True)
        if row['status'] == 'live':
            raise HTTPException(409, '直播期间不能修改课次')
        db.execute('UPDATE live_lessons SET title=?,description=?,starts_at=? WHERE id=?',
                   (payload.title, payload.description, payload.starts_at, lid))
        if row.get('course_lesson_id'):
            db.execute('UPDATE course_lessons SET title=?,description=? WHERE id=?',
                       (payload.title, payload.description, row['course_lesson_id']))
        row, parent = store.lesson(db, lid, user)
        return store.lesson_view(db, row, parent, user)


def deletion_files(db, entity, ident):
    condition = 'l.course_id=?' if entity == 'course' else 'l.id=?'
    return [(kind, row['path']) for table, kind in [('live_materials', 'materials'), ('live_recordings', 'recordings')]
            for row in db.execute(f'SELECT f.path FROM {table} f JOIN live_lessons l ON l.id=f.lesson_id WHERE {condition}', (ident,))]


def delete_files(files):
    for kind, name in files:
        try:
            private_path(kind, name).unlink(missing_ok=True)
        except OSError as error:
            raise HTTPException(503, '课程记录已删除，但私有文件清理失败，请联系管理员清理存储') from error


@router.delete('/courses/{cid}')
def delete_course(cid: int, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        parent = store.course(db, cid, user)
        if not store.manage(parent, user):
            raise HTTPException(403, '需要课程管理权限')
        if db.execute("SELECT 1 FROM live_lessons WHERE course_id=? AND status='live'", (cid,)).fetchone():
            raise HTTPException(409, '请先结束直播')
        files = deletion_files(db, 'course', cid)
        db.execute('DELETE FROM live_courses WHERE id=?', (cid,))
    delete_files(files)
    return {}


@router.delete('/lessons/{lid}')
def delete_lesson(lid: int, user=Depends(administrator)):
    with connect() as db:
        row, _ = store.lesson(db, lid, user, manager=True)
        if row['status'] == 'live':
            raise HTTPException(409, '请先结束直播')
        files = deletion_files(db, 'lesson', lid)
        course_lesson_id = row.get('course_lesson_id')
        section_id = db.execute('SELECT section_id FROM course_lessons WHERE id=?',
                                (course_lesson_id,)).fetchone() if course_lesson_id else None
        db.execute('DELETE FROM course_lessons WHERE id=?', (course_lesson_id,))
        db.execute('DELETE FROM live_lessons WHERE id=?', (lid,))
        if section_id:
            learning.compact_positions(db, 'course_lessons', 'section_id', section_id['section_id'])
    delete_files(files)
    return {}


@router.get('/lessons/{lid}')
def get_lesson(lid: int, user=Depends(current_user)):
    with connect() as db:
        row, parent = store.lesson(db, lid, user)
        return store.lesson_view(db, row, parent, user)


@router.post('/lessons/{lid}/start')
@serialized_media_write
async def start(lid: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, parent = store.lesson(db, lid, user, host=True)
        if row['status'] == 'ended':
            raise HTTPException(409, '已结束课次不能重新开始')
        await media.call('room', 'create_room', api.CreateRoomRequest(name=media.room(lid), max_participants=media.settings()['max_participants']))
        db.execute("UPDATE live_lessons SET status='live' WHERE id=?", (lid,))
        row['status'] = 'live'
        return store.lesson_view(db, row, parent, user)


@router.post('/lessons/{lid}/end')
@serialized_media_write
async def end(lid: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, parent = store.lesson(db, lid, user, host=True)
        store.require_live(row)
        await media.call('room', 'delete_room', api.DeleteRoomRequest(room=media.room(lid)))
        db.execute("UPDATE live_lessons SET status='ended' WHERE id=?", (lid,))
        db.execute('DELETE FROM live_presence WHERE lesson_id=?', (lid,))
        row['status'] = 'ended'
        return store.lesson_view(db, row, parent, user)


@router.post('/lessons/{lid}/join')
@serialized_media_write
async def join(lid: int, user=Depends(current_user)):
    media.require_configured()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, parent = store.lesson(db, lid, user)
        store.require_live(row)
        cutoff = time.time() - media.settings()['presence_seconds']
        # Expired reservations are removed from the SFU before their slots become reusable.
        expired = list(db.execute('SELECT user_id FROM live_presence WHERE lesson_id=? AND seen<?', (lid, cutoff)))
        for member in expired:
            try:
                await media.call('room', 'remove_participant', api.RoomParticipantIdentity(room=media.room(lid), identity=str(member['user_id'])))
            except HTTPException as error:
                if not isinstance(error.__cause__, api.TwirpError) or error.__cause__.code != 'not_found':
                    raise
        db.execute('DELETE FROM live_presence WHERE lesson_id=? AND seen<?', (lid, cutoff))
        old = db.execute('SELECT * FROM live_presence WHERE lesson_id=? AND user_id=?', (lid, user['id'])).fetchone()
        if not old and db.execute('SELECT COUNT(*) FROM live_presence WHERE lesson_id=?', (lid,)).fetchone()[0] >= media.settings()['max_participants']:
            raise HTTPException(409, '课堂人数已满，请稍后重试')
        host = parent['host_id'] == user['id']
        speak, share = (bool(old['can_speak']), bool(old['can_share'])) if old else (host, False)
        db.execute('''INSERT INTO live_presence(lesson_id,user_id,seen,can_speak,can_share,muted) VALUES (?,?,?,?,?,COALESCE((SELECT muted FROM live_moderation WHERE lesson_id=? AND user_id=?),0))
            ON CONFLICT(lesson_id,user_id) DO UPDATE SET seen=excluded.seen,muted=excluded.muted''', (lid, user['id'], time.time(), speak, share, lid, user['id']))
        return {'url': media.settings()['url'], 'token': media.token(lid, user, speak, share),
                'identity': str(user['id']), 'is_host': host, 'can_speak': speak, 'can_share': share,
                'screen_share': {key: media.settings()[f'screen_share_{key}']
                                 for key in ('width', 'height', 'frame_rate', 'max_bitrate')}}


def state_view(db, lid, user, after=0):
    row, parent = store.lesson(db, lid, user)
    members = [{**dict(item), **{key: bool(item[key]) for key in ('hand', 'request_share', 'can_speak', 'can_share', 'muted')},
                'is_host': item['user_id'] == parent['host_id']} for item in db.execute('''SELECT p.user_id,u.username,p.hand,p.request_share,p.can_speak,p.can_share,COALESCE((SELECT muted FROM live_moderation mod WHERE mod.lesson_id=p.lesson_id AND mod.user_id=p.user_id),0) AS muted
                FROM live_presence p JOIN users u ON u.id=p.user_id WHERE lesson_id=? AND seen>=? ORDER BY p.seen''',
                (lid, time.time() - media.settings()['presence_seconds']))]
    own = next((item for item in members if item['user_id'] == user['id']), {})
    return {'status': row['status'], 'messages': [dict(item) for item in db.execute('''SELECT m.id,m.user_id,u.username,m.content,m.created
        FROM live_messages m JOIN users u ON u.id=m.user_id WHERE lesson_id=? AND m.id>? ORDER BY m.id LIMIT 200''', (lid, after))],
        'members': members, 'likes': row['likes'], 'recording_status': store.recording_status(db, lid), 'muted': own.get('muted', False)}


@router.get('/lessons/{lid}/state')
def state(lid: int, after: int = Query(default=0, ge=0), user=Depends(current_user)):
    with connect() as db:
        return state_view(db, lid, user, after)


@router.post('/lessons/{lid}/presence')
def presence(lid: int, payload: PresenceInput, user=Depends(current_user)):
    with connect() as db:
        row, _ = store.lesson(db, lid, user)
        store.require_live(row)
        store.require_present(db, lid, user['id'])
        db.execute('UPDATE live_presence SET seen=? WHERE lesson_id=? AND user_id=?', (time.time(), lid, user['id']))
        for key, value in payload.model_dump(exclude_none=True).items():
            db.execute(f'UPDATE live_presence SET {key}=? WHERE lesson_id=? AND user_id=?', (value, lid, user['id']))
        return state_view(db, lid, user)


@router.post('/lessons/{lid}/leave')
@serialized_media_write
async def leave(lid: int, user=Depends(current_user)):
    with connect() as db:
        store.lesson(db, lid, user)
        if db.execute('SELECT 1 FROM live_presence WHERE lesson_id=? AND user_id=?', (lid, user['id'])).fetchone():
            try:
                await media.call('room', 'remove_participant', api.RoomParticipantIdentity(room=media.room(lid), identity=str(user['id'])))
            except HTTPException as error:
                if not isinstance(error.__cause__, api.TwirpError) or error.__cause__.code != 'not_found':
                    raise
            db.execute('DELETE FROM live_presence WHERE lesson_id=? AND user_id=?', (lid, user['id']))
    return {}


@router.post('/lessons/{lid}/messages')
def message(lid: int, payload: MessageInput, user=Depends(current_user)):
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, '评论不能为空')
    with connect() as db:
        row, _ = store.lesson(db, lid, user)
        store.require_live(row)
        own = store.require_present(db, lid, user['id'])
        moderation = db.execute('SELECT muted FROM live_moderation WHERE lesson_id=? AND user_id=?', (lid, user['id'])).fetchone()
        if moderation and moderation['muted']:
            raise HTTPException(403, '主持人已暂停你的评论权限')
        now = time.time()
        last = db.execute('SELECT MAX(created) FROM live_messages WHERE lesson_id=? AND user_id=?', (lid, user['id'])).fetchone()[0]
        if last and now - last < 1:
            raise HTTPException(429, '发送过于频繁，请稍后重试')
        mid = db.execute('INSERT INTO live_messages(lesson_id,user_id,content,created) VALUES (?,?,?,?)', (lid, user['id'], content, now)).lastrowid
        return {'id': mid, 'user_id': user['id'], 'username': user['username'], 'content': content, 'created': now}


@router.post('/lessons/{lid}/like')
def like(lid: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, _ = store.lesson(db, lid, user)
        store.require_live(row)
        store.require_present(db, lid, user['id'])
        now = time.time()
        previous = db.execute('SELECT created FROM live_likes WHERE lesson_id=? AND user_id=?', (lid, user['id'])).fetchone()
        if previous and now - previous['created'] < media.settings()['like_interval_seconds']:
            raise HTTPException(429, '点赞过于频繁，请稍后重试')
        db.execute('INSERT INTO live_likes VALUES (?,?,?) ON CONFLICT(lesson_id,user_id) DO UPDATE SET created=excluded.created', (lid, user['id'], now))
        db.execute('UPDATE live_lessons SET likes=likes+1 WHERE id=?', (lid,))
        return {'likes': db.execute('SELECT likes FROM live_lessons WHERE id=?', (lid,)).fetchone()[0]}


@router.patch('/lessons/{lid}/members/{uid}')
@serialized_media_write
async def grant(lid: int, uid: int, payload: GrantInput, user=Depends(current_user)):
    lock = _grant_locks.setdefault(lid, asyncio.Lock())
    async with lock:
        return await _grant(lid, uid, payload, user)


async def _grant(lid, uid, payload, user):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, _ = store.lesson(db, lid, user, host=True)
        store.require_live(row)
        target = store.require_present(db, lid, uid)
        changes = payload.model_dump(exclude_none=True)
        speak = changes.get('can_speak', bool(target['can_speak']))
        share = changes.get('can_share', bool(target['can_share']))
        if share:
            others = list(db.execute('SELECT * FROM live_presence WHERE lesson_id=? AND user_id<>? AND can_share=1', (lid, uid)))
            for other in others:
                await media.permission(lid, other['user_id'], bool(other['can_speak']), False)
                db.execute('UPDATE live_presence SET can_share=0 WHERE lesson_id=? AND user_id=?', (lid, other['user_id']))

        if 'can_speak' in changes or 'can_share' in changes:
            try:
                await media.permission(lid, uid, speak, share)
            except HTTPException:
                # Preserve successful prior revocations while releasing the same write lock.
                db.commit()
                raise
        if 'muted' in changes:
            db.execute('INSERT INTO live_moderation VALUES (?,?,?) ON CONFLICT(lesson_id,user_id) DO UPDATE SET muted=excluded.muted', (lid, uid, changes['muted']))
        for key, value in changes.items():
            db.execute(f'UPDATE live_presence SET {key}=? WHERE lesson_id=? AND user_id=?', (value, lid, uid))
        return dict(db.execute('SELECT * FROM live_presence WHERE lesson_id=? AND user_id=?', (lid, uid)).fetchone())


def private_path(kind, name):
    base = Path(media.settings()['directory']).resolve() / kind
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = (base / name).resolve()
    if candidate.parent != base or not name:
        raise HTTPException(404, '文件不存在')
    return candidate


@router.post('/lessons/{lid}/materials')
@serialized_media_write
async def upload_material(lid: int, file: UploadFile = File(), user=Depends(current_user)):
    with connect() as db:
        _, parent = store.lesson(db, lid, user)
        if parent['host_id'] != user['id'] and not store.manage(parent, user):
            raise HTTPException(403, '仅主持人或管理员可以上传资料')
        name = Path((file.filename or '').replace('\\', '/')).name
        allowed = {'.pdf', '.txt', '.md', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.png', '.jpg', '.jpeg', '.zip'}
        if Path(name).suffix.lower() not in allowed or len(name) > 200:
            raise HTTPException(422, '不支持此文件类型，请使用文档、图片或 ZIP 文件')
        path = private_path('materials', secrets.token_hex(24))
        size = 0
        try:
            with path.open('xb') as output:
                path.chmod(0o600)
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > media.settings()['material_max_mb'] * 1024 * 1024:
                        raise HTTPException(413, '资料超过大小限制')
                    output.write(chunk)
            if not size:
                raise HTTPException(422, '不能上传空文件')
            mid = db.execute('INSERT INTO live_materials(lesson_id,name,path,size) VALUES (?,?,?,?)',
                             (lid, name, path.name, size)).lastrowid
        except (OSError, HTTPException):
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {'id': mid, 'name': name, 'size': size}


@router.get('/materials/{mid}/file')
def material_file(mid: int, user=Depends(current_user)):
    with connect() as db:
        row = db.execute('SELECT * FROM live_materials WHERE id=?', (mid,)).fetchone()
        if not row:
            raise HTTPException(404, '资料不存在')
        store.lesson(db, row['lesson_id'], user)
        path = private_path('materials', row['path'])
        if not path.is_file():
            raise HTTPException(404, '资料文件不可用，请联系主持人')
        return FileResponse(path, filename=row['name'], media_type='application/octet-stream',
                            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.delete('/materials/{mid}')
def delete_material(mid: int, user=Depends(current_user)):
    with connect() as db:
        row = db.execute('SELECT * FROM live_materials WHERE id=?', (mid,)).fetchone()
        if not row:
            raise HTTPException(404, '资料不存在')
        _, parent = store.lesson(db, row['lesson_id'], user)
        if parent['host_id'] != user['id'] and not store.manage(parent, user):
            raise HTTPException(403, '需要课程资料管理权限')
        private_path('materials', row['path']).unlink(missing_ok=True)
        db.execute('DELETE FROM live_materials WHERE id=?', (mid,))
    return {}


@router.post('/lessons/{lid}/recording')
@serialized_media_write
async def recording(lid: int, payload: RecordingInput, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row, _ = store.lesson(db, lid, user, host=True)
        if payload.action != 'reconcile':
            store.require_live(row)
        if not media.settings()['recording_enabled']:
            raise HTTPException(503, '录制尚未配置，请联系管理员部署 Egress 和共享私有存储')
        media.require_configured()
        active = db.execute("SELECT * FROM live_recordings WHERE lesson_id=? AND status IN ('starting','recording','stopping','unknown') ORDER BY id DESC LIMIT 1", (lid,)).fetchone()
        if payload.action == 'reconcile':
            if not active:
                return {'status': store.recording_status(db, lid)}
            response = await media.call('egress', 'list_egress', api.ListEgressRequest(room_name=media.room(lid)))
            expected = str(Path(media.settings()['egress_directory']) / active['path'])
            match = None
            for info in response.items:
                requested = list(info.room_composite.file_outputs)
                if info.egress_id == active['egress_id'] or any(output.filepath == expected for output in requested) or any(result.filename == expected for result in info.file_results):
                    match = info
                    break
            if match is None:
                raise HTTPException(409, 'Egress 尚未确认此录制；不能安全重试，请检查服务日志和任务历史')
            status_name = api.EgressStatus.Name(match.status)
            if status_name == 'EGRESS_COMPLETE':
                status = 'ready' if private_path('recordings', active['path']).is_file() else 'failed'
                error = '' if status == 'ready' else '录制结束但私有文件不可用，请检查共享目录'
            elif status_name in ('EGRESS_FAILED', 'EGRESS_ABORTED', 'EGRESS_LIMIT_REACHED'):
                status, error = 'failed', match.error or 'Egress 录制失败，可重新开始'
            else:
                status, error = ('stopping' if status_name == 'EGRESS_ENDING' else 'recording'), ''
            db.execute('UPDATE live_recordings SET egress_id=?,status=?,error=? WHERE id=?', (match.egress_id, status, error, active['id']))
            return {'status': status}
        if payload.action == 'stop':
            if not active:
                return {'status': store.recording_status(db, lid)}
            if not active['egress_id']:
                raise HTTPException(409, '录制启动状态尚未确认，请检查 Egress 后重试')
            try:
                await media.call('egress', 'stop_egress', api.StopEgressRequest(egress_id=active['egress_id']))
            except HTTPException:
                db.execute("UPDATE live_recordings SET error='停止录制失败，请检查 Egress 后重试' WHERE id=?", (active['id'],))
                db.commit()
                raise
            db.execute("UPDATE live_recordings SET status='stopping',error='' WHERE id=?", (active['id'],))
            return {'status': 'stopping'}
        if active:
            return {'status': active['status']}
        filename = secrets.token_hex(24) + '.mp4'
        private_path('recordings', filename)
        rid = db.execute("INSERT INTO live_recordings(lesson_id,status,path) VALUES (?,'starting',?)", (lid, filename)).lastrowid
        # Persist intent before remote work: an interrupted request must not silently start a second recorder.
        db.commit()
        try:
            result = await media.call('egress', 'start_room_composite_egress', api.RoomCompositeEgressRequest(
                room_name=media.room(lid), layout='grid',
                advanced=api.EncodingOptions(
                    width=media.settings()['recording_width'],
                    height=media.settings()['recording_height'],
                    framerate=media.settings()['recording_frame_rate'],
                    video_bitrate=media.settings()['recording_video_bitrate'],
                    audio_bitrate=media.settings()['recording_audio_bitrate']),
                file_outputs=[api.EncodedFileOutput(
                    file_type=api.EncodedFileType.MP4, filepath=str(Path(media.settings()['egress_directory']) / filename))]))
        except HTTPException as error:
            status = 'failed' if isinstance(error.__cause__, api.TwirpError) else 'unknown'
            db.execute("UPDATE live_recordings SET status=?,error='Egress 启动失败或结果未确认，请检查服务日志后重试' WHERE id=?", (status, rid))
            db.commit()
            raise
        db.execute('UPDATE live_recordings SET egress_id=? WHERE id=?', (result.egress_id, rid))
        return {'status': 'starting'}


@router.post('/webhook')
@serialized_media_write
async def webhook(request: Request):
    media.require_configured()
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(413, '事件过大')
    key, secret = media.credentials()
    try:
        event = api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(body.decode('utf-8'), request.headers.get('authorization', ''))
    except Exception as error:
        # SDK raises generic Exception for invalid body hashes; all verification errors reject the event.
        raise HTTPException(401, 'LiveKit 事件签名无效') from error
    if not event.id or abs(time.time() - event.created_at) > 86400:
        raise HTTPException(400, '事件缺少标识或已经过期')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM live_webhooks WHERE id=?', (event.id,)).fetchone():
            return {}
        if event.event == 'participant_joined' and not event.participant.permission.recorder:
            room_name = event.room.name
            try:
                lid = int(room_name.removeprefix('classroom-')) if room_name.startswith('classroom-') else None
                uid = int(event.participant.identity)
            except ValueError:
                lid, uid = None, None
            if lid is not None:
                admitted = db.execute('''SELECT p.*,c.host_id FROM live_presence p
                    JOIN live_lessons l ON l.id=p.lesson_id JOIN live_courses c ON c.id=l.course_id
                    JOIN users u ON u.id=p.user_id
                    WHERE p.lesson_id=? AND p.user_id=? AND l.status='live' AND c.publication_status='published' AND u.is_active=1
                    AND p.seen>=? AND (c.host_id=p.user_id OR EXISTS(
                        SELECT 1 FROM live_members m WHERE m.course_id=c.id AND m.user_id=p.user_id))''',
                    (lid, uid, time.time()-media.settings()['presence_seconds'])).fetchone()
                if not admitted:
                    await media.call('room', 'remove_participant', api.RoomParticipantIdentity(room=room_name, identity=event.participant.identity))
                else:
                    # Reconcile reconnects carrying a previously issued token with current grants.
                    await media.permission(lid, uid, bool(admitted['can_speak']), bool(admitted['can_share']))
        if event.event in ('egress_started', 'egress_updated', 'egress_ended'):
            info = event.egress_info
            row = db.execute('SELECT * FROM live_recordings WHERE egress_id=?', (info.egress_id,)).fetchone()
            if not row:
                for result in info.file_results:
                    candidate = db.execute("SELECT * FROM live_recordings WHERE path=? AND egress_id IS NULL AND status IN ('starting','unknown')", (Path(result.filename).name,)).fetchone()
                    if candidate and result.filename == str(Path(media.settings()['egress_directory']) / candidate['path']):
                        row = candidate
                        db.execute('UPDATE live_recordings SET egress_id=? WHERE id=?', (info.egress_id, row['id']))
                        break
            if row:
                status_name = api.EgressStatus.Name(info.status)
                if status_name == 'EGRESS_COMPLETE':
                    expected = str(Path(media.settings()['egress_directory']) / row['path'])
                    matching = any(item.filename == expected and item.size > 0 for item in info.file_results)
                    ready = matching and private_path('recordings', row['path']).is_file()
                    status, error = ('ready', '') if ready else ('failed', '录制结束但私有视频文件尚不可用，请检查 Egress 共享目录')
                elif status_name in ('EGRESS_FAILED', 'EGRESS_ABORTED', 'EGRESS_LIMIT_REACHED'):
                    status, error = 'failed', info.error or 'Egress 录制失败'
                elif status_name == 'EGRESS_ACTIVE':
                    status, error = 'recording', ''
                elif status_name == 'EGRESS_ENDING':
                    status, error = 'stopping', ''
                else:
                    status, error = 'starting', ''
                if row['status'] not in ('ready', 'failed') and not (row['status'] == 'stopping' and status in ('starting', 'recording')):
                    db.execute('UPDATE live_recordings SET status=?,error=? WHERE id=?', (status, error, row['id']))
        db.execute('INSERT INTO live_webhooks VALUES (?,?)', (event.id, time.time()))
    return {}


def recording_row(db, rid, user):
    row = db.execute('SELECT * FROM live_recordings WHERE id=?', (rid,)).fetchone()
    if not row:
        raise HTTPException(404, '录播不存在')
    store.lesson(db, row['lesson_id'], user)
    if row['status'] != 'ready':
        raise HTTPException(409, '录播尚不可播放')
    return row


@router.post('/recordings/{rid}/playback')
def playback(rid: int, user=Depends(current_user)):
    with connect() as db:
        recording_row(db, rid, user)
        ticket = secrets.token_urlsafe(32)
        db.execute('DELETE FROM live_playback WHERE expires<?', (time.time(),))
        expires_in = media.settings()['playback_seconds']
        expires_at = time.time() + expires_in
        db.execute('INSERT INTO live_playback VALUES (?,?,?,?)', (hashlib.sha256(ticket.encode()).hexdigest(), rid,
                    user['id'], expires_at))
        return {'url': f'/api/live/recordings/{rid}/file?ticket={ticket}', 'expires_at': expires_at, 'expires_in': expires_in}


@router.get('/recordings/{rid}/file')
def recording_file(rid: int, request: Request, ticket: str | None = None):
    with connect() as db:
        if ticket:
            user = db.execute('''SELECT u.* FROM live_playback p JOIN users u ON u.id=p.user_id
                WHERE p.token=? AND p.recording_id=? AND p.expires>? AND u.is_active=1''',
                (hashlib.sha256(ticket.encode()).hexdigest(), rid, time.time())).fetchone()
            if not user:
                raise HTTPException(401, '播放链接已过期，请重新打开录播')
        else:
            user = current_user(request.headers.get('authorization'))
        row = recording_row(db, rid, user)
        path = private_path('recordings', row['path'])
        if not path.is_file():
            raise HTTPException(404, '录播文件不可用，请联系管理员')
        return FileResponse(path, media_type='video/mp4', headers={'Cache-Control': 'private, no-store',
            'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})
