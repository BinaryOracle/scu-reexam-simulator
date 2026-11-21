"""Coding catalog visibility, authoring and version-checked administrator moderation."""
import json
import re
import secrets
import time
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.services import coding_platforms
from app.services.problem_content import render_statement
from app.services.question_markdown import bind

SELECT = '''SELECT q.*,s.title AS stage_title,s.active AS stage_active,s.position AS stage_position,
    u.username AS owner_name,u.is_admin AS owner_admin FROM coding_questions q
    JOIN coding_stages s ON s.id=q.stage_id LEFT JOIN users u ON u.id=q.owner_user_id'''
EDIT_FIELDS = ('stage_id', 'title', 'topic', 'difficulty', 'stars', 'position', 'statement', 'samples',
               'reference_code', 'reference_language', 'starter_codes', 'source_url', 'remote_problem_id',
               'remote_platform', 'judge_mode', 'source_info')


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


def _shift_for_insert(db, stage_id, position, *, exclude_id=None):
    """Make room for a question at a stage-local position before writing it."""
    params = [stage_id, position]
    condition = 'stage_id=? AND deleted=0 AND position>=?'
    if exclude_id is not None:
        condition += ' AND id<>?'
        params.append(exclude_id)
    db.execute(f'UPDATE coding_questions SET position=position+1 WHERE {condition}', params)


def _move_position(db, row, item, qid):
    """Keep stage-local positions ordered when an existing question is moved."""
    old_stage, old_position = row['stage_id'], row['position']
    new_stage, new_position = item['stage_id'], item['position']
    if old_stage == new_stage:
        if new_position < old_position:
            db.execute('''UPDATE coding_questions SET position=position+1
                WHERE stage_id=? AND deleted=0 AND id<>? AND position>=? AND position<?''',
                       (old_stage, qid, new_position, old_position))
        elif new_position > old_position:
            db.execute('''UPDATE coding_questions SET position=position-1
                WHERE stage_id=? AND deleted=0 AND id<>? AND position>? AND position<=?''',
                       (old_stage, qid, old_position, new_position))
        return
    db.execute('''UPDATE coding_questions SET position=position-1
        WHERE stage_id=? AND deleted=0 AND position>?''', (old_stage, old_position))
    _shift_for_insert(db, new_stage, new_position, exclude_id=qid)


