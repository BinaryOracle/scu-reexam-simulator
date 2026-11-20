"""Learner catalog, administrator editing and authenticated course media."""
import asyncio
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal
from anyio import CancelScope
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect
from app.config import load_config
from app.db import connect
from app.services.auth import administrator, current_user
from app.services import courses as storage

router = APIRouter()
admin = APIRouter(prefix='/api/admin/courses', dependencies=[Depends(administrator)])
catalog = APIRouter(prefix='/api/courses', dependencies=[Depends(current_user)])
MEDIA = '/api/course-media'
MEDIA_COOKIE = 'scu_course_media'
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CourseInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Title
    description: str = Field(default='', max_length=4000)
    published: bool = False


class CourseAccess(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['all', 'restricted']
    learner_ids: list[Annotated[int, Field(strict=True, gt=0, le=2**63-1)]] = Field(default_factory=list, max_length=5000)


class LessonInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    title: Title
    description: str = Field(default='', max_length=4000)
    position: int = Field(default=1, ge=1, le=10000)
    live_start: float | None = None
    live_end: float | None = None

    @model_validator(mode='after')
    def check_schedule(self):
        if self.live_start is None and self.live_end is None:
            return self
        window = load_config()['courses']['max_live_minutes']
        if (self.live_start is None or self.live_end is None
                or not 0 < self.live_start < self.live_end < 253402300800
                or self.live_end - self.live_start > window * 60):
            raise ValueError(f'请设置有效的直播开始、结束时间，时长不超过 {window} 分钟')
        return self


def course_list(*, viewer=None):
    where, args = ('', ()) if viewer is None else (f'WHERE {storage.VISIBLE}', (viewer['is_admin'], viewer['id']))
    with connect() as db:
        rows = db.execute(f'''
            SELECT c.*,COUNT(l.id) AS lesson_count FROM courses c
            LEFT JOIN course_lessons l ON l.course_id=c.id {where} GROUP BY c.id ORDER BY c.id DESC''', args)
        return [course_metadata(row, manage=viewer is None) for row in rows]


def course_metadata(row, *, manage):
    item = {**dict(row), 'published': bool(row['published'])}
    if not manage:
        item.pop('access_mode', None)
    return item


@catalog.get('')
def learner_list(response: Response, user=Depends(current_user)):
    response.headers.update(storage.PRIVATE)
    return course_list(viewer=user)


@admin.get('')
def admin_list():
    return course_list()


def course_detail(cid, *, viewer=None):
    root, now = storage.file_root(), time.time()
    with connect() as db:
        item = storage.course(db, cid) if viewer is None else storage.visible_course(db, cid, viewer)
        storage.recover(db, root, now)
        return course_metadata(storage.payload(db, item, root, now), manage=viewer is None)


@catalog.get('/{cid}')
def learner_detail(cid: int, response: Response, user=Depends(current_user)):
    response.headers.update(storage.PRIVATE)
    return course_detail(cid, viewer=user)


@admin.get('/{cid}')
def admin_detail(cid: int):
    return course_detail(cid)


@admin.get('/{cid}/access')
def get_course_access(cid: int, response: Response):
    response.headers.update(storage.PRIVATE)
    with connect() as db:
        db.execute('BEGIN')
        item = storage.course(db, cid)
        learners = [dict(row) for row in db.execute('''
            SELECT u.id,u.username,u.email,u.is_active,(a.user_id IS NOT NULL) AS selected
            FROM users u LEFT JOIN course_learners a ON a.user_id=u.id AND a.course_id=?
            WHERE u.is_admin=0 ORDER BY u.username COLLATE NOCASE,u.id''', (cid,))]
        return {'mode': item['access_mode'], 'learners': learners}


@admin.put('/{cid}/access', status_code=204)
def set_course_access(cid: int, data: CourseAccess):
    learners = set(data.learner_ids)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        storage.course(db, cid)
        if learners:
            # Read in bounded batches for SQLite builds with a low parameter limit.
            ids = sorted(learners)
            for i in range(0, len(ids), 500):
                batch = ids[i:i+500]
                marks = ','.join('?' for _ in batch)
                count = db.execute(f'SELECT COUNT(*) FROM users WHERE is_admin=0 AND id IN ({marks})',
                                   batch).fetchone()[0]
                if count != len(batch):
                    raise HTTPException(409, '学员名单已变化，请重新加载后再保存')
        db.execute('UPDATE courses SET access_mode=? WHERE id=?', (data.mode, cid))
        db.execute('DELETE FROM course_learners WHERE course_id=?', (cid,))
        db.executemany('INSERT INTO course_learners(course_id,user_id) VALUES (?,?)',
                       ((cid, uid) for uid in learners))


@admin.post('', status_code=201)
def create_course(data: CourseInput):
    with connect() as db:
        cid = db.execute("INSERT INTO courses(title,description,published,access_mode) VALUES (?,?,?,'restricted')",
                         (data.title, data.description.strip(), data.published)).lastrowid
    return {'id': cid}


@admin.put('/{cid}')
def edit_course(cid: int, data: CourseInput):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        storage.course(db, cid)
        if not data.published:
            storage.recover(db, storage.file_root(), time.time())
            storage.require_idle(db, cid)
        db.execute('UPDATE courses SET title=?,description=?,published=? WHERE id=?',
                   (data.title, data.description.strip(), data.published, cid))
    return {'id': cid}


def delete_course_or_lesson(cid, lid=None):
    root = storage.file_root()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        storage.course(db, cid)
        if lid is not None:
            storage.lesson(db, cid, lid)
        storage.recover(db, root, time.time())
        storage.require_idle(db, cid, lid)
        clause, args = ('course_id=?', (cid,)) if lid is None else ('id=?', (lid,))
        linked = f' WHERE lesson_id IN (SELECT id FROM course_lessons WHERE {clause})'
        files = [row[0] for row in db.execute('SELECT id FROM course_files' + linked, args)]
        broadcasts = [row[0] for row in db.execute('SELECT id FROM course_broadcasts' + linked, args)]
        if lid is None:
            db.execute('DELETE FROM courses WHERE id=?', (cid,))
        else:
            db.execute('DELETE FROM course_lessons WHERE id=?', (lid,))
    storage.remove_media(root, files, broadcasts)
    return Response(status_code=204)


@admin.delete('/{cid}', status_code=204)
def delete_course(cid: int):
    return delete_course_or_lesson(cid)


@admin.post('/{cid}/lessons', status_code=201)
def create_lesson(cid: int, data: LessonInput):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        storage.course(db, cid)
        lid = db.execute('''INSERT INTO course_lessons(course_id,title,description,position,live_start,live_end)
            VALUES (?,?,?,?,?,?)''', (cid, data.title, data.description.strip(), data.position,
                                     data.live_start, data.live_end)).lastrowid
    return {'id': lid}


@admin.put('/{cid}/lessons/{lid}')
def edit_lesson(cid: int, lid: int, data: LessonInput):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = storage.lesson(db, cid, lid)
        if (previous['live_start'], previous['live_end']) != (data.live_start, data.live_end):
            storage.recover(db, storage.file_root(), time.time())
            storage.require_idle(db, cid, lid)
        db.execute('''UPDATE course_lessons SET title=?,description=?,position=?,live_start=?,live_end=? WHERE id=?''',
                   (data.title, data.description.strip(), data.position, data.live_start, data.live_end, lid))
    return {'id': lid}


@admin.delete('/{cid}/lessons/{lid}', status_code=204)
def delete_lesson(cid: int, lid: int):
    return delete_course_or_lesson(cid, lid)


@admin.put('/{cid}/lessons/{lid}/files/{kind}', status_code=201)
async def upload_file(cid: int, lid: int, kind: str, request: Request,
                      name: str = Query(min_length=1, max_length=255)):
    if kind not in ('material', 'video'):
        raise HTTPException(404, '文件类型不存在')
    name = ''.join(char for char in name.replace('\\', '/').split('/')[-1] if char.isprintable()).strip()
    if not name or name in ('.', '..'):
        raise HTTPException(400, '文件名无效')
    extension = Path(name).suffix.lower()
    mime = 'application/octet-stream'
    config = load_config()['courses']
    limit_mb = config['max_material_mb']
    if kind == 'video':
        mime = {'.mp4': 'video/mp4', '.webm': 'video/webm'}.get(extension)
        if not mime:
            raise HTTPException(415, '录播请上传 MP4 或 WebM 视频')
        limit_mb = config['max_video_mb']
    limit = limit_mb * 1024 * 1024
    declared = request.headers.get('content-length')
    too_large = HTTPException(413, f'文件超过 {limit_mb} MB 上传上限')
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    with connect() as db:
        storage.lesson(db, cid, lid)
    directory = Path(config['directory']) / 'files'
    directory.mkdir(parents=True, exist_ok=True)
    fid, size = uuid.uuid4().hex, 0
    path = directory / fid
    prefix = bytearray()
    saved = False
    try:
        with path.open('xb') as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise too_large
                if len(prefix) < 12:
                    prefix.extend(chunk[:12 - len(prefix)])
                await run_in_threadpool(out.write, chunk)
        if not size:
            raise HTTPException(400, '不能上传空文件')
        if kind == 'video' and not (prefix[4:8] == b'ftyp' if extension == '.mp4'
                                    else prefix.startswith(b'\x1a\x45\xdf\xa3')):
            raise HTTPException(415, '文件内容与视频格式不匹配')
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            storage.lesson(db, cid, lid)
            db.execute('INSERT INTO course_files VALUES (?,?,?,?,?,?,?)',
                       (fid, lid, kind, name, mime, size, time.time()))
        saved = True
    finally:
        if not saved:
            path.unlink(missing_ok=True)
    return {'id': fid}


def delete_media(cid, lid, fid='', bid=''):
    root = storage.file_root()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        storage.lesson(db, cid, lid)
        if fid:
            count = db.execute('DELETE FROM course_files WHERE id=? AND lesson_id=?', (fid, lid)).rowcount
        else:
            storage.recover(db, root, time.time())
            count = db.execute("DELETE FROM course_broadcasts WHERE id=? AND lesson_id=? AND state!='recording'",
                               (bid, lid)).rowcount
        if not count:
            raise HTTPException(404, '文件不存在或直播尚未结束')
    storage.remove_media(root, [fid] if fid else [], [bid] if bid else [])
    return Response(status_code=204)


@admin.delete('/{cid}/lessons/{lid}/files/{fid}', status_code=204)
def delete_file(cid: int, lid: int, fid: str):
    return delete_media(cid, lid, fid=fid)


@admin.delete('/{cid}/lessons/{lid}/replays/{bid}', status_code=204)
def delete_replay(cid: int, lid: int, bid: str):
    return delete_media(cid, lid, bid=bid)


@catalog.post('/media-access', status_code=204)
def media_access(request: Request, authorization: str = Header()):
    # Native video and playlist segment requests cannot set the application's Bearer header.
    response = Response(status_code=204, headers=storage.PRIVATE)
    response.set_cookie(MEDIA_COOKIE, authorization[7:], path=MEDIA, httponly=True,
                        samesite='strict', secure=request.url.scheme == 'https')
    return response


def media_user(request: Request):
    token = request.cookies.get(MEDIA_COOKIE)
    return current_user(request.headers.get('Authorization') or (f'Bearer {token}' if token else None))


@router.get(MEDIA + '/{cid}/files/{fid}')
def file_content(cid: int, fid: str, user=Depends(media_user)):
    with connect() as db:
        storage.visible_course(db, cid, user, preview=True)
        row = db.execute('''SELECT f.* FROM course_files f JOIN course_lessons l ON l.id=f.lesson_id
            WHERE l.course_id=? AND f.id=?''', (cid, fid)).fetchone()
    if row is None:
        raise HTTPException(404, '文件不存在')
    path = storage.file_root() / 'files' / row['id']
    if not path.is_file():
        raise HTTPException(404, '文件不存在')
    return FileResponse(path, media_type=row['mime'], filename=row['name'], headers=storage.PRIVATE,
                        content_disposition_type='attachment' if row['kind'] == 'material' else 'inline')


@router.get(MEDIA + '/{cid}/live/{bid}/{name}')
def stream_content(cid: int, bid: str, name: str, user=Depends(media_user)):
    if name != 'index.m3u8' and not storage.SEGMENT.fullmatch(name):
        raise HTTPException(404, '视频片段不存在')
    root = storage.file_root()
    with connect() as db:
        item = storage.visible_course(db, cid, user, preview=True)
        storage.recover(db, root, time.time())
        row = db.execute('''SELECT b.* FROM course_broadcasts b JOIN course_lessons l ON l.id=b.lesson_id
            WHERE l.course_id=? AND b.id=?''', (cid, bid)).fetchone()
    if row is None or row['state'] == 'failed' or (row['state'] == 'recording' and not item['published']):
        raise HTTPException(404, '视频不存在')
    path = root / 'live' / row['id']
    if name == 'index.m3u8':
        playlist = storage.manifest(path)
        if playlist is None:
            raise HTTPException(404, '直播画面尚未就绪')
        if row['state'] == 'ready' and '#EXT-X-ENDLIST' not in playlist:
            playlist = playlist.rstrip() + '\n#EXT-X-ENDLIST\n'
        return Response(playlist, media_type='application/vnd.apple.mpegurl', headers=storage.PRIVATE)
    if not (path / name).is_file():
        raise HTTPException(404, '视频片段不存在')
    return FileResponse(path / name, media_type='video/mp2t', headers=storage.PRIVATE)


@router.websocket(MEDIA + '/{cid}/lessons/{lid}/publish')
async def broadcast(socket: WebSocket, cid: int, lid: int):
    scheme = 'https' if socket.url.scheme == 'wss' else 'http'
    if socket.headers.get('origin') != f"{scheme}://{socket.headers.get('host')}":
        await socket.close(code=1008)
        return
    token = socket.cookies.get(MEDIA_COOKIE)
    await socket.accept()
    try:
        bid, root, encoder, end = await run_in_threadpool(storage.reserve_broadcast, cid, lid, token)
    except HTTPException as error:
        try:
            await socket.send_json({'error': error.detail})
            await socket.close(code=1008)
        except (OSError, WebSocketDisconnect):
            pass
        return
    process = None
    disconnected = False
    blocked = False
    try:
        process = await run_in_threadpool(storage.start_encoder, encoder, root / 'live' / bid)
        await socket.send_json({'ready': True, 'ends_at': end})
        renew_after = time.monotonic() + 5
        flush_until = None
        while True:
            now = time.time()
            if now >= end and flush_until is None:
                # Ask the recorder to flush its last slice before forcing EOF.
                await socket.send_json({'stop': True})
                flush_until = end + 4
            remaining = (flush_until if flush_until is not None else end) - now
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(socket.receive(), timeout=min(remaining, 16))
            except TimeoutError:
                if flush_until is None and time.time() >= end:
                    continue
                break
            if message['type'] == 'websocket.disconnect':
                disconnected = True
                break
            if message.get('text') == 'finish':
                break
            chunk = message.get('bytes')
            if not chunk or len(chunk) > 4 * 1024 * 1024:
                raise HTTPException(400, '直播上传片段无效或过大')
            if time.monotonic() >= renew_after:
                await run_in_threadpool(storage.renew_broadcast, bid, token)
                renew_after = time.monotonic() + 5
            try:
                await asyncio.wait_for(asyncio.to_thread(storage.write_chunk, process, chunk), timeout=10)
            except TimeoutError:
                blocked = True
                raise HTTPException(503, '直播编码超时，已保存可用片段')
    except WebSocketDisconnect:
        disconnected = True
    except (HTTPException, OSError) as error:
        if not disconnected:
            try:
                await socket.send_json({'error': error.detail if isinstance(error, HTTPException)
                                        else '直播编码或连接中断，正在保存可用片段'})
            except (OSError, WebSocketDisconnect):
                disconnected = True
    finally:
        with CancelScope(shield=True):
            if process is not None:
                await run_in_threadpool(storage.stop_encoder, process, kill=blocked)
            state = await run_in_threadpool(storage.finish_broadcast, bid, root)
    if not disconnected:
        try:
            await socket.send_json({'finished': True, 'replay_saved': state == 'ready'})
            await socket.close()
        except (OSError, WebSocketDisconnect):
            pass


router.include_router(admin)
router.include_router(catalog)
