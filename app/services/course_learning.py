"""Course visibility, enrollment, lesson ordering, and learner progress."""
import time
from fastapi import HTTPException
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from app.services.live import manage


def can_access_course(db, course_id, user):
    """Return whether an enabled account has course membership or management access."""
    row = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not row:
        return False
    if manage(row, user) or row['host_id'] == user['id']:
        return True
    if row['publication_status'] != 'published':
        return False
    return bool(db.execute(
        '''SELECT 1 FROM live_members WHERE course_id=? AND user_id=? UNION ALL
        SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=? LIMIT 1''',
        (course_id, user['id'], course_id, user['id'])).fetchone())


def is_enrolled(db, course_id, user):
    """Return whether the user joined as a learner, independently of management access."""
    course = db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not course:
        return False
    if db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?',
                  (course_id, user['id'])).fetchone():
        return True
    return bool(course['host_id'] != user['id'] and not manage(course, user) and db.execute(
        'SELECT 1 FROM live_members WHERE course_id=? AND user_id=?', (course_id, user['id'])).fetchone())


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
    course = require_access(db, lesson['course_id'], user, manager=manager)
    return lesson, course


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
    return {**row, 'items': items, 'progress': dict(progress) if progress else {
        'position_seconds': 0, 'completed': 0}}


def render_lesson_markdown(text):
    """Render lesson Markdown without raw HTML or remotely loaded images."""
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough']).disable('image')
    renderer.use(dollarmath_plugin, allow_digits=True, allow_space=True)
    tokens = renderer.parse(text or '')
    for token in tokens:
        for child in token.children or []:
            if child.type == 'link_open':
                child.attrSet('target', '_blank')
                child.attrSet('rel', 'noopener noreferrer')
    return renderer.renderer.render(tokens, renderer.options, {})


def course_detail(db, course_id, user):
    course = require_access(db, course_id, user)
    sections = []
    for section in db.execute('SELECT * FROM course_sections WHERE course_id=? ORDER BY position,id', (course_id,)):
        lessons = [lesson_view(db, dict(row), user) for row in db.execute(
            'SELECT * FROM course_lessons WHERE section_id=? ORDER BY position,id', (section['id'],))]
        sections.append({**dict(section), 'lessons': lessons})
    host = db.execute('SELECT username FROM users WHERE id=?', (course['host_id'],)).fetchone()
    detail = {**course, 'host_name': host['username'], 'sections': sections,
            'progress_summary': progress_summary(db, course_id, user['id']),
            'is_enrolled': is_enrolled(db, course_id, user),
            'can_manage': manage(course, user),
            'is_self_enrolled': bool(db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=?',
                                                (course_id, user['id'])).fetchone())}
    if detail['can_manage']:
        detail['member_ids'] = [row[0] for row in db.execute(
            'SELECT user_id FROM live_members WHERE course_id=?', (course_id,))]
        detail['publish_issues'] = publish_issues(db, course_id)
    return detail


def public_preview(db, course_id):
    """Return published public course metadata without member or lesson resource data."""
    course = db.execute('''SELECT c.id,c.title,c.description,u.username host_name
        FROM live_courses c JOIN users u ON u.id=c.host_id
        WHERE c.id=? AND c.publication_status='published' AND c.access_mode='public' ''',
        (course_id,)).fetchone()
    if not course:
        raise HTTPException(404, '公开课程不存在')
    sections = []
    lessons_total = 0
    content_kinds = set()
    for section in db.execute('SELECT id,title,position FROM course_sections WHERE course_id=? ORDER BY position,id',
                              (course_id,)):
        lessons = []
        for lesson in db.execute('''SELECT id,title,description,position FROM course_lessons
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
            lessons.append({**dict(lesson), 'content_kinds': kinds,
                            'live_starts_at': live_session['starts_at'] if live_session else None,
                            'live_status': live_session['status'] if live_session else None})
            content_kinds.update(kinds)
            lessons_total += 1
        if lessons:
            sections.append({'title': section['title'], 'position': section['position'], 'lessons': lessons})
    return {**dict(course), 'sections': sections, 'lesson_count': lessons_total,
            'content_kinds': sorted(content_kinds)}


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
