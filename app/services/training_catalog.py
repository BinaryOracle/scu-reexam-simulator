"""Training question visibility, private authorship and versioned moderation."""
import json
import re
import time
from fastapi import HTTPException
from app.config import load_config
from app.services.training_mastery import personal_state

PAGE_SIZE = 12
SELECT = '''SELECT q.*,c.name AS collection_name,c.category,c.section_id,c.active AS collection_active,
    c.position AS collection_position,u.username AS owner_name,u.is_admin AS owner_admin
    FROM training_questions q JOIN training_collections c ON c.id=q.collection_id
    LEFT JOIN users u ON u.id=q.owner_user_id'''


def accessible(row, uid):
    return bool(row and not row['deleted'] and row['active'] and row['collection_active']
                and (row['visibility'] == 'public' or row['owner_user_id'] == uid))


def get_question(db, qid):
    row = db.execute(SELECT + ' WHERE q.id=? AND q.deleted=0', (qid,)).fetchone()
    if row is None:
        raise HTTPException(404, '题目不存在或已删除')
    return row


def require_access(db, qid, uid):
    row = get_question(db, qid)
    if not accessible(row, uid):
        raise HTTPException(404, '题目不存在或当前不可用')
    return row


def editable(db, qid, user, *, admin=False):
    row = get_question(db, qid)
    if admin:
        if row['owner_user_id'] is not None or not (row['visibility'] == 'public' or row['source_key']):
            raise HTTPException(404, '请在投稿审核中管理用户题目')
    elif row['owner_user_id'] != user['id']:
        raise HTTPException(404, '题目不存在')
    return row


def reviewable(db, qid, actor):
    row = get_question(db, qid)
    # Private, never-submitted drafts are not an administrator browsing surface.
    if row['visibility'] != 'public' and row['review_status'] != 'pending':
        raise HTTPException(404, '题目不在公开或待审列表中')
    if row['owner_admin'] and not actor['is_superadmin']:
        raise HTTPException(404, '题目不存在')
    return row


def check_version(row, version):
    if row['version'] != version:
        raise HTTPException(409, '题目已被修改，请刷新后重试')


def serialize(db, row, uid):
    favorite = db.execute('SELECT 1 FROM training_favorites WHERE user_id=? AND question_id=?', (uid, row['id'])).fetchone()
    return {key: row[key] for key in ('id', 'collection_id', 'collection_name', 'section_id', 'category', 'question', 'answer',
                                     'visibility', 'review_status', 'review_reason', 'version')} | {
        'active': bool(row['active']), 'favorite': bool(favorite), 'source_info': json.loads(row['source_info']),
        'mastery': personal_state(db, uid, row['id']),
        'images': [f"/api/training/questions/{row['id']}/images/{i}" for i, _ in enumerate(json.loads(row['images']))],
    }


