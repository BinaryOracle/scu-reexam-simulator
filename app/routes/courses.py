"""Authenticated course catalog, authoring, enrollment, and learner progress API."""
import secrets
import time
import os
import io
import re
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, StrictBool, StrictInt, ConfigDict
from PIL import Image, UnidentifiedImageError
from app.db import connect
from app.config import load_config
from app.services.auth import current_user, administrator
from app.services import course_learning as courses
from app.services import live, points

router = APIRouter(prefix='/api/courses', tags=['courses'])
DOCUMENT_TYPES = {'.pdf': 'application/pdf', '.txt': 'text/plain', '.md': 'text/markdown',
                  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                  '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
VIDEO_TYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm'}
COVER_TYPES = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}
COVER_PRESETS = {'forest', 'ocean', 'coral', 'graphite', 'violet', 'mint'}


class CourseWrite(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=4000)
    publication_status: str = Field(default='draft', pattern='^(draft|published|archived)$')
    access_mode: str = Field(default='roster', pattern='^(public|roster|points)$')
    points_price: StrictInt | None = Field(default=None, ge=0, le=100000000)
    points_access_days: StrictInt | None = Field(default=None, ge=0, le=36500)
    host_id: StrictInt | None = Field(default=None, gt=0)
    member_ids: list[StrictInt] = Field(default_factory=list, max_length=1000)
    cover_kind: str | None = Field(default=None, pattern='^(preset|upload)$')
    cover_value: str | None = Field(default=None, max_length=40)


class NamedPosition(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    position: StrictInt = Field(ge=0, le=10000)
    preview_enabled: StrictBool | None = None


class CoursePurchase(BaseModel):
    expected_points_price: StrictInt = Field(gt=0, le=100000000)


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


class MarkdownWrite(BaseModel):
    markdown: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=196)


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


def validate_markdown_images(db, course_id, lesson_id, markdown):
    for link in courses.markdown_image_links(markdown):
        match = courses.MARKDOWN_IMAGE_PATH.fullmatch(link)
        if not match or not db.execute(
                'SELECT 1 FROM course_markdown_images WHERE id=? AND course_id=? AND lesson_id IS ?',
                (match[1], course_id, lesson_id)).fetchone():
            scope = '当前课程简介' if lesson_id is None else '当前课时'
            if course_id is None:
                raise HTTPException(422, '请先保存课程草稿，再粘贴图片')
            raise HTTPException(422, f'Markdown 图片须先粘贴上传到{scope}')


