"""Course visibility, enrollment, lesson ordering, and learner progress."""
import time
import re
from html.parser import HTMLParser
from html import unescape
from fastapi import HTTPException
from markdown_it import MarkdownIt
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from app.services.live import manage


class _TextExtractor(HTMLParser):
    """Collect rendered text for compact catalog summaries."""
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def markdown_summary(text, limit=180):
    """Return a readable plain-text Markdown summary capped at ``limit`` chars."""
    parser = _TextExtractor()
    parser.feed(render_lesson_markdown(text or ''))
    plain = ' '.join(parser.parts)
    plain = ' '.join(unescape(plain).split())
    return plain if len(plain) <= limit else plain[:limit - 1].rstrip() + '…'


def can_access_course(db, course_id, user):
    """Return whether an enabled account has course membership or management access."""
    row = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not row:
        return False
    if manage(row, user) or row['host_id'] == user['id']:
        return True
    if row['publication_status'] != 'published':
        return False
    if row['access_mode'] == 'public':
        return True
    return bool(db.execute('''SELECT 1 WHERE
        EXISTS (SELECT 1 FROM live_members WHERE course_id=? AND user_id=?) OR
        (EXISTS (SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?) AND
         NOT EXISTS (SELECT 1 FROM course_purchases WHERE course_id=? AND user_id=?)) OR
        EXISTS (SELECT 1 FROM course_purchases WHERE course_id=? AND user_id=?
            AND (access_expires_at IS NULL OR access_expires_at>?))''',
        (course_id, user['id'], course_id, user['id'], course_id, user['id'],
         course_id, user['id'], time.time())).fetchone())


def is_enrolled(db, course_id, user):
    """Return whether the user joined as a learner, independently of management access."""
    course = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not course:
        return False
    if db.execute('''SELECT 1 FROM course_purchases WHERE course_id=? AND user_id=?
        AND (access_expires_at IS NULL OR access_expires_at>?)''',
                  (course_id, user['id'], time.time())).fetchone():
        return True
    if db.execute('''SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?
        AND (?='public' OR NOT EXISTS (SELECT 1 FROM course_purchases WHERE course_id=? AND user_id=?))''',
                  (course_id, user['id'], course['access_mode'], course_id, user['id'])).fetchone():
        return True
    return bool(course['host_id'] != user['id'] and not manage(course, user) and db.execute(
        'SELECT 1 FROM live_members WHERE course_id=? AND user_id=?', (course_id, user['id'])).fetchone())


def is_removed_from_library(db, course_id, user_id):
    """Whether this learner hid a course without giving up membership or progress."""
    return bool(db.execute('SELECT 1 FROM course_library_hidden WHERE course_id=? AND user_id=?',
                           (course_id, user_id)).fetchone())


def require_access(db, course_id, user, *, manager=False):
    row = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not row or not can_access_course(db, course_id, user):
        raise HTTPException(404, '课程不存在或尚未加入')
    if manager and not manage(row, user):
        raise HTTPException(403, '需要课程管理权限')
    return dict(row)


def lesson_row(db, lesson_id):
    row = db.execute('SELECT * FROM course_lessons WHERE id=?', (lesson_id,)).fetchone()
    if not row:
        raise HTTPException(404, '课时不存在')
    return dict(row)


def require_lesson(db, lesson_id, user, *, manager=False):
    lesson = lesson_row(db, lesson_id)
    if not manager and can_preview_lesson(db, lesson_id):
        course = dict(db.execute('SELECT * FROM live_courses WHERE id=?', (lesson['course_id'],)).fetchone())
        return lesson, course
    course = require_access(db, lesson['course_id'], user, manager=manager)
    return lesson, course


def can_preview_lesson(db, lesson_id):
    """Preview requires a published course and both the chapter and lesson switches."""
    return bool(db.execute('''SELECT 1 FROM course_lessons l
        JOIN course_sections s ON s.id=l.section_id JOIN live_courses c ON c.id=l.course_id
        WHERE l.id=? AND l.preview_enabled=1 AND s.preview_enabled=1
        AND c.publication_status='published' ''', (lesson_id,)).fetchone())