def list_questions(db, user, *, mine=False, favorites=False, collection_id='', q='', page=1, admin_status=None, section_id=''):
    clauses, values = ['q.deleted=0'], []
    if admin_status is not None:
        clauses.append("(q.visibility='public' OR q.review_status='pending')")
        if not user['is_superadmin']:
            clauses.append('(u.is_admin=0 OR u.id IS NULL)')
        if admin_status == 'pending':
            clauses.append("q.review_status='pending'")
        elif admin_status == 'public':
            clauses.append("q.visibility='public'")
    elif mine:
        clauses.append('q.owner_user_id=?'); values.append(user['id'])
    else:
        clauses.append("q.active=1 AND c.active=1 AND (q.visibility='public' OR q.owner_user_id=?)")
        values.append(user['id'])
    if favorites:
        clauses.append('EXISTS(SELECT 1 FROM training_favorites f WHERE f.question_id=q.id AND f.user_id=?)')
        values.append(user['id'])
    if section_id:
        from app.services.training_schema import SECTIONS
        if section_id not in dict(SECTIONS):
            raise HTTPException(422, '请选择有效的训练篇章')
        clauses.append('c.section_id=?'); values.append(section_id)
    if collection_id:
        clauses.append('q.collection_id=?'); values.append(collection_id)
    if q:
        clauses.append('instr(lower(q.question),lower(?))>0'); values.append(q)
    where = ' WHERE ' + ' AND '.join(clauses)
    total = db.execute('SELECT COUNT(*) FROM (' + SELECT + where + ')', values).fetchone()[0]
    rows = db.execute(SELECT + where + ' ORDER BY q.updated DESC,q.id DESC LIMIT ? OFFSET ?',
                      (*values, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    items = []
    for row in rows:
        item = serialize(db, row, user['id'])
        if admin_status is not None:
            item['owner_name'] = row['owner_name'] or ('官方题库' if row['source_key'] else '公开贡献')
            item['official'] = row['owner_user_id'] is None
        items.append(item)
    return dict(items=items, total=total, page=page, page_size=PAGE_SIZE)


def validate_item(db, item):
    config = load_config()['training']
    collection = db.execute('SELECT * FROM training_collections WHERE id=?', (item['collection_id'],)).fetchone()
    if collection is None or not collection['active']:
        raise HTTPException(422, '请选择启用的训练集合')
    question, answer = item['question'].strip(), item.get('answer', '').strip()
    if not question or len(question) > config['max_question_chars'] or len(answer) > config['max_answer_chars']:
        raise HTTPException(422, f"题干须为1～{config['max_question_chars']}字，参考答案最多{config['max_answer_chars']}字")
    if collection['category'] != 'professional' and (re.search(r'[\u4e00-\u9fff]', question) or not re.search('[A-Za-z]', question)):
        raise HTTPException(422, '英文训练集合的题干请使用英文')
    if collection['category'] == 'oral' and answer:
        raise HTTPException(422, '英文问答仅保存题目，不填写参考答案')
    return dict(collection_id=collection['id'], question=question, answer=answer)


def event(db, qid, actor, name, version, reason=''):
    db.execute('INSERT INTO training_review_events(question_id,actor_id,event,version,reason,created) VALUES (?,?,?,?,?,?)',
               (qid, actor['id'], name, version, reason, time.time()))


def create_question(db, user, item, *, official=False):
    item = validate_item(db, item)
    position = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM training_questions WHERE collection_id=?',
                          (item['collection_id'],)).fetchone()[0]
    now = time.time()
    cursor = db.execute('''INSERT INTO training_questions(collection_id,owner_user_id,position,question,answer,
        visibility,review_status,created,updated) VALUES (?,?,?,?,?,?,?,?,?)''',
        (item['collection_id'], None if official else user['id'], position, item['question'], item['answer'],
         'public' if official else 'private', 'approved' if official else 'draft', now, now))
    event(db, cursor.lastrowid, user, 'create_official' if official else 'create_private', 1)
    return serialize(db, get_question(db, cursor.lastrowid), user['id'])


def update_question(db, user, qid, item, version, *, official=False, active=True):
    row = editable(db, qid, user, admin=official)
    check_version(row, version)
    item = validate_item(db, item)
    db.execute('''UPDATE training_questions SET collection_id=?,question=?,answer=?,visibility=?,
        review_status=?,review_reason='',reviewed_by=NULL,reviewed_at=NULL,active=?,version=version+1,updated=? WHERE id=?''',
        (item['collection_id'], item['question'], item['answer'], 'public' if official else 'private',
         'approved' if official else 'draft', active if official else row['active'], time.time(), qid))
    event(db, qid, user, 'edit_official' if official else 'edit_private', version + 1)
    return serialize(db, get_question(db, qid), user['id'])


def submit(db, user, qid, version, *, withdraw=False):
    row = editable(db, qid, user)
    check_version(row, version)
    if row['visibility'] == 'public':
        raise HTTPException(409, '此题已公开，无需再次提交')
    if not withdraw:
        validate_item(db, dict(row))
        if row['review_status'] == 'pending':
            raise HTTPException(409, '已提交审核，请等待审核结果')
    elif row['review_status'] != 'pending':
        raise HTTPException(409, '此题当前不在审核中')
    db.execute("UPDATE training_questions SET review_status=?,review_reason='',version=version+1,updated=? WHERE id=?",
               ('draft' if withdraw else 'pending', time.time(), qid))
    event(db, qid, user, 'withdraw' if withdraw else 'submit', version + 1)
    return serialize(db, get_question(db, qid), user['id'])


def review(db, actor, qid, version, approve, reason):
    row = reviewable(db, qid, actor)
    check_version(row, version)
    if row['review_status'] != 'pending':
        raise HTTPException(409, '此题不在待审核状态')
    reason = reason.strip()
    if not approve and not reason:
        raise HTTPException(422, '请填写驳回原因')
    if approve:
        validate_item(db, dict(row))
    db.execute('''UPDATE training_questions SET visibility=?,review_status=?,review_reason=?,reviewed_by=?,
        reviewed_at=?,version=version+1,updated=? WHERE id=?''',
        ('public' if approve else 'private', 'approved' if approve else 'rejected', reason, actor['id'], time.time(), time.time(), qid))
    event(db, qid, actor, 'approve' if approve else 'reject', version + 1, reason)
    return serialize(db, get_question(db, qid), actor['id'])
