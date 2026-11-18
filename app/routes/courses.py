"""Authenticated course catalog, authoring, enrollment, and learner progress API."""
import secrets
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt, ConfigDict
from app.db import connect
from app.config import load_config
from app.services.auth import current_user, administrator
from app.services import course_learning as courses
from app.services import live

router = APIRouter(prefix='/api/courses', tags=['courses'])
DOCUMENT_TYPES = {'.pdf': 'application/pdf', '.txt': 'text/plain', '.md': 'text/markdown',
                  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
VIDEO_TYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm'}


class CourseWrite(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)
    publication_status: str = Field(default='draft', pattern='^(draft|published|archived)$')
    access_mode: str = Field(default='roster', pattern='^(public|roster)$')
    host_id: StrictInt | None = Field(default=None, gt=0)
    member_ids: list[StrictInt] = Field(default_factory=list, max_length=1000)


class NamedPosition(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    position: StrictInt = Field(ge=0, le=10000)


class LessonWrite(NamedPosition):
    description: str = Field(default='', max_length=4000)


class CourseItem(BaseModel):
    id: StrictInt | None = Field(default=None, gt=0)
    kind: str = Field(pattern='^(live|video|document)$')
    live_lesson_id: StrictInt | None = Field(default=None, gt=0)


class ItemOrder(BaseModel):
    items: list[CourseItem] = Field(max_length=100)


class IdOrder(BaseModel):
    ids: list[StrictInt] = Field(max_length=1000)


class ProgressWrite(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    position_seconds: float = Field(default=0, ge=0, le=864000)
    completed: StrictBool = False


class LiveSessionWrite(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    starts_at: float = Field(ge=0, le=4102444800)


class LiveCourseUnitWrite(LessonWrite):
    starts_at: float = Field(ge=0, le=4102444800)


def asset_path(name):
    base = Path(load_config()['course_media']['directory']).resolve() / 'assets'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = (base / name).resolve()
    if path.parent != base or not name:
        raise HTTPException(404, '课程文件不存在')
    return path


def _course_row(db, course_id):
    row = db.execute('''SELECT c.*,u.username AS host_name FROM live_courses c
        JOIN users u ON u.id=c.host_id WHERE c.id=?''', (course_id,)).fetchone()
    return dict(row) if row else None


def _save_course(db, payload, user, course_id=None):
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, '请输入课程名称')
    host_id = payload.host_id or user['id']
    live.validate_people(db, [host_id, *payload.member_ids], user)
    if course_id is None:
        course_id = db.execute('''INSERT INTO live_courses(title,description,host_id,owner_id,publication_status,access_mode)
            VALUES (?,?,?,?,?,?)''', (title, payload.description.strip(), host_id, user['id'],
                                      payload.publication_status, payload.access_mode)).lastrowid
        db.execute("INSERT INTO course_sections(course_id,title,position) VALUES (?,'第一章',0)", (course_id,))
    else:
        course = courses.require_access(db, course_id, user, manager=True)
        if db.execute("SELECT 1 FROM live_lessons WHERE course_id=? AND status='live'", (course_id,)).fetchone():
            raise HTTPException(409, '直播期间不能修改课程主持人或成员')
        db.execute('''UPDATE live_courses SET title=?,description=?,host_id=?,publication_status=?,access_mode=?
            WHERE id=?''', (title, payload.description.strip(), host_id, payload.publication_status,
                            payload.access_mode, course_id))
        db.execute('DELETE FROM live_members WHERE course_id=?', (course_id,))
        # Self-enrolled users are never converted into assigned roster members.
        if payload.access_mode == 'roster':
            db.execute('''DELETE FROM course_self_enrollments WHERE course_id=?''', (course_id,))
    db.executemany('INSERT INTO live_members(course_id,user_id) VALUES (?,?)',
                   [(course_id, uid) for uid in set([host_id, *payload.member_ids])])
    return _course_row(db, course_id)


def _apply_positions(db, table, parent_column, parent_id, ids):
    rows = [row['id'] for row in db.execute(
        f'SELECT id FROM {table} WHERE {parent_column}=? ORDER BY position,id', (parent_id,))]
    if len(ids) != len(set(ids)) or set(ids) != set(rows):
        raise HTTPException(422, '排序必须包含当前课程中的全部项目')
    offset = db.execute(f'SELECT COALESCE(MAX(position),-1)+? FROM {table} WHERE {parent_column}=?',
                        (len(ids) + 1, parent_id)).fetchone()[0]
    db.execute(f'UPDATE {table} SET position=position+? WHERE {parent_column}=?', (offset, parent_id))
    for position, item_id in enumerate(ids):
        db.execute(f'UPDATE {table} SET position=? WHERE id=?', (position, item_id))


@router.get('')
def catalog(scope: str = Query(default='mine', pattern='^(mine|public|managed)$'),
            q: str = Query(default='', max_length=100), user=Depends(current_user)):
    with connect() as db:
        if scope == 'public':
            rows = db.execute('''SELECT c.id,c.title,c.description,c.publication_status,c.access_mode,
                u.username host_name FROM live_courses c JOIN users u ON u.id=c.host_id
                WHERE c.publication_status='published' AND c.access_mode='public'
                AND instr(lower(c.title),lower(?))>0 ORDER BY c.id DESC''', (q.strip(),)).fetchall()
        elif scope == 'mine':
            rows = db.execute('''SELECT DISTINCT c.*,u.username host_name FROM live_courses c
                JOIN users u ON u.id=c.host_id LEFT JOIN live_members m ON m.course_id=c.id
                LEFT JOIN course_self_enrollments e ON e.course_id=c.id
                WHERE (e.user_id=? OR (m.user_id=? AND c.host_id<>?
                    AND NOT (?=1 AND (?=1 OR c.owner_id=?))))
                AND c.publication_status='published'
                AND instr(lower(c.title),lower(?))>0
                ORDER BY COALESCE((SELECT MAX(p.updated) FROM course_progress p
                    JOIN course_lessons l ON l.id=p.lesson_id WHERE l.course_id=c.id AND p.user_id=?),0) DESC,c.id DESC''',
                (user['id'], user['id'], user['id'], user['is_admin'], user['is_superadmin'], user['id'],
                 q.strip(), user['id'])).fetchall()
        else:
            rows = db.execute('''SELECT DISTINCT c.*,u.username host_name FROM live_courses c
                JOIN users u ON u.id=c.host_id LEFT JOIN live_members m ON m.course_id=c.id
                LEFT JOIN course_self_enrollments e ON e.course_id=c.id
                WHERE (m.user_id=? OR e.user_id=? OR (?=1 AND (?=1 OR c.owner_id=?)))
                AND instr(lower(c.title),lower(?))>0
                ORDER BY CASE WHEN ?='mine' THEN COALESCE((SELECT MAX(p.updated) FROM course_progress p
                    JOIN course_lessons l ON l.id=p.lesson_id WHERE l.course_id=c.id AND p.user_id=?),0)
                    ELSE c.id END DESC,c.id DESC''',
                (user['id'], user['id'], user['is_admin'], user['is_superadmin'], user['id'], q.strip(),
                 scope, user['id'])).fetchall()
            if scope == 'managed':
                rows = [row for row in rows if live.manage(row, user)]
        items = []
        for row in rows:
            course = dict(row)
            count = db.execute('SELECT COUNT(*) FROM course_lessons WHERE course_id=?',
                               (row['id'],)).fetchone()[0]
            kinds = [item['kind'] for item in db.execute('''SELECT DISTINCT i.kind FROM course_lesson_items i
                JOIN course_lessons l ON l.id=i.lesson_id WHERE l.course_id=? ORDER BY i.kind''',
                (row['id'],))]
            item = {**course, 'lesson_count': count, 'content_kinds': kinds,
                    'can_manage': live.manage(row, user) if scope != 'public' else False,
                    'is_enrolled': courses.is_enrolled(db, row['id'], user)}
            if scope != 'public':
                item['progress_summary'] = courses.progress_summary(db, row['id'], user['id'])
                item['resume_lesson_id'] = courses.resume_lesson(db, row['id'], user['id'])
            items.append(item)
        return {'items': items}


@router.get('/public/{course_id}')
def public_course_preview(course_id: int, user=Depends(current_user)):
    with connect() as db:
        preview = courses.public_preview(db, course_id)
        enrolled = courses.is_enrolled(db, course_id, user)
        preview['is_enrolled'] = enrolled
        preview['can_manage'] = live.manage(db.execute(
            'SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone(), user)
        if enrolled:
            preview['progress_summary'] = courses.progress_summary(db, course_id, user['id'])
            preview['resume_lesson_id'] = courses.resume_lesson(db, course_id, user['id'])
        return preview


@router.post('', status_code=201)
def create_course(payload: CourseWrite, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = _save_course(db, payload, user)
        if payload.publication_status == 'published':
            courses.validate_publish_ready(db, row['id'])
        return courses.course_detail(db, row['id'], user)


@router.get('/{course_id}')
def get_course(course_id: int, user=Depends(current_user)):
    with connect() as db:
        return courses.course_detail(db, course_id, user)


@router.patch('/{course_id}')
def update_course(course_id: int, payload: CourseWrite, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        _save_course(db, payload, user, course_id)
        if payload.publication_status == 'published':
            courses.validate_publish_ready(db, course_id)
        return courses.course_detail(db, course_id, user)


@router.post('/{course_id}/enroll')
def enroll(course_id: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        course = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
        if not course or course['publication_status'] != 'published' or course['access_mode'] != 'public':
            raise HTTPException(404, '公开课程不存在或暂不可加入')
        db.execute('INSERT OR IGNORE INTO course_self_enrollments(course_id,user_id,enrolled_at) VALUES (?,?,?)',
                   (course_id, user['id'], time.time()))
        return courses.course_detail(db, course_id, user)


@router.delete('/{course_id}/enroll')
def unenroll(course_id: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        course = db.execute('SELECT access_mode FROM live_courses WHERE id=?', (course_id,)).fetchone()
        enrollment = db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?',
                                (course_id, user['id'])).fetchone()
        if not course or not enrollment:
            raise HTTPException(404, '自主加入的课程不存在')
        db.execute('DELETE FROM course_self_enrollments WHERE course_id=? AND user_id=?', (course_id, user['id']))
        return {'ok': True}


@router.delete('/{course_id}')
def delete_course(course_id: int, user=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        course = courses.require_access(db, course_id, user, manager=True)
        if db.execute("SELECT 1 FROM live_lessons WHERE course_id=? AND status='live' LIMIT 1",
                      (course_id,)).fetchone():
            raise HTTPException(409, '请先结束课程内正在进行的直播')
        if db.execute("""SELECT 1 FROM live_recordings r JOIN live_lessons l ON l.id=r.lesson_id
            WHERE l.course_id=? AND r.status IN ('starting','recording','stopping','unknown') LIMIT 1""",
                      (course_id,)).fetchone():
            raise HTTPException(409, '课程内仍有录制任务未结束或状态待确认，请先处理录制状态')

        media_root = Path(load_config()['live']['directory']).resolve()
        course_assets_root = Path(load_config()['course_media']['directory']).resolve() / 'assets'
        course_files = [(course_assets_root / row['storage_name']).resolve() for row in db.execute(
            'SELECT storage_name FROM course_assets WHERE course_id=?', (course_id,))]
        if any(path.parent != course_assets_root for path in course_files):
            raise HTTPException(500, '课程私有文件路径无效，已取消删除')
        files = list(course_files)
        live_files = db.execute('''SELECT 'materials' AS kind,f.path FROM live_materials f
            JOIN live_lessons l ON l.id=f.lesson_id WHERE l.course_id=?
            UNION ALL
            SELECT 'recordings' AS kind,f.path FROM live_recordings f
            JOIN live_lessons l ON l.id=f.lesson_id WHERE l.course_id=?''', (course_id, course_id))
        for row in live_files:
            base = (media_root / row['kind']).resolve()
            path = (base / row['path']).resolve()
            if path.parent != base:
                raise HTTPException(500, '课程私有文件路径无效，已取消删除')
            files.append(path)
        db.execute('DELETE FROM live_courses WHERE id=?', (course_id,))

    try:
        for path in files:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(503, '课程记录已删除，但私有文件清理失败，请联系管理员清理存储') from error
    return {'ok': True}


@router.post('/{course_id}/sections', status_code=201)
def add_section(course_id: int, payload: NamedPosition, user=Depends(administrator)):
    with connect() as db:
        courses.require_access(db, course_id, user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        cursor = db.execute('INSERT INTO course_sections(course_id,title,position) VALUES (?,?,?)',
                            (course_id, payload.title.strip(), payload.position))
        return dict(db.execute('SELECT * FROM course_sections WHERE id=?', (cursor.lastrowid,)).fetchone())


@router.patch('/sections/{section_id}')
def update_section(section_id: int, payload: NamedPosition, user=Depends(administrator)):
    with connect() as db:
        section = db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            raise HTTPException(404, '章节不存在')
        courses.require_access(db, section['course_id'], user, manager=True)
        db.execute('UPDATE course_sections SET title=?,position=? WHERE id=?',
                   (payload.title.strip(), payload.position, section_id))
        return dict(db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone())


@router.delete('/sections/{section_id}')
def delete_section(section_id: int, user=Depends(administrator)):
    with connect() as db:
        section = db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            raise HTTPException(404, '章节不存在')
        courses.require_access(db, section['course_id'], user, manager=True)
        if db.execute('''SELECT 1 FROM course_lessons l LEFT JOIN live_lessons v ON v.course_lesson_id=l.id
            WHERE l.section_id=? AND v.status='live' LIMIT 1''', (section_id,)).fetchone():
            raise HTTPException(409, '章节中有正在直播的课次，不能删除')
        if db.execute('SELECT COUNT(*) FROM course_sections WHERE course_id=?', (section['course_id'],)).fetchone()[0] <= 1:
            raise HTTPException(409, '课程至少保留一个章节')
        if db.execute('SELECT 1 FROM course_lessons WHERE section_id=? LIMIT 1', (section_id,)).fetchone():
            raise HTTPException(409, '请先删除本章节中的课时，再删除章节')
        db.execute('DELETE FROM course_sections WHERE id=?', (section_id,))
        courses.compact_positions(db, 'course_sections', 'course_id', section['course_id'])
        return {'ok': True}


@router.put('/{course_id}/sections/order')
def reorder_sections(course_id: int, payload: IdOrder, user=Depends(administrator)):
    with connect() as db:
        courses.require_access(db, course_id, user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        _apply_positions(db, 'course_sections', 'course_id', course_id, payload.ids)
        return courses.course_detail(db, course_id, user)


@router.post('/sections/{section_id}/lessons', status_code=201)
def add_lesson(section_id: int, payload: LessonWrite, user=Depends(administrator)):
    with connect() as db:
        section = db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            raise HTTPException(404, '章节不存在')
        courses.require_access(db, section['course_id'], user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        cursor = db.execute('''INSERT INTO course_lessons(course_id,section_id,title,description,position)
            VALUES (?,?,?,?,?)''', (section['course_id'], section_id, payload.title.strip(),
                                     payload.description.strip(), payload.position))
        return courses.lesson_view(db, dict(db.execute('SELECT * FROM course_lessons WHERE id=?',
                                                       (cursor.lastrowid,)).fetchone()), user)


@router.patch('/lessons/{lesson_id}')
def update_lesson(lesson_id: int, payload: LessonWrite, user=Depends(administrator)):
    with connect() as db:
        lesson, _ = courses.require_lesson(db, lesson_id, user, manager=True)
        if db.execute('''SELECT 1 FROM live_lessons WHERE course_lesson_id=? AND status='live' ''',
                      (lesson_id,)).fetchone():
            raise HTTPException(409, '直播期间不能编辑课时')
        db.execute('UPDATE course_lessons SET title=?,description=?,position=? WHERE id=?',
                   (payload.title.strip(), payload.description.strip(), payload.position, lesson_id))
        return courses.lesson_view(db, courses.lesson_row(db, lesson_id), user)


@router.put('/sections/{section_id}/lessons/order')
def reorder_lessons(section_id: int, payload: IdOrder, user=Depends(administrator)):
    with connect() as db:
        section = db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            raise HTTPException(404, '章节不存在')
        courses.require_access(db, section['course_id'], user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        _apply_positions(db, 'course_lessons', 'section_id', section_id, payload.ids)
        return courses.course_detail(db, section['course_id'], user)


@router.delete('/lessons/{lesson_id}')
def delete_lesson(lesson_id: int, user=Depends(administrator)):
    with connect() as db:
        lesson, _ = courses.require_lesson(db, lesson_id, user, manager=True)
        live_row = db.execute('SELECT id,status FROM live_lessons WHERE course_lesson_id=?', (lesson_id,)).fetchone()
        if live_row and live_row['status'] == 'live':
            raise HTTPException(409, '请先结束直播')
        if live_row:
            raise HTTPException(409, '请先在直播课次管理中删除关联课次，再删除此课时')
        if db.execute('SELECT 1 FROM course_assets WHERE lesson_id=?', (lesson_id,)).fetchone():
            raise HTTPException(409, '请先移除课时中的视频和文档')
        db.execute('DELETE FROM course_lessons WHERE id=?', (lesson['id'],))
        if live_row:
            db.execute('DELETE FROM live_lessons WHERE id=?', (live_row['id'],))
        courses.compact_positions(db, 'course_lessons', 'section_id', lesson['section_id'])
        return {'ok': True}


@router.put('/lessons/{lesson_id}/items')
def order_items(lesson_id: int, payload: ItemOrder, user=Depends(administrator)):
    with connect() as db:
        courses.require_lesson(db, lesson_id, user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        courses.reorder_items(db, lesson_id, [item.model_dump() for item in payload.items])
        return courses.lesson_view(db, courses.lesson_row(db, lesson_id), user)


@router.post('/lessons/{lesson_id}/assets', status_code=201)
async def upload_asset(lesson_id: int, kind: str = Query(pattern='^(video|document)$'),
                       file: UploadFile = File(...), user=Depends(administrator)):
    with connect() as db:
        lesson, course = courses.require_lesson(db, lesson_id, user, manager=True)
        suffix = Path((file.filename or '').replace('\\', '/')).suffix.lower()
        allowed = VIDEO_TYPES if kind == 'video' else DOCUMENT_TYPES
        if suffix not in allowed or len(file.filename or '') > 200:
            raise HTTPException(422, '不支持的文件格式')
        maximum = load_config()['course_media'][f'{kind}_max_mb'] * 1024 * 1024
        storage_name = secrets.token_hex(24) + suffix
        path = asset_path(storage_name)
        size = 0
        try:
            with path.open('xb') as output:
                path.chmod(0o600)
                while chunk := await file.read(65536):
                    size += len(chunk)
                    if size > maximum:
                        raise HTTPException(413, '文件超过课程上传大小限制')
                    output.write(chunk)
            if not size:
                raise HTTPException(422, '不能上传空文件')
            db.execute('BEGIN IMMEDIATE')
            position = db.execute('SELECT COUNT(*) FROM course_lesson_items WHERE lesson_id=?',
                                  (lesson_id,)).fetchone()[0]
            asset_id = db.execute('''INSERT INTO course_assets(course_id,lesson_id,kind,original_name,storage_name,
                size,mime_type,uploaded_by,created) VALUES (?,?,?,?,?,?,?,?,?)''',
                (course['id'], lesson_id, kind, Path((file.filename or '').replace('\\', '/')).name,
                 storage_name, size, allowed[suffix], user['id'], time.time())).lastrowid
            db.execute('INSERT INTO course_lesson_items(lesson_id,kind,position,asset_id) VALUES (?,?,?,?)',
                       (lesson_id, kind, position, asset_id))
        except (OSError, HTTPException):
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {'id': asset_id, 'kind': kind, 'name': Path(file.filename or '').name, 'size': size}


@router.delete('/assets/{asset_id}')
def delete_asset(asset_id: int, user=Depends(administrator)):
    with connect() as db:
        asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, '课程文件不存在')
        courses.require_access(db, asset['course_id'], user, manager=True)
        path = asset_path(asset['storage_name'])
        db.execute('DELETE FROM course_assets WHERE id=?', (asset_id,))
        courses.compact_positions(db, 'course_lesson_items', 'lesson_id', asset['lesson_id'])
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(503, '文件记录已移除，但私有文件清理失败，请联系管理员清理存储') from error
    return {'ok': True}


@router.get('/assets/{asset_id}/file')
def asset_file(asset_id: int, user=Depends(current_user)):
    with connect() as db:
        asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, '课程文件不存在')
        courses.require_access(db, asset['course_id'], user)
        if asset['kind'] != 'document':
            raise HTTPException(404, '视频请使用课程播放器')
        path = asset_path(asset['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程文件不可用，请联系管理员')
        return FileResponse(path, media_type=asset['mime_type'], filename=asset['original_name'],
                            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/assets/{asset_id}/playback')
def create_playback_ticket(asset_id: int, user=Depends(current_user)):
    with connect() as db:
        asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, '课程视频不存在')
        courses.require_access(db, asset['course_id'], user)
        if asset['kind'] != 'video':
            raise HTTPException(404, '该课程内容不是视频')
        path = asset_path(asset['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程视频不可用，请联系管理员')
        token = secrets.token_urlsafe(32)
        expires = time.time() + load_config()['course_media']['playback_seconds']
        db.execute('DELETE FROM course_playback_tickets WHERE expires<=?', (time.time(),))
        db.execute('INSERT INTO course_playback_tickets(token,asset_id,user_id,expires) VALUES (?,?,?,?)',
                   (token, asset_id, user['id'], expires))
        return {'url': f'/api/courses/playback/{token}', 'expires': expires}


@router.get('/playback/{token}')
def playback_file(token: str):
    with connect() as db:
        row = db.execute('''SELECT a.*,t.user_id,t.expires,u.is_active,u.is_admin,u.is_superadmin,
            c.owner_id,c.host_id FROM course_playback_tickets t
            JOIN course_assets a ON a.id=t.asset_id JOIN users u ON u.id=t.user_id
            JOIN live_courses c ON c.id=a.course_id WHERE t.token=?''', (token,)).fetchone()
        if not row or row['kind'] != 'video' or row['expires'] <= time.time() or not row['is_active']:
            raise HTTPException(404, '播放链接已失效，请重新打开课程')
        user = {'id': row['user_id'], 'is_admin': row['is_admin'],
                'is_superadmin': row['is_superadmin']}
        if not courses.can_access_course(db, row['course_id'], user):
            raise HTTPException(404, '播放链接已失效，请重新加入课程')
        path = asset_path(row['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程视频不可用，请联系管理员')
        return FileResponse(path, media_type=row['mime_type'], headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/lessons/{lesson_id}')
def get_lesson(lesson_id: int, user=Depends(current_user)):
    with connect() as db:
        lesson, _ = courses.require_lesson(db, lesson_id, user)
        return courses.lesson_view(db, lesson, user)


@router.post('/lessons/{lesson_id}/live', status_code=201)
def create_live_session(lesson_id: int, payload: LiveSessionWrite, user=Depends(administrator)):
    with connect() as db:
        lesson, course = courses.require_lesson(db, lesson_id, user, manager=True)
        existing = db.execute('SELECT id FROM live_lessons WHERE course_lesson_id=?', (lesson_id,)).fetchone()
        if existing:
            raise HTTPException(409, '本课时已关联直播课次')
        db.execute('BEGIN IMMEDIATE')
        live_id = db.execute('''INSERT INTO live_lessons(course_id,title,description,starts_at,course_lesson_id)
            VALUES (?,?,?,?,?)''', (course['id'], lesson['title'], lesson['description'],
                                     payload.starts_at, lesson_id)).lastrowid
        position = db.execute('SELECT COUNT(*) FROM course_lesson_items WHERE lesson_id=?', (lesson_id,)).fetchone()[0]
        db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,live_lesson_id)
            VALUES (?,'live',?,?)''', (lesson_id, position, live_id))
        row, parent = live.lesson(db, live_id, user)
        return live.lesson_view(db, row, parent, user)


@router.post('/sections/{section_id}/live', status_code=201)
def create_live_course_unit(section_id: int, payload: LiveCourseUnitWrite, user=Depends(administrator)):
    """Create the course lesson and its live session as one atomic course operation."""
    with connect() as db:
        section = db.execute('SELECT * FROM course_sections WHERE id=?', (section_id,)).fetchone()
        if not section:
            raise HTTPException(404, '章节不存在')
        course = courses.require_access(db, section['course_id'], user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        lesson_id = db.execute('''INSERT INTO course_lessons(course_id,section_id,title,description,position)
            VALUES (?,?,?,?,?)''', (course['id'], section_id, payload.title.strip(),
                                     payload.description.strip(), payload.position)).lastrowid
        live_id = db.execute('''INSERT INTO live_lessons(course_id,title,description,starts_at,course_lesson_id)
            VALUES (?,?,?,?,?)''', (course['id'], payload.title.strip(), payload.description.strip(),
                                     payload.starts_at, lesson_id)).lastrowid
        db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,live_lesson_id)
            VALUES (?,'live',0,?)''', (lesson_id, live_id))
        return courses.course_detail(db, course['id'], user)


@router.put('/lessons/{lesson_id}/progress')
def save_progress(lesson_id: int, payload: ProgressWrite, user=Depends(current_user)):
    with connect() as db:
        courses.require_lesson(db, lesson_id, user)
        has_video = db.execute('''SELECT 1 FROM course_lesson_items i JOIN course_assets a ON a.id=i.asset_id
            WHERE i.lesson_id=? AND i.kind='video' LIMIT 1''', (lesson_id,)).fetchone()
        has_content = db.execute('''SELECT 1 FROM course_lesson_items i
            LEFT JOIN course_assets a ON a.id=i.asset_id
            LEFT JOIN live_lessons l ON l.id=i.live_lesson_id
            WHERE i.lesson_id=? AND ((i.kind='live' AND l.id IS NOT NULL) OR
                (i.kind IN ('video','document') AND a.id IS NOT NULL)) LIMIT 1''', (lesson_id,)).fetchone()
        if payload.position_seconds and not has_video:
            raise HTTPException(422, '该课时没有可保存进度的视频')
        if payload.completed and not has_content:
            raise HTTPException(422, '请先为课时添加学习内容')
        progress = courses.update_progress(db, lesson_id, user['id'], payload.position_seconds, payload.completed)
        return {**progress, 'course': courses.progress_summary(db, courses.lesson_row(db, lesson_id)['course_id'], user['id'])}
