"""Coding catalog visibility, authoring and version-checked administrator moderation."""
import json
import re
import secrets
import time
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.services.problem_content import render_statement

SELECT = '''SELECT q.*,s.title AS stage_title,s.active AS stage_active,s.position AS stage_position,
    u.username AS owner_name,u.is_admin AS owner_admin FROM coding_questions q
    JOIN coding_stages s ON s.id=q.stage_id LEFT JOIN users u ON u.id=q.owner_user_id'''
EDIT_FIELDS = ('stage_id', 'title', 'topic', 'difficulty', 'stars', 'position', 'statement', 'samples',
               'reference_code', 'reference_language', 'source_url', 'remote_problem_id', 'judge_mode')


def get_question(db, qid):
    row = db.execute(SELECT + ' WHERE q.id=? AND q.deleted=0', (qid,)).fetchone()
    if row is None:
        raise HTTPException(404, '题目不存在或已删除')
    return row


def accessible(row, uid):
    return bool(row and not row['deleted'] and (row['owner_user_id'] == uid or
                (row['visibility'] == 'public' and row['active'] and row['stage_active'])))


def require_access(db, qid, uid, *, practice=False):
    row = get_question(db, qid)
    if not accessible(row, uid) or (practice and not (row['active'] and row['stage_active'])):
        raise HTTPException(404, '题目不存在或当前不可用')
    return row


def admin_access(row, actor):
    return bool((row['visibility'] == 'public' or row['review_status'] == 'pending') and
                (not row['owner_admin'] or actor['is_superadmin']))


def editable(db, qid, actor, *, admin=False):
    row = get_question(db, qid)
    if (admin and not admin_access(row, actor)) or (not admin and row['owner_user_id'] != actor['id']):
        raise HTTPException(404, '题目不存在')
    return row


def check_version(row, version):
    if row['version'] != version:
        raise HTTPException(409, '题目已被修改，请刷新后重试')


def serialize(db, row, uid):
    result = {key: row[key] for key in (*EDIT_FIELDS, 'id', 'version', 'owner_user_id', 'visibility',
              'review_status', 'review_reason', 'stage_title')}
    result['samples'] = json.loads(row['samples'])
    result['source_info'] = json.loads(row['source_info'])
    result['statement_html'] = render_statement(row['statement'])
    result['active'] = bool(row['active'])
    result['solved'] = bool(db.execute("""SELECT 1 FROM coding_submissions WHERE user_id=? AND question_id=?
        AND question_content_version=? AND status='Accepted' LIMIT 1""", (uid, row['id'], row['content_version'])).fetchone())
    result['favorited'] = bool(db.execute('SELECT 1 FROM coding_favorites WHERE user_id=? AND question_id=?',
                                          (uid, row['id'])).fetchone())
    result['content_available'] = bool(row['statement'].strip())
    result['content_notice'] = '' if result['content_available'] else '尚未缓存完整题面，请打开原题链接；管理员可重新导入洛谷题面。'
    return result