def progress_summary(db, course_id, user_id):
    row = db.execute('''SELECT COUNT(*) total,COALESCE(SUM(p.completed),0) completed
        FROM course_lessons l LEFT JOIN course_progress p ON p.lesson_id=l.id AND p.user_id=?
        WHERE l.course_id=?''', (user_id, course_id)).fetchone()
    return {'total': row['total'], 'completed': row['completed'],
            'percent': round(row['completed'] * 100 / row['total']) if row['total'] else 0}


def lesson_view(db, row, user):
    progress = db.execute('SELECT position_seconds,completed FROM course_progress WHERE lesson_id=? AND user_id=?',
                          (row['id'], user['id'])).fetchone()
    items = []
    for item in db.execute('SELECT * FROM course_lesson_items WHERE lesson_id=? ORDER BY position,id', (row['id'],)):
        value = dict(item)
        if item['kind'] == 'live' and item['live_lesson_id']:
            live = db.execute('SELECT id,title,description,starts_at,status FROM live_lessons WHERE id=?',
                              (item['live_lesson_id'],)).fetchone()
            value['live'] = dict(live) if live else None
            value['recordings'] = [dict(recording) for recording in db.execute(
                'SELECT id,status FROM live_recordings WHERE lesson_id=? ORDER BY id',
                (item['live_lesson_id'],))]
        elif item['asset_id']:
            asset = db.execute('SELECT id,kind,original_name,size,mime_type FROM course_assets WHERE id=?',
                               (item['asset_id'],)).fetchone()
            value['asset'] = dict(asset) if asset else None
        items.append(value)
    return {**row, 'description_html': render_lesson_markdown(row.get('description', '')),
            'description_summary': markdown_summary(row.get('description', '')),
            'items': items, 'progress': dict(progress) if progress else {
        'position_seconds': 0, 'completed': 0}}


MARKDOWN_IMAGE_PATH = re.compile(r'/api/courses/markdown-images/([a-f0-9]{32})')
COURSE_PRACTICE_PATH = re.compile(r'/#view=coding/question/[1-9][0-9]*')


def _lesson_fold(renderer, tokens, idx, _options, _env):
    token = tokens[idx]
    if token.nesting == -1:
        return '</details>\n'
    kind = token.info.strip()
    title = {'code': '书中原代码', 'practice': '动手练习'}[kind]
    return f'<details class="course-fold course-fold-{kind}"><summary>{title}</summary>\n'


def _markdown_renderer():
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough'])
    renderer.use(dollarmath_plugin, allow_digits=True, allow_space=True)
    for kind in ('code', 'practice'):
        renderer.use(container_plugin, kind, validate=lambda info, _markup, kind=kind: info.strip() == kind,
                     render=_lesson_fold)
    return renderer


def markdown_image_links(text):
    """Yield image destinations parsed with the same rules as the rendered document."""
    for token in _markdown_renderer().parse(text or ''):
        for child in token.children or []:
            if child.type == 'image':
                yield child.attrGet('src') or ''


def render_lesson_markdown(text):
    """Render lesson Markdown without raw HTML or remotely loaded images."""
    renderer = _markdown_renderer()
    tokens = renderer.parse(text or '')
    for token in tokens:
        for child in token.children or []:
            if child.type == 'link_open':
                if COURSE_PRACTICE_PATH.fullmatch(child.attrGet('href') or ''):
                    child.attrSet('class', 'course-practice-link')
                else:
                    child.attrSet('target', '_blank')
                    child.attrSet('rel', 'noopener noreferrer')
            elif child.type == 'image' and not MARKDOWN_IMAGE_PATH.fullmatch(child.attrGet('src') or ''):
                child.type = 'text'
                child.content = child.content or child.attrGet('alt') or ''
                child.attrs = None
    return renderer.renderer.render(tokens, renderer.options, {})