def serialize(db, row, uid):
    result = {key: row[key] for key in (*EDIT_FIELDS, 'id', 'version', 'owner_user_id', 'visibility',
              'review_status', 'review_reason', 'stage_title')}
    result['samples'] = json.loads(row['samples'])
    result['starter_codes'] = json.loads(row['starter_codes'])
    result['source_info'] = json.loads(row['source_info'])
    result['statement_html'] = render_statement(row['statement'])
    result['reference_code_html'] = render_statement(row['reference_code']) if row['reference_code'].strip() else ''
    result['active'] = bool(row['active'])
    result['solved'] = bool(db.execute("""SELECT 1 FROM coding_submissions WHERE user_id=? AND question_id=?
        AND question_content_version=? AND status='Accepted' LIMIT 1""", (uid, row['id'], row['content_version'])).fetchone())
    result['favorited'] = bool(db.execute('SELECT 1 FROM coding_favorites WHERE user_id=? AND question_id=?',
                                          (uid, row['id'])).fetchone())
    result['content_available'] = bool(row['statement'].strip())
    result['content_notice'] = '' if result['content_available'] else '尚未缓存完整题面，请打开原题链接或联系管理员重新导入。'
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
    if item['remote_platform'] not in ('luogu', 'leetcode'):
        raise HTTPException(422, '远程评测平台无效')
    if item['judge_mode'] == 'luogu' and item['remote_platform'] == 'luogu':
        item['remote_problem_id'] = item['remote_problem_id'].strip().upper()
        if not re.fullmatch(r'[A-Z][A-Z0-9_-]{0,31}', item['remote_problem_id']):
            raise HTTPException(422, '洛谷评测须填写有效题目编号')
    elif item['judge_mode'] == 'luogu' and item['remote_platform'] == 'leetcode':
        item['remote_problem_id'] = item['remote_problem_id'].strip()
        try:
            slug = coding_platforms.normalize_identifier('leetcode', item['source_url'])
        except ValueError as error:
            raise HTTPException(422, '请填写力扣中国区原题链接（leetcode.cn）') from error
        if slug != item['remote_problem_id']:
            raise HTTPException(422, 'LeetCode 题目标识与原题链接不一致')
        if (item['source_info'].get('platform') != 'leetcode'
                or not re.fullmatch(r'[1-9]\d{0,8}', str(item['source_info'].get('question_id', '')))):
            raise HTTPException(422, '请使用 LeetCode 官方导入功能填写题目编号与代码模板')
    if item['judge_mode'] == 'samples':
        if not item['samples']:
            raise HTTPException(422, '样例评测题至少需要一组公开输入/输出样例')
        item['remote_problem_id'] = ''
        item['remote_platform'] = 'luogu'
    if not isinstance(item['starter_codes'], dict) or any(
            language not in ('cpp11', 'c', 'python3') or not isinstance(code, str) or len(code) > 100000
            for language, code in item['starter_codes'].items()):
        raise HTTPException(422, '代码模板格式无效')
    if not isinstance(item['source_info'], dict) or len(json.dumps(item['source_info'], ensure_ascii=False)) > 250000:
        raise HTTPException(422, '题目来源信息格式无效')
    if item['judge_mode'] == 'luogu' and item['remote_platform'] == 'leetcode' and item['source_info'].get('leetcode_metadata'):
        from app.services.coding_test_adapters import validate_cases, UnsupportedCase
        try:
            validate_cases(item['samples'], item['source_info']['leetcode_metadata'])
        except UnsupportedCase:
            # These questions remain available for the platform's full judge.
            pass
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    item['samples'] = json.dumps(item['samples'], ensure_ascii=False)
    item['starter_codes'] = json.dumps(item['starter_codes'], ensure_ascii=False)
    item['source_info'] = json.dumps(item['source_info'], ensure_ascii=False)
    return item


def event(db, qid, actor, name, version, reason=''):
    db.execute('INSERT INTO coding_review_events(question_id,actor_id,event,version,reason,created) VALUES (?,?,?,?,?,?)',
               (qid, actor['id'], name, version, reason, time.time()))


def create_question(db, user, data, *, admin=False):
    item = validate_item(db, data, admin=admin)
    now = time.time()
    _shift_for_insert(db, item['stage_id'], item['position'])
    cursor = db.execute(f'''INSERT INTO coding_questions({','.join(EDIT_FIELDS)},owner_user_id,visibility,review_status,active,created,updated)
        VALUES ({','.join('?' for _ in EDIT_FIELDS)},?,?,?,?,?,?)''',
        (*(item[key] for key in EDIT_FIELDS), None if admin else user['id'], 'public' if admin else 'private',
         'approved' if admin else 'draft', data.get('active', True), now, now))
    bind(db, user, 'coding', cursor.lastrowid, item['statement'], item['reference_code'])
    event(db, cursor.lastrowid, user, 'create', 1)
    return serialize(db, get_question(db, cursor.lastrowid), user['id'])


def update_question(db, user, qid, data, *, admin=False):
    row = editable(db, qid, user, admin=admin)
    check_version(row, data['version'])
    merged = {key: row[key] for key in EDIT_FIELDS}
    for key in ('samples', 'starter_codes', 'source_info'):
        merged[key] = json.loads(row[key])
    merged.update({key: value for key, value in data.items() if key in EDIT_FIELDS})
    item = validate_item(db, merged, admin=admin)
    _move_position(db, row, item, qid)
    bind(db, user, 'coding', qid, item['statement'], item['reference_code'])
    public = admin and row['visibility'] == 'public'
    review_status = row['review_status'] if admin else 'draft'
    content_changed = any(item[key] != row[key] for key in ('statement', 'samples', 'starter_codes', 'reference_code', 'source_info', 'judge_mode', 'remote_platform', 'remote_problem_id'))
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