def list_questions(db, user, *, stage_id='', q='', mine=False, status=None, view='roadmap', page=1, page_size=20):
    clauses, values = ['q.deleted=0'], []
    if status is not None:
        clauses.append("(q.visibility='public' OR q.review_status='pending')")
        if not user['is_superadmin']:
            clauses.append('(u.is_admin=0 OR u.id IS NULL)')
        if status and status != 'all':
            clauses.append('q.visibility=?' if status == 'public' else 'q.review_status=?')
            values.append(status)
    elif mine or view == 'mine':
        clauses.append('q.owner_user_id=?'); values.append(user['id'])
    else:
        clauses.append("q.active=1 AND s.active=1 AND (q.visibility='public' OR q.owner_user_id=?)")
        values.append(user['id'])
        if view == 'solved':
            clauses.append("EXISTS (SELECT 1 FROM coding_submissions solved WHERE solved.user_id=? AND solved.question_id=q.id AND solved.question_content_version=q.content_version AND solved.status='Accepted')")
            values.append(user['id'])
        elif view == 'failed':
            clauses.append("EXISTS (SELECT 1 FROM coding_submissions failed WHERE failed.user_id=? AND failed.question_id=q.id AND failed.question_content_version=q.content_version AND failed.status IN ('Wrong Answer','Output Limit Exceeded','Time Limit Exceeded','Memory Limit Exceeded','Runtime Error','Compile Error'))")
            clauses.append("NOT EXISTS (SELECT 1 FROM coding_submissions solved WHERE solved.user_id=? AND solved.question_id=q.id AND solved.question_content_version=q.content_version AND solved.status='Accepted')")
            values.extend([user['id'], user['id']])
        elif view == 'favorites':
            clauses.append('EXISTS (SELECT 1 FROM coding_favorites favorite WHERE favorite.user_id=? AND favorite.question_id=q.id)')
            values.append(user['id'])
    if stage_id:
        clauses.append('q.stage_id=?'); values.append(stage_id)
    if q:
        clauses.append('(instr(lower(q.title),lower(?))>0 OR instr(lower(q.topic),lower(?))>0)')
        values.extend([q, q])
    where = ' WHERE ' + ' AND '.join(clauses)
    total = db.execute('SELECT COUNT(*) FROM (' + SELECT + where + ')', values).fetchone()[0]
    rows = db.execute(SELECT + where + ' ORDER BY s.position,s.id,q.position,q.id LIMIT ? OFFSET ?',
                      (*values, page_size, (page - 1) * page_size)).fetchall()
    items = [serialize(db, row, user['id']) for row in rows]
    if status is not None:
        for item, row in zip(items, rows):
            item['owner_name'] = row['owner_name'] or '官方题库'
    return dict(items=items, total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)


def validate_item(db, data, *, admin=False):
    item = {key: data[key] for key in EDIT_FIELDS}
    stage = db.execute('SELECT * FROM coding_stages WHERE id=?', (item['stage_id'],)).fetchone()
    if stage is None or (not admin and not stage['active']):
        raise HTTPException(422, '请选择有效的启用阶段')
    item['title'] = item['title'].strip()
    if not item['title']:
        raise HTTPException(422, '题目名称不能为空')
    if item['source_url']:
        try:
            url = urlsplit(item['source_url'])
        except ValueError as error:
            raise HTTPException(422, '来源地址须为有效的 HTTP/HTTPS 网页链接') from error
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise HTTPException(422, '来源地址须为 HTTP/HTTPS 网页链接')
    item['remote_problem_id'] = item['remote_problem_id'].strip().upper()
    if item['judge_mode'] == 'luogu' and not re.fullmatch(r'[A-Z][A-Z0-9_-]{0,31}', item['remote_problem_id']):
        raise HTTPException(422, '洛谷评测须填写有效题目编号')
    if item['judge_mode'] == 'samples':
        if not item['samples']:
            raise HTTPException(422, '样例评测题至少需要一组公开输入/输出样例')
        item['remote_problem_id'] = ''
    item['samples'] = json.dumps(item['samples'], ensure_ascii=False)
    return item


def event(db, qid, actor, name, version, reason=''):
    db.execute('INSERT INTO coding_review_events(question_id,actor_id,event,version,reason,created) VALUES (?,?,?,?,?,?)',
               (qid, actor['id'], name, version, reason, time.time()))


def create_question(db, user, data, *, admin=False):
    item = validate_item(db, data, admin=admin)
    now = time.time()
    cursor = db.execute(f'''INSERT INTO coding_questions({','.join(EDIT_FIELDS)},owner_user_id,visibility,review_status,active,created,updated)
        VALUES ({','.join('?' for _ in EDIT_FIELDS)},?,?,?,?,?,?)''',
        (*(item[key] for key in EDIT_FIELDS), None if admin else user['id'], 'public' if admin else 'private',
         'approved' if admin else 'draft', data.get('active', True), now, now))
    event(db, cursor.lastrowid, user, 'create', 1)
    return serialize(db, get_question(db, cursor.lastrowid), user['id'])