def course_detail(db, course_id, user):
    course = require_access(db, course_id, user)
    sections = []
    for section in db.execute('SELECT * FROM course_sections WHERE course_id=? ORDER BY position,id', (course_id,)):
        lessons = [lesson_view(db, dict(row), user) for row in db.execute(
            'SELECT * FROM course_lessons WHERE section_id=? ORDER BY position,id', (section['id'],))]
        sections.append({**dict(section), 'lessons': lessons})
    host = db.execute('SELECT username FROM users WHERE id=?', (course['host_id'],)).fetchone()
    detail = {key: value for key, value in course.items() if key != 'cover_asset_id'}
    detail.update({'host_name': host['username'],
            'description_html': render_lesson_markdown(course.get('description', '')),
            'description_summary': markdown_summary(course.get('description', '')),
            'cover_url': f"/api/courses/{course_id}/cover" if course.get('cover_kind') == 'upload' else None,
            'sections': sections,
            'progress_summary': progress_summary(db, course_id, user['id']),
            'is_enrolled': is_enrolled(db, course_id, user),
            'is_removed_from_library': is_removed_from_library(db, course_id, user['id']),
            'can_manage': manage(course, user),
            'is_self_enrolled': bool(db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?',
                                                (course_id, user['id'])).fetchone())})
    if detail['can_manage']:
        detail['member_ids'] = [row[0] for row in db.execute(
            'SELECT user_id FROM live_members WHERE course_id=?', (course_id,))]
        if course['access_mode'] == 'public':
            learners = [dict(row) for row in db.execute('''SELECT u.username,e.enrolled_at FROM course_self_enrollments e
                JOIN users u ON u.id=e.user_id WHERE e.course_id=? ORDER BY e.enrolled_at DESC,u.username''',
                (course_id,))]
            detail['enrollment_summary'] = {'joined_count': len(learners), 'students': learners}
        elif course['access_mode'] == 'roster':
            learners = [{**dict(row), 'started': bool(row['started'])} for row in db.execute('''SELECT u.username,
                EXISTS(SELECT 1 FROM course_progress p JOIN course_lessons l ON l.id=p.lesson_id
                    WHERE l.course_id=? AND p.user_id=u.id) AS started
                FROM live_members m JOIN users u ON u.id=m.user_id
                WHERE m.course_id=? AND m.user_id<>? ORDER BY u.username''',
                (course_id, course_id, course['host_id']))]
            detail['enrollment_summary'] = {'assigned_count': len(learners),
                'joined_count': sum(bool(row['started']) for row in learners), 'students': learners}
        else:
            learners = [dict(row) for row in db.execute('''SELECT u.username,p.purchased_at,p.access_expires_at
                FROM course_purchases p JOIN users u ON u.id=p.user_id
                WHERE p.course_id=? ORDER BY p.purchased_at DESC,u.username''', (course_id,))]
            detail['enrollment_summary'] = {'purchased_count': len(learners), 'students': learners}
        detail['publish_issues'] = publish_issues(db, course_id)
    return detail