def _markdown_asset(db, lesson_id, course_id, user, payload):
    content = payload.markdown.encode('utf-8')
    if not payload.markdown.strip():
        raise HTTPException(422, 'Markdown 正文不能为空')
    maximum = load_config()['course_media']['document_max_mb'] * 1024 * 1024
    if len(content) > maximum:
        raise HTTPException(413, 'Markdown 正文超过课程资料大小限制')
    validate_markdown_images(db, course_id, lesson_id, payload.markdown)
    name = (payload.name or '课程正文').strip().replace('\\', '-').replace('/', '-')
    if not name:
        raise HTTPException(422, '文档名称不能为空')
    original_name = name if name.lower().endswith('.md') else f'{name}.md'
    if len(original_name) > 200:
        raise HTTPException(422, '文档名称不能超过 200 个字符')
    storage_name = secrets.token_hex(24) + '.md'
    path = asset_path(storage_name)
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            output.write(content)
        position = db.execute('SELECT COUNT(*) FROM course_lesson_items WHERE lesson_id=?',
                              (lesson_id,)).fetchone()[0]
        asset_id = db.execute('''INSERT INTO course_assets(course_id,lesson_id,kind,original_name,storage_name,
            size,mime_type,uploaded_by,created) VALUES (?,?,'document',?,?,?,?,?,?)''',
            (course_id, lesson_id, original_name, storage_name, len(content), 'text/markdown',
             user['id'], time.time())).lastrowid
        db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,asset_id)
            VALUES (?,'document',?,?)''', (lesson_id, position, asset_id))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'id': asset_id, 'kind': 'document', 'name': original_name, 'size': len(content)}


def cover_path(name):
    """Resolve a generated course cover filename inside private cover storage."""
    base = Path(load_config()['course_media']['directory']).resolve() / 'covers'
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = (base / name).resolve()
    if path.parent != base or not name:
        raise HTTPException(404, '课程封面不存在')
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
    previous = db.execute('SELECT points_price,points_access_days FROM live_courses WHERE id=?', (course_id,)).fetchone() if course_id else None
    price = payload.points_price if payload.points_price is not None else previous['points_price'] if previous else 0
    access_days = payload.points_access_days if payload.points_access_days is not None else previous['points_access_days'] if previous else 0
    if payload.access_mode == 'points' and price <= 0:
        raise HTTPException(422, '积分购买课程须设置大于 0 的整数价格')
    live.validate_people(db, [host_id, *payload.member_ids], user)
    if course_id is None:
        validate_markdown_images(db, None, None, payload.description)
        cover_kind, cover_value = _preset_cover(payload)
        course_id = db.execute('''INSERT INTO live_courses(title,description,host_id,owner_id,publication_status,access_mode,cover_kind,cover_value)
            VALUES (?,?,?,?,?,?,?,?)''', (title, payload.description.strip(), host_id, user['id'],
                                      payload.publication_status, payload.access_mode, cover_kind, cover_value)).lastrowid
        db.execute("INSERT INTO course_sections(course_id,title,position) VALUES (?,'第一章',0)", (course_id,))
    else:
        course = courses.require_access(db, course_id, user, manager=True)
        validate_markdown_images(db, course_id, None, payload.description)
        if db.execute("SELECT 1 FROM live_lessons WHERE course_id=? AND status='live'", (course_id,)).fetchone():
            raise HTTPException(409, '直播期间不能修改课程主持人或成员')
        if payload.cover_kind is not None:
            cover_kind, cover_value = _preset_cover(payload)
            db.execute('''UPDATE live_courses SET title=?,description=?,host_id=?,publication_status=?,access_mode=?,
                cover_kind=?,cover_value=?,cover_asset_id=NULL WHERE id=?''',
                (title, payload.description.strip(), host_id, payload.publication_status,
                 payload.access_mode, cover_kind, cover_value, course_id))
        else:
            db.execute('''UPDATE live_courses SET title=?,description=?,host_id=?,publication_status=?,access_mode=?
                WHERE id=?''', (title, payload.description.strip(), host_id, payload.publication_status,
                                payload.access_mode, course_id))
        db.execute('DELETE FROM live_members WHERE course_id=?', (course_id,))
        # A paid or assigned course no longer honors old public self-enrollments;
        # purchased entitlements survive either mode change.
        if payload.access_mode != 'public':
            db.execute('''DELETE FROM course_self_enrollments WHERE course_id=? AND NOT EXISTS (
                SELECT 1 FROM course_purchases p WHERE p.course_id=course_self_enrollments.course_id
                AND p.user_id=course_self_enrollments.user_id)''', (course_id,))
    db.execute('UPDATE live_courses SET points_price=?,points_access_days=? WHERE id=?', (price, access_days, course_id))
    db.executemany('INSERT INTO live_members(course_id,user_id) VALUES (?,?)',
                   [(course_id, uid) for uid in set([host_id, *(payload.member_ids if payload.access_mode == 'roster' else [])])])
    return _course_row(db, course_id)


def _preset_cover(payload):
    if payload.cover_kind is None:
        return None, None
    if payload.cover_kind != 'preset' or payload.cover_value not in COVER_PRESETS:
        raise HTTPException(422, '请选择有效的预设封面')
    return 'preset', payload.cover_value


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
            q: str = Query(default='', max_length=100), removed: bool = Query(default=False),
            user=Depends(current_user)):
    with connect() as db:
        if scope == 'public':
            rows = db.execute('''SELECT c.id,c.title,c.description,c.publication_status,c.access_mode,
                c.cover_kind,c.cover_value,c.cover_asset_id,c.points_price,
                u.username host_name FROM live_courses c JOIN users u ON u.id=c.host_id
                WHERE c.publication_status='published' AND (c.access_mode IN ('public','points') OR EXISTS (
                    SELECT 1 FROM course_lessons l JOIN course_sections s ON s.id=l.section_id
                    WHERE l.course_id=c.id AND l.preview_enabled=1 AND s.preview_enabled=1))
                AND instr(lower(c.title),lower(?))>0 ORDER BY c.id DESC''', (q.strip(),)).fetchall()
        elif scope == 'mine':
            rows = db.execute('''SELECT DISTINCT c.*,u.username host_name FROM live_courses c
                JOIN users u ON u.id=c.host_id LEFT JOIN live_members m ON m.course_id=c.id
                LEFT JOIN course_self_enrollments e ON e.course_id=c.id
                LEFT JOIN course_purchases p ON p.course_id=c.id AND (p.access_expires_at IS NULL OR p.access_expires_at>?)
                WHERE ((e.user_id=? AND (c.access_mode='public' OR NOT EXISTS (SELECT 1 FROM course_purchases x WHERE x.course_id=c.id AND x.user_id=?))) OR p.user_id=? OR (m.user_id=? AND c.host_id<>?
                    AND NOT (?=1 AND (?=1 OR c.owner_id=?))))
                AND c.publication_status='published'
                AND instr(lower(c.title),lower(?))>0
                ORDER BY COALESCE((SELECT MAX(p.updated) FROM course_progress p
                    JOIN course_lessons l ON l.id=p.lesson_id WHERE l.course_id=c.id AND p.user_id=?),0) DESC,c.id DESC''',
                (time.time(), user['id'], user['id'], user['id'], user['id'], user['id'], user['is_admin'], user['is_superadmin'], user['id'],
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
            is_removed = courses.is_removed_from_library(db, row['id'], user['id'])
            if scope == 'mine' and is_removed != removed:
                continue
            course = dict(row)
            course.pop('cover_asset_id', None)
            count = db.execute('SELECT COUNT(*) FROM course_lessons WHERE course_id=?',
                               (row['id'],)).fetchone()[0]
            kinds = [item['kind'] for item in db.execute('''SELECT DISTINCT i.kind FROM course_lesson_items i
                JOIN course_lessons l ON l.id=i.lesson_id WHERE l.course_id=? ORDER BY i.kind''',
                (row['id'],))]
            item = {**course,
                    'description_summary': courses.markdown_summary(course.get('description', '')),
                    'cover_url': f"/api/courses/{row['id']}/cover" if course.get('cover_kind') == 'upload' else None,
                    'section_count': db.execute('SELECT COUNT(*) FROM course_sections WHERE course_id=?',
                                                (row['id'],)).fetchone()[0],
                    'lesson_count': count, 'content_kinds': kinds,
                    'can_manage': live.manage(row, user) if scope != 'public' else False,
                    'is_removed_from_library': is_removed,
                    'is_enrolled': courses.is_enrolled(db, row['id'], user)}
            if scope != 'public':
                item['progress_summary'] = courses.progress_summary(db, row['id'], user['id'])
                item['resume_lesson_id'] = courses.resume_lesson(db, row['id'], user['id'])
            items.append(item)
        return {'items': items}


@router.get('/public/{course_id}')
def public_course_preview(course_id: int, user=Depends(current_user)):
    with connect() as db:
        preview = courses.public_preview(db, course_id, user)
        preview['points_balance'] = db.execute('SELECT points FROM users WHERE id=?', (user['id'],)).fetchone()[0]
        enrolled = courses.is_enrolled(db, course_id, user)
        preview['is_enrolled'] = enrolled
        preview['is_removed_from_library'] = courses.is_removed_from_library(db, course_id, user['id'])
        preview['can_manage'] = live.manage(db.execute(
            'SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone(), user)
        if enrolled:
            progress = {row['lesson_id']: bool(row['completed']) for row in db.execute(
                '''SELECT p.lesson_id,p.completed FROM course_progress p
                   JOIN course_lessons l ON l.id=p.lesson_id WHERE l.course_id=? AND p.user_id=?''',
                (course_id, user['id']))}
            for section in preview['sections']:
                for lesson in section['lessons']:
                    lesson['progress'] = {'completed': progress.get(lesson['id'], False)}
            preview['progress_summary'] = courses.progress_summary(db, course_id, user['id'])
            preview['resume_lesson_id'] = courses.resume_lesson(db, course_id, user['id'])
        else:
            for section in preview['sections']:
                for lesson in section['lessons']:
                    lesson['progress'] = {'completed': False}
            preview['progress_summary'] = {'total': preview['lesson_count'], 'completed': 0, 'percent': 0}
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
        before = db.execute('SELECT cover_asset_id FROM live_courses WHERE id=?', (course_id,)).fetchone()
        _save_course(db, payload, user, course_id)
        if payload.publication_status == 'published':
            courses.validate_publish_ready(db, course_id)
        result = courses.course_detail(db, course_id, user)
    if before and before['cover_asset_id'] and payload.cover_kind is not None:
        try:
            cover_path(before['cover_asset_id']).unlink(missing_ok=True)
        except OSError:
            pass
    return result


@router.post('/{course_id}/cover')
async def upload_course_cover(course_id: int, file: UploadFile = File(...), user=Depends(administrator)):
    """Store a decoded raster cover for a course the caller can manage."""
    maximum = load_config()['course_media']['cover_max_mb'] * 1024 * 1024
    content = await file.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(413, f"封面图片不能超过 {load_config()['course_media']['cover_max_mb']} MB")
    try:
        image = Image.open(io.BytesIO(content))
        image.verify()
        image = Image.open(io.BytesIO(content))
        image_format = image.format
        if image_format not in COVER_TYPES or image.width * image.height > 24_000_000:
            raise HTTPException(422, '请上传 PNG、JPG 或 WebP 图片（最大 2400 万像素）')
        image.load()
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if image_format == 'PNG' else 'RGB')
        mime_type, extension = COVER_TYPES[image_format]
        encoded = io.BytesIO()
        image.save(encoded, format=image_format, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(422, '无法读取图片，请重新选择 PNG、JPG 或 WebP 文件') from error

    storage_name = f'{secrets.token_hex(24)}{extension}'
    path = cover_path(storage_name)
    path.write_bytes(encoded.getvalue())
    path.chmod(0o600)
    old_name = None
    try:
        with connect() as db:
            course = courses.require_access(db, course_id, user, manager=True)
            old_name = course.get('cover_asset_id')
            db.execute("UPDATE live_courses SET cover_kind='upload',cover_value=NULL,cover_asset_id=? WHERE id=?",
                       (storage_name, course_id))
            result = courses.course_detail(db, course_id, user)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if old_name and old_name != storage_name:
        try:
            cover_path(old_name).unlink(missing_ok=True)
        except OSError:
            pass
    result['cover_mime_type'] = mime_type
    return result


@router.get('/{course_id}/cover')
def course_cover(course_id: int, user=Depends(current_user)):
    """Serve a private course cover after checking course access."""
    with connect() as db:
        row = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
        if not row:
            raise HTTPException(404, '课程不存在')
        course = dict(row)
        public_preview_allowed = course['publication_status'] == 'published' and (course['access_mode'] in ('public', 'points') or db.execute('''
            SELECT 1 FROM course_lessons l JOIN course_sections s ON s.id=l.section_id
            WHERE l.course_id=? AND l.preview_enabled=1 AND s.preview_enabled=1''', (course_id,)).fetchone())
        if not public_preview_allowed:
            course = courses.require_access(db, course_id, user)
        if course.get('cover_kind') != 'upload' or not course.get('cover_asset_id'):
            raise HTTPException(404, '课程没有上传封面')
        name = course['cover_asset_id']
        path = cover_path(name)
        if not path.is_file():
            raise HTTPException(404, '课程封面文件不可用')
        media_type = COVER_TYPES.get(path.suffix.lower().lstrip('.').upper(), ('image/jpeg', ''))[0]
        if path.suffix.lower() == '.jpg':
            media_type = 'image/jpeg'
    return FileResponse(path, media_type=media_type, headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.put('/{course_id}/cover/preset')
def select_course_cover(course_id: int, payload: dict, user=Depends(administrator)):
    """Select a curated preset cover and discard the previous uploaded cover."""
    value = payload.get('cover_value') if isinstance(payload, dict) else None
    if value not in COVER_PRESETS:
        raise HTTPException(422, '请选择有效的预设封面')
    old_name = None
    with connect() as db:
        course = courses.require_access(db, course_id, user, manager=True)
        old_name = course.get('cover_asset_id')
        db.execute("UPDATE live_courses SET cover_kind='preset',cover_value=?,cover_asset_id=NULL WHERE id=?",
                   (value, course_id))
        result = courses.course_detail(db, course_id, user)
    if old_name:
        try:
            cover_path(old_name).unlink(missing_ok=True)
        except OSError:
            pass
    return result


@router.post('/markdown/preview', response_class=HTMLResponse)
def markdown_preview(payload: MarkdownWrite, user=Depends(administrator)):
    """Render untrusted editor Markdown through the same safe renderer as lessons."""
    return HTMLResponse(courses.render_lesson_markdown(payload.markdown), headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; style-src 'none'; img-src 'none'; base-uri 'none'"})


@router.post('/{course_id}/enroll')
def enroll(course_id: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        course = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
        if not course or course['publication_status'] != 'published' or course['access_mode'] != 'public':
            raise HTTPException(404, '公开课程不存在或暂不可加入')
        db.execute('INSERT OR IGNORE INTO course_self_enrollments(course_id,user_id,enrolled_at) VALUES (?,?,?)',
                   (course_id, user['id'], time.time()))
        db.execute('DELETE FROM course_library_hidden WHERE course_id=? AND user_id=?', (course_id, user['id']))
        return courses.course_detail(db, course_id, user)


@router.delete('/{course_id}/enroll')
def unenroll(course_id: int, user=Depends(current_user)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('''SELECT 1 FROM course_purchases WHERE course_id=? AND user_id=?
            AND (access_expires_at IS NULL OR access_expires_at>?)''', (course_id, user['id'], time.time())).fetchone():
            raise HTTPException(409, '已购买课程请使用移除功能，购买资格和学习进度会保留')
        course = db.execute('SELECT access_mode FROM live_courses WHERE id=?', (course_id,)).fetchone()
        enrollment = db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?',
                                (course_id, user['id'])).fetchone()
        if not course or not enrollment:
            raise HTTPException(404, '自主加入的课程不存在')
        db.execute('DELETE FROM course_self_enrollments WHERE course_id=? AND user_id=?', (course_id, user['id']))
        return {'ok': True}


@router.post('/{course_id}/purchase')
def purchase_course(course_id: int, payload: CoursePurchase, user=Depends(current_user)):
    """Debit points and grant the configured course entitlement atomically."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        course = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
        if not course or course['publication_status'] != 'published':
            raise HTTPException(404, '课程不存在或暂未开放购买')
        if courses.can_access_course(db, course_id, user):
            return courses.course_detail(db, course_id, user)
        if course['access_mode'] != 'points':
            raise HTTPException(409, '该课程不支持积分购买')
        if payload.expected_points_price != course['points_price']:
            raise HTTPException(409, '课程价格已更新，请刷新页面后重新确认')
        points.adjust(db, user['id'], -course['points_price'], kind='course_purchase', reference=f"课程：{course['title']}（{course_id}）")
        purchased_at = time.time()
        expires_at = purchased_at + course['points_access_days'] * 86400 if course['points_access_days'] else None
        db.execute('''INSERT INTO course_purchases(course_id,user_id,points_paid,purchased_at,access_expires_at)
            VALUES (?,?,?,?,?) ON CONFLICT(course_id,user_id) DO UPDATE SET
            points_paid=excluded.points_paid,purchased_at=excluded.purchased_at,
            access_expires_at=excluded.access_expires_at''',
            (course_id, user['id'], course['points_price'], purchased_at, expires_at))
        db.execute('INSERT OR IGNORE INTO course_self_enrollments(course_id,user_id) VALUES (?,?)', (course_id, user['id']))
        db.execute('DELETE FROM course_library_hidden WHERE course_id=? AND user_id=?', (course_id, user['id']))
        return courses.course_detail(db, course_id, user)


@router.delete('/{course_id}/library')
def remove_from_library(course_id: int, user=Depends(current_user)):
    """Hide an enrolled course for one learner while retaining membership and progress."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        courses.require_access(db, course_id, user)
        if not courses.is_enrolled(db, course_id, user):
            raise HTTPException(404, '我的课程中没有该课程')
        db.execute('INSERT OR IGNORE INTO course_library_hidden(course_id,user_id) VALUES (?,?)', (course_id, user['id']))
        return {'ok': True}


@router.post('/{course_id}/library')
def restore_to_library(course_id: int, user=Depends(current_user)):
    """Restore a hidden course only while the caller retains enrollment access."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        courses.require_access(db, course_id, user)
        if not courses.is_enrolled(db, course_id, user):
            raise HTTPException(404, '该课程暂不可恢复，请重新加入课程')
        db.execute('DELETE FROM course_library_hidden WHERE course_id=? AND user_id=?', (course_id, user['id']))
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
        cover_name = course.get('cover_asset_id')
        cover_file = cover_path(cover_name) if cover_name else None
        if cover_file and cover_file.parent != (Path(load_config()['course_media']['directory']).resolve() / 'covers'):
            raise HTTPException(500, '课程封面路径无效，已取消删除')
        course_files = [(course_assets_root / row['storage_name']).resolve() for row in db.execute(
            '''SELECT storage_name FROM course_assets WHERE course_id=?
               UNION ALL SELECT storage_name FROM course_markdown_images WHERE course_id=?''', (course_id, course_id))]
        if any(path.parent != course_assets_root for path in course_files):
            raise HTTPException(500, '课程私有文件路径无效，已取消删除')
        files = list(course_files)
        if cover_file:
            files.append(cover_file)
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
        db.execute('UPDATE course_sections SET preview_enabled=? WHERE id=?', (bool(payload.preview_enabled), cursor.lastrowid))
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
        if payload.preview_enabled is not None:
            db.execute('UPDATE course_sections SET preview_enabled=? WHERE id=?', (payload.preview_enabled, section_id))
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
        validate_markdown_images(db, section['course_id'], cursor.lastrowid, payload.description)
        db.execute('UPDATE course_lessons SET preview_enabled=? WHERE id=?', (bool(payload.preview_enabled), cursor.lastrowid))
        return courses.lesson_view(db, dict(db.execute('SELECT * FROM course_lessons WHERE id=?',
                                                       (cursor.lastrowid,)).fetchone()), user)


@router.patch('/lessons/{lesson_id}')
def update_lesson(lesson_id: int, payload: LessonWrite, user=Depends(administrator)):
    with connect() as db:
        lesson, _ = courses.require_lesson(db, lesson_id, user, manager=True)
        if db.execute('''SELECT 1 FROM live_lessons WHERE course_lesson_id=? AND status='live' ''',
                      (lesson_id,)).fetchone():
            raise HTTPException(409, '直播期间不能编辑课时')
        validate_markdown_images(db, lesson['course_id'], lesson_id, payload.description)
        db.execute('UPDATE course_lessons SET title=?,description=?,position=? WHERE id=?',
                   (payload.title.strip(), payload.description.strip(), payload.position, lesson_id))
        if payload.preview_enabled is not None:
            db.execute('UPDATE course_lessons SET preview_enabled=? WHERE id=?', (payload.preview_enabled, lesson_id))
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
        db.execute('BEGIN IMMEDIATE')
        lesson, _ = courses.require_lesson(db, lesson_id, user, manager=True)
        live_row = db.execute('SELECT id,status FROM live_lessons WHERE course_lesson_id=?', (lesson_id,)).fetchone()
        if live_row and live_row['status'] == 'live':
            raise HTTPException(409, '请先结束直播')
        if live_row:
            raise HTTPException(409, '请先在直播课次管理中删除关联课次，再删除此课时')
        if db.execute('SELECT 1 FROM course_assets WHERE lesson_id=?', (lesson_id,)).fetchone():
            raise HTTPException(409, '请先移除课时中的视频和文档')
        image_files = [asset_path(row['storage_name']) for row in db.execute(
            'SELECT storage_name FROM course_markdown_images WHERE lesson_id=?', (lesson_id,))]
        db.execute('DELETE FROM course_lessons WHERE id=?', (lesson['id'],))
        courses.compact_positions(db, 'course_lessons', 'section_id', lesson['section_id'])
    try:
        for path in image_files:
            path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(503, '课时已删除，但图片文件清理失败，请联系管理员清理存储') from error
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


async def _store_markdown_image(file, course_id, lesson_id, user):
    maximum = min(load_config()['course_media']['document_max_mb'] * 1024 * 1024, 5 * 1024 * 1024)
    try:
        content = await file.read(maximum + 1)
    finally:
        await file.close()
    if len(content) > maximum:
        raise HTTPException(413, f'粘贴图片不能超过 {maximum // (1024 * 1024)} MB')
    try:
        image = Image.open(io.BytesIO(content))
        image.verify()
        image = Image.open(io.BytesIO(content))
        image_format = image.format
        if image_format not in COVER_TYPES or image.width * image.height > 24_000_000:
            raise HTTPException(422, '粘贴图片仅支持 PNG、JPG 或 WebP（最大 2400 万像素）')
        image.load()
        image = image.convert('RGBA' if image_format == 'PNG' else 'RGB')
        mime_type, suffix = COVER_TYPES[image_format]
        output = io.BytesIO()
        image.save(output, format=image_format)
        encoded = output.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, '粘贴内容不是有效图片，请重新复制后粘贴') from error
    image_id = secrets.token_hex(16)
    storage_name = secrets.token_hex(24) + suffix
    path = asset_path(storage_name)
    try:
        with path.open('xb') as output_file:
            path.chmod(0o600)
            output_file.write(encoded)
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if lesson_id is None:
                courses.require_access(db, course_id, user, manager=True)
            else:
                courses.require_lesson(db, lesson_id, user, manager=True)
            db.execute('''INSERT INTO course_markdown_images(id,course_id,lesson_id,storage_name,mime_type,size,
                uploaded_by,created) VALUES (?,?,?,?,?,?,?,?)''',
                (image_id, course_id, lesson_id, storage_name, mime_type, len(encoded), user['id'], time.time()))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'id': image_id, 'url': f'/api/courses/markdown-images/{image_id}', 'mime_type': mime_type}


@router.post('/{course_id}/markdown-images', status_code=201)
async def upload_course_markdown_image(course_id: int, file: UploadFile = File(...), user=Depends(administrator)):
    with connect() as db:
        courses.require_access(db, course_id, user, manager=True)
    return await _store_markdown_image(file, course_id, None, user)


@router.post('/lessons/{lesson_id}/markdown-images', status_code=201)
async def upload_markdown_image(lesson_id: int, file: UploadFile = File(...), user=Depends(administrator)):
    with connect() as db:
        lesson, course = courses.require_lesson(db, lesson_id, user, manager=True)
    return await _store_markdown_image(file, course['id'], lesson['id'], user)


@router.get('/markdown-images/{image_id}')
def markdown_image(image_id: str, user=Depends(current_user)):
    if not re.fullmatch(r'[a-f0-9]{32}', image_id):
        raise HTTPException(404, '课程图片不存在')
    with connect() as db:
        image = db.execute('SELECT * FROM course_markdown_images WHERE id=?', (image_id,)).fetchone()
        if not image:
            raise HTTPException(404, '课程图片不存在')
        visible_in_plaza = False
        if image['lesson_id'] is None:
            public = db.execute("""SELECT description FROM live_courses WHERE id=?
                AND publication_status='published'""", (image['course_id'],)).fetchone()
            visible_in_plaza = public is not None and f'/api/courses/markdown-images/{image_id}' in (
                courses.markdown_image_links(public['description']))
        if not visible_in_plaza:
            if image['lesson_id'] is not None:
                courses.require_lesson(db, image['lesson_id'], user)
            else:
                courses.require_access(db, image['course_id'], user)
        path = asset_path(image['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程图片不可用，请联系管理员')
        return FileResponse(path, media_type=image['mime_type'], headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'inline', 'Content-Security-Policy': "default-src 'none'; base-uri 'none'"})


@router.post('/lessons/{lesson_id}/markdown', status_code=201)
def create_markdown_asset(lesson_id: int, payload: MarkdownWrite, user=Depends(administrator)):
    with connect() as db:
        lesson, course = courses.require_lesson(db, lesson_id, user, manager=True)
        db.execute('BEGIN IMMEDIATE')
        return _markdown_asset(db, lesson_id, course['id'], user, payload)


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
        courses.require_lesson(db, asset['lesson_id'], user)
        if asset['kind'] != 'document':
            raise HTTPException(404, '视频请使用课程播放器')
        path = asset_path(asset['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程文件不可用，请联系管理员')
        return FileResponse(path, media_type=asset['mime_type'], filename=asset['original_name'],
                            headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/assets/{asset_id}/markdown', response_class=HTMLResponse)
def markdown_asset(asset_id: int, user=Depends(current_user)):
    with connect() as db:
        asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, '课程资料不存在')
        courses.require_lesson(db, asset['lesson_id'], user)
        if asset['kind'] != 'document' or Path(asset['original_name']).suffix.lower() != '.md':
            raise HTTPException(404, '该课程资料不是 Markdown 文档')
        path = asset_path(asset['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程资料不可用，请联系管理员')
        try:
            source = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError as error:
            raise HTTPException(422, 'Markdown 文档编码无效，请重新上传 UTF-8 文件') from error
        return HTMLResponse(courses.render_lesson_markdown(source), headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; style-src 'none'; img-src 'self'; base-uri 'none'"})


@router.put('/assets/{asset_id}/markdown')
def update_markdown_asset(asset_id: int, payload: MarkdownWrite, user=Depends(administrator)):
    content = payload.markdown.encode('utf-8')
    if not payload.markdown.strip():
        raise HTTPException(422, 'Markdown 正文不能为空')
    maximum = load_config()['course_media']['document_max_mb'] * 1024 * 1024
    if len(content) > maximum:
        raise HTTPException(413, 'Markdown 正文超过课程资料大小限制')
    original_name = None
    if payload.name is not None:
        name = payload.name.strip().replace('\\', '-').replace('/', '-')
        if not name:
            raise HTTPException(422, '文档名称不能为空')
        original_name = name if name.lower().endswith('.md') else f'{name}.md'
        if len(original_name) > 200:
            raise HTTPException(422, '文档名称不能超过 200 个字符')
    old_path = None
    path = None
    temporary = None
    try:
        with connect() as db:
            asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
            if not asset:
                raise HTTPException(404, '课程资料不存在')
            courses.require_access(db, asset['course_id'], user, manager=True)
            if asset['kind'] != 'document' or Path(asset['original_name']).suffix.lower() != '.md':
                raise HTTPException(404, '该课程资料不是 Markdown 文档')
            validate_markdown_images(db, asset['course_id'], asset['lesson_id'], payload.markdown)
            old_path = asset_path(asset['storage_name'])
            storage_name = secrets.token_hex(24) + '.md'
            path = asset_path(storage_name)
            temporary = asset_path(storage_name + '.tmp')
            with temporary.open('xb') as output:
                temporary.chmod(0o600)
                output.write(content)
            os.replace(temporary, path)
            db.execute('BEGIN IMMEDIATE')
            db.execute('''UPDATE course_assets SET storage_name=?,size=?,mime_type=?,original_name=COALESCE(?,original_name)
                WHERE id=?''', (storage_name, len(content), 'text/markdown', original_name, asset_id))
    except OSError as error:
        if temporary:
            temporary.unlink(missing_ok=True)
        if path:
            path.unlink(missing_ok=True)
        raise HTTPException(503, 'Markdown 保存失败，请稍后重试') from error
    except Exception:
        if temporary:
            temporary.unlink(missing_ok=True)
        if path:
            path.unlink(missing_ok=True)
        raise
    try:
        old_path.unlink(missing_ok=True)
    except OSError as error:
        raise HTTPException(503, '正文已更新，但旧文件清理失败，请联系管理员') from error
    return {'ok': True, 'size': len(content)}


@router.post('/assets/{asset_id}/playback')
def create_playback_ticket(asset_id: int, user=Depends(current_user)):
    with connect() as db:
        asset = db.execute('SELECT * FROM course_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(404, '课程视频不存在')
        courses.require_lesson(db, asset['lesson_id'], user)
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
        if not (courses.can_access_course(db, row['course_id'], user) or courses.can_preview_lesson(db, row['lesson_id'])):
            raise HTTPException(404, '播放链接已失效，请重新加入课程')
        path = asset_path(row['storage_name'])
        if not path.is_file():
            raise HTTPException(404, '课程视频不可用，请联系管理员')
        return FileResponse(path, media_type=row['mime_type'], headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/lessons/{lesson_id}')
def get_lesson(lesson_id: int, user=Depends(current_user)):
    with connect() as db:
        lesson, course = courses.require_lesson(db, lesson_id, user)
        result = courses.lesson_view(db, lesson, user)
        result['preview_only'] = not courses.can_access_course(db, course['id'], user)
        return result


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