def update_question(db, user, qid, data, *, admin=False):
    row = editable(db, qid, user, admin=admin)
    check_version(row, data['version'])
    merged = {key: row[key] for key in EDIT_FIELDS}
    merged['samples'] = json.loads(row['samples'])
    merged.update({key: value for key, value in data.items() if key in EDIT_FIELDS})
    item = validate_item(db, merged, admin=admin)
    public = admin and row['visibility'] == 'public'
    review_status = row['review_status'] if admin else 'draft'
    content_changed = any(item[key] != row[key] for key in ('statement', 'samples', 'judge_mode', 'remote_problem_id'))
    db.execute(f'''UPDATE coding_questions SET {','.join(key+'=?' for key in EDIT_FIELDS)},visibility=?,review_status=?,
        review_reason='',reviewed_by=NULL,reviewed_at=NULL,active=?,version=version+1,
        content_version=content_version+?,updated=? WHERE id=?''',
        (*(item[key] for key in EDIT_FIELDS), 'public' if public else 'private', review_status,
         data.get('active', bool(row['active'])), int(content_changed), time.time(), qid))
    event(db, qid, user, 'edit', row['version'] + 1)
    return serialize(db, get_question(db, qid), user['id'])


def delete_question(db, actor, qid, *, admin=False):
    row = editable(db, qid, actor, admin=admin)
    # Tombstones retain submitted code, moderation, fixed assignments and reward references.
    db.execute("UPDATE coding_questions SET deleted=1,active=0,visibility='private',version=version+1,updated=? WHERE id=?", (time.time(), qid))
    event(db, qid, actor, 'delete', row['version'] + 1)


def submit(db, actor, qid, version):
    row = editable(db, qid, actor)
    check_version(row, version)
    if row['review_status'] == 'pending' or row['visibility'] == 'public':
        raise HTTPException(409, '题目已在审核中或已公开')
    db.execute("UPDATE coding_questions SET review_status='pending',review_reason='',version=version+1,updated=? WHERE id=?", (time.time(), qid))
    event(db, qid, actor, 'submit', version + 1)
    return serialize(db, get_question(db, qid), actor['id'])


def review(db, actor, qid, version, approve, reason):
    row = editable(db, qid, actor, admin=True)
    check_version(row, version)
    if row['review_status'] != 'pending':
        raise HTTPException(409, '此题不在待审核状态')
    reason = reason.strip()
    if not approve and not reason:
        raise HTTPException(422, '请填写驳回原因')
    db.execute('''UPDATE coding_questions SET visibility=?,review_status=?,review_reason=?,reviewed_by=?,reviewed_at=?,
        version=version+1,updated=? WHERE id=?''',
        ('public' if approve else 'private', 'approved' if approve else 'rejected', reason, actor['id'], time.time(), time.time(), qid))
    event(db, qid, actor, 'approve' if approve else 'reject', version + 1, reason)
    if approve:
        from app.services.coding_practice import reward_contribution
        reward_contribution(db, row)
    return serialize(db, get_question(db, qid), actor['id'])


def stages(db):
    return [dict(row) | {'active': bool(row['active'])} for row in db.execute('SELECT * FROM coding_stages ORDER BY position,id')]


def save_stage(db, data, stage_id=None):
    if stage_id is None:
        stage_id = 'custom-' + secrets.token_hex(8)
        db.execute('INSERT INTO coding_stages(id,title,description,position,active) VALUES (?,?,?,?,?)',
                   (stage_id, data['title'].strip(), data['description'], data['position'], data['active']))
    else:
        if not db.execute('SELECT 1 FROM coding_stages WHERE id=?', (stage_id,)).fetchone():
            raise HTTPException(404, '阶段不存在')
        if data:
            db.execute('UPDATE coding_stages SET ' + ','.join(key+'=?' for key in data) + ' WHERE id=?', (*data.values(), stage_id))
    row = db.execute('SELECT * FROM coding_stages WHERE id=?', (stage_id,)).fetchone()
    return dict(row) | {'active': bool(row['active'])}


def delete_stage(db, stage_id):
    if not db.execute('SELECT 1 FROM coding_stages WHERE id=?', (stage_id,)).fetchone():
        raise HTTPException(404, '阶段不存在')
    if db.execute('SELECT 1 FROM coding_questions WHERE stage_id=? LIMIT 1', (stage_id,)).fetchone():
        raise HTTPException(409, '阶段仍有题目或历史记录，请移动题目或停用阶段')
    db.execute('DELETE FROM coding_stages WHERE id=?', (stage_id,))