def public_preview(db, course_id, user=None):
    """Return published public course metadata without member or lesson resource data."""
    course = db.execute('''SELECT c.id,c.title,c.description,c.access_mode,c.points_price,c.points_access_days,c.cover_kind,c.cover_value,c.cover_asset_id,u.username host_name
        FROM live_courses c JOIN users u ON u.id=c.host_id
        WHERE c.id=? AND c.publication_status='published' AND (c.access_mode IN ('public','points') OR EXISTS (
            SELECT 1 FROM course_lessons l JOIN course_sections s ON s.id=l.section_id
            WHERE l.course_id=c.id AND l.preview_enabled=1 AND s.preview_enabled=1)) ''',
        (course_id,)).fetchone()
    if not course:
        raise HTTPException(404, '公开课程不存在')
    sections = []
    lessons_total = 0
    content_kinds = set()
    full_access = user is not None and can_access_course(db, course_id, user)
    for section in db.execute('SELECT id,title,position,preview_enabled FROM course_sections WHERE course_id=? ORDER BY position,id',
                              (course_id,)):
        lessons = []
        for lesson in db.execute('''SELECT id,title,description,position,preview_enabled FROM course_lessons
            WHERE section_id=? ORDER BY position,id''', (section['id'],)):
            kinds = [row['kind'] for row in db.execute('''SELECT i.kind FROM course_lesson_items i
                LEFT JOIN course_assets a ON a.id=i.asset_id
                LEFT JOIN live_lessons l ON l.id=i.live_lesson_id
                WHERE i.lesson_id=? AND ((i.kind='live' AND l.id IS NOT NULL) OR
                    (i.kind IN ('video','document') AND a.id IS NOT NULL)) ORDER BY i.position,i.id''',
                (lesson['id'],))]
            live_session = db.execute('''SELECT l.starts_at,l.status FROM course_lesson_items i
                JOIN live_lessons l ON l.id=i.live_lesson_id WHERE i.lesson_id=? AND i.kind='live'
                ORDER BY i.position LIMIT 1''', (lesson['id'],)).fetchone()
            previewable = bool(section['preview_enabled'] and lesson['preview_enabled'])
            readable = full_access or previewable
            description = lesson['description'] if readable else ''
            lessons.append({**dict(lesson), 'description': description,
                            'can_preview': previewable, 'locked': not readable,
                            'description_html': render_lesson_markdown(description),
                            'description_summary': markdown_summary(description),
                            'content_kinds': kinds,
                            'live_starts_at': live_session['starts_at'] if live_session else None,
                            'live_status': live_session['status'] if live_session else None})
            content_kinds.update(kinds)
            lessons_total += 1
        if lessons:
            sections.append({**dict(section), 'lessons': lessons})
    return {key: value for key, value in {
            **dict(course), 'description_html': render_lesson_markdown(course['description']),
            'description_summary': markdown_summary(course['description']),
            'cover_url': f"/api/courses/{course_id}/cover" if course['cover_kind'] == 'upload' else None,
            'sections': sections, 'lesson_count': lessons_total,
            'content_kinds': sorted(content_kinds)}.items() if key != 'cover_asset_id'}


def resume_lesson(db, course_id, user_id):
    """Select the learner's active lesson, falling back to the first unfinished lesson."""
    resume = db.execute('''SELECT l.id FROM course_progress p
        JOIN course_lessons l ON l.id=p.lesson_id
        JOIN course_sections s ON s.id=l.section_id
        WHERE l.course_id=? AND p.user_id=? AND p.completed=0 AND p.position_seconds>0
        ORDER BY p.updated DESC,s.position,l.position,l.id LIMIT 1''', (course_id, user_id)).fetchone()
    if not resume:
        resume = db.execute('''SELECT l.id FROM course_lessons l
            JOIN course_sections s ON s.id=l.section_id
            LEFT JOIN course_progress p ON p.lesson_id=l.id AND p.user_id=?
            WHERE l.course_id=? AND COALESCE(p.completed,0)=0
            ORDER BY s.position,l.position,l.id LIMIT 1''', (user_id, course_id)).fetchone()
    if not resume:
        resume = db.execute('''SELECT l.id FROM course_lessons l
            JOIN course_sections s ON s.id=l.section_id WHERE l.course_id=?
            ORDER BY s.position,l.position,l.id LIMIT 1''', (course_id,)).fetchone()
    return resume['id'] if resume else None


def publish_issues(db, course_id):
    """Return the shared list of course-content requirements still blocking publication."""
    issues = []
    sections = db.execute('SELECT id,title FROM course_sections WHERE course_id=? ORDER BY position,id',
                          (course_id,)).fetchall()
    if not sections:
        issues.append('至少添加一个章节')
    lessons = db.execute('''SELECT id,title FROM course_lessons WHERE course_id=? ORDER BY position,id''',
                          (course_id,)).fetchall()
    if not lessons:
        issues.append('至少添加一个课时')
    for lesson in lessons:
        valid = db.execute('''SELECT 1 FROM course_lesson_items i
            LEFT JOIN course_assets a ON a.id=i.asset_id
            LEFT JOIN live_lessons l ON l.id=i.live_lesson_id
            WHERE i.lesson_id=? AND ((i.kind='live' AND l.id IS NOT NULL) OR
                (i.kind IN ('video','document') AND a.id IS NOT NULL)) LIMIT 1''',
            (lesson['id'],)).fetchone()
        if not valid:
            issues.append(f'为课时“{lesson["title"]}”添加可学习内容')
    return issues


