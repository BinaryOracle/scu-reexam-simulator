"""Course membership and classroom persistence shared by authenticated routes."""
import time
from fastapi import HTTPException
from app.services.auth import managed_user
from app.services import live_media as media


def manage(course, user):
    return bool(user['is_admin'] and (user['is_superadmin'] or course['owner_id'] == user['id']))


def course(db, cid, user):
    row = db.execute('SELECT * FROM live_courses WHERE id=?', (cid,)).fetchone()
    privileged = row and (manage(row, user) or row['host_id'] == user['id'])
    enrolled = row and row['publication_status'] == 'published' and db.execute(
            '''SELECT 1 FROM live_members WHERE course_id=? AND user_id=? UNION ALL
            SELECT 1 FROM course_self_enrollments WHERE course_id=? AND user_id=? LIMIT 1''',
            (cid, user['id'], cid, user['id'])).fetchone()
    if not row or not (privileged or enrolled):
        raise HTTPException(404, '课程不存在或未加入课程')
    return dict(row)


def lesson(db, lid, user, *, host=False, manager=False):
    row = db.execute('SELECT * FROM live_lessons WHERE id=?', (lid,)).fetchone()
    if not row:
        raise HTTPException(404, '课次不存在')
    parent = course(db, row['course_id'], user)
    if host and parent['host_id'] != user['id']:
        raise HTTPException(403, '仅课程主持人可以操作')
    if manager and not manage(parent, user):
        raise HTTPException(403, '需要课程管理权限')
    return dict(row), parent


def require_live(row):
    if row['status'] != 'live':
        raise HTTPException(409, '课堂尚未开始或已经结束')


def require_present(db, lid, uid):
    row = db.execute('SELECT * FROM live_presence WHERE lesson_id=? AND user_id=?', (lid, uid)).fetchone()
    if not row or row['seen'] < time.time() - media.settings()['presence_seconds']:
        raise HTTPException(409, '请先加入课堂')
    return dict(row)


def validate_people(db, ids, actor):
    for uid in set(ids):
        if uid == actor['id']:
            continue
        managed_user(db, uid, actor)


def recording_status(db, lid):
    row = db.execute('SELECT status FROM live_recordings WHERE lesson_id=? ORDER BY id DESC LIMIT 1', (lid,)).fetchone()
    return row['status'] if row else 'idle'


def lesson_view(db, row, parent, user):
    return {**row, 'course_title': parent['title'], 'is_host': parent['host_id'] == user['id'],
            'can_manage': manage(parent, user), 'configured': media.configured(),
            'materials': [dict(item) for item in db.execute('SELECT id,name,size FROM live_materials WHERE lesson_id=?', (row['id'],))],
            'recordings': [{**dict(item), 'url': f"/api/live/recordings/{item['id']}/file" if item['status'] == 'ready' else None}
                           for item in db.execute('SELECT id,status,error FROM live_recordings WHERE lesson_id=? ORDER BY id', (row['id'],))],
            'recording_status': recording_status(db, row['id'])}