def validate_publish_ready(db, course_id):
    """Reject publication until every visible course lesson has usable content."""
    issues = publish_issues(db, course_id)
    if issues:
        raise HTTPException(422, f'发布前请{issues[0]}')


def reorder_lessons(db, section_id, lesson_ids):
    rows = [row['id'] for row in db.execute('SELECT id FROM course_lessons WHERE section_id=? ORDER BY position,id',
                                            (section_id,))]
    if set(rows) != set(lesson_ids) or len(rows) != len(lesson_ids):
        raise HTTPException(422, '课时排序必须包含本章节的全部课时')
    for position, lesson_id in enumerate(lesson_ids):
        db.execute('UPDATE course_lessons SET position=? WHERE id=?', (position, lesson_id))


def compact_positions(db, table, parent_column, parent_id):
    """Normalize ordered records after deleting one item without violating unique positions."""
    rows = [row['id'] for row in db.execute(
        f'SELECT id FROM {table} WHERE {parent_column}=? ORDER BY position,id', (parent_id,))]
    if not rows:
        return
    offset = db.execute(f'SELECT COALESCE(MAX(position),-1)+? FROM {table} WHERE {parent_column}=?',
                        (len(rows) + 1, parent_id)).fetchone()[0]
    db.execute(f'UPDATE {table} SET position=position+? WHERE {parent_column}=?', (offset, parent_id))
    for position, item_id in enumerate(rows):
        db.execute(f'UPDATE {table} SET position=? WHERE id=?', (position, item_id))


def reorder_items(db, lesson_id, items):
    existing = {row['id']: row for row in db.execute(
        'SELECT * FROM course_lesson_items WHERE lesson_id=?', (lesson_id,))}
    submitted = [item['id'] for item in items if item.get('id') is not None]
    if len(submitted) != len(set(submitted)) or set(submitted) != set(existing):
        raise HTTPException(422, '内容排序必须保留本课时现有项目')
    for item in items:
        item_id = item.get('id')
        if item_id is None:
            if item['kind'] != 'live' or not item.get('live_lesson_id'):
                raise HTTPException(422, '请先创建直播课次或上传课程资料')
            live = db.execute('SELECT course_id,course_lesson_id FROM live_lessons WHERE id=?',
                              (item['live_lesson_id'],)).fetchone()
            if not live or live['course_id'] != existing_course(db, lesson_id) or live['course_lesson_id'] != lesson_id:
                raise HTTPException(422, '直播课次不属于当前课时')
        elif item['kind'] != existing[item_id]['kind']:
            raise HTTPException(422, '不能修改已创建内容的类型')
    offset = db.execute('SELECT COALESCE(MAX(position),-1)+? FROM course_lesson_items WHERE lesson_id=?',
                        (len(items) + 1, lesson_id)).fetchone()[0]
    db.execute('UPDATE course_lesson_items SET position=position+? WHERE lesson_id=?', (offset, lesson_id))
    for position, item in enumerate(items):
        if item.get('id') is None:
            db.execute('INSERT INTO course_lesson_items(lesson_id,kind,position,live_lesson_id) VALUES (?,?,?,?)',
                       (lesson_id, 'live', position, item['live_lesson_id']))
        else:
            db.execute('UPDATE course_lesson_items SET position=? WHERE id=?', (position, item['id']))


def existing_course(db, lesson_id):
    row = db.execute('SELECT course_id FROM course_lessons WHERE id=?', (lesson_id,)).fetchone()
    return row['course_id'] if row else None


def update_progress(db, lesson_id, user_id, position_seconds, completed):
    db.execute('''INSERT INTO course_progress(lesson_id,user_id,position_seconds,completed,updated)
        VALUES (?,?,?,?,?) ON CONFLICT(lesson_id,user_id) DO UPDATE SET
        position_seconds=excluded.position_seconds,completed=MAX(course_progress.completed,excluded.completed),updated=excluded.updated''',
        (lesson_id, user_id, position_seconds, int(completed), time.time()))
    return dict(db.execute('SELECT position_seconds,completed,updated FROM course_progress WHERE lesson_id=? AND user_id=?',
                           (lesson_id, user_id)).fetchone())
