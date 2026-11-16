"""Question discussion storage, threading, reactions, and moderation."""
import time
from fastapi import HTTPException


def _comment(db, comment_id, user_id):
    row = db.execute('''SELECT c.*,u.username,
        (SELECT COUNT(*) FROM coding_comment_likes l WHERE l.comment_id=c.id) AS like_count,
        EXISTS(SELECT 1 FROM coding_comment_likes l WHERE l.comment_id=c.id AND l.user_id=?) AS liked
        FROM coding_comments c JOIN users u ON u.id=c.user_id WHERE c.id=?''', (user_id, comment_id)).fetchone()
    if row is None:
        raise HTTPException(404, '评论不存在')
    return dict(row) | {'pinned': bool(row['pinned']), 'liked': bool(row['liked'])}


def list_comments(db, question_id, user_id, sort):
    order = '(SELECT COUNT(*) FROM coding_comment_likes l WHERE l.comment_id=c.id) DESC,c.created DESC,c.id DESC' if sort == 'hot' else 'c.created DESC,c.id DESC'
    rows = db.execute(f'''SELECT c.id FROM coding_comments c WHERE c.question_id=?
        ORDER BY c.pinned DESC,{order}''', (question_id,)).fetchall()
    return [_comment(db, row['id'], user_id) for row in rows]


def create(db, question_id, user, body, parent_id):
    if not body.strip():
        raise HTTPException(422, '评论内容不能为空')
    if parent_id is not None:
        parent = db.execute('''WITH RECURSIVE ancestors(id,parent_id,depth) AS (
            SELECT id,parent_id,1 FROM coding_comments WHERE id=? AND question_id=?
            UNION ALL SELECT c.id,c.parent_id,a.depth+1 FROM coding_comments c JOIN ancestors a ON c.id=a.parent_id
        ) SELECT MAX(depth) AS depth FROM ancestors''', (parent_id, question_id)).fetchone()
        if parent is None or parent['depth'] is None:
            raise HTTPException(404, '回复目标不存在')
        if parent['depth'] >= 6:
            raise HTTPException(422, '回复层级最多为 6 层')
    now = time.time()
    comment_id = db.execute('''INSERT INTO coding_comments(question_id,parent_id,user_id,body,created,updated)
        VALUES (?,?,?,?,?,?)''', (question_id, parent_id, user['id'], body.strip(), now, now)).lastrowid
    return _comment(db, comment_id, user['id'])


def like(db, comment_id, user_id, liked):
    if not db.execute('SELECT 1 FROM coding_comments WHERE id=?', (comment_id,)).fetchone():
        raise HTTPException(404, '评论不存在')
    if liked:
        db.execute('INSERT OR IGNORE INTO coding_comment_likes(comment_id,user_id,created) VALUES (?,?,?)',
                   (comment_id, user_id, time.time()))
    else:
        db.execute('DELETE FROM coding_comment_likes WHERE comment_id=? AND user_id=?', (comment_id, user_id))
    result = _comment(db, comment_id, user_id)
    return {'liked': result['liked'], 'like_count': result['like_count']}


def set_pinned(db, comment_id, pinned):
    cursor = db.execute('UPDATE coding_comments SET pinned=?,updated=? WHERE id=?',
                        (int(pinned), time.time(), comment_id))
    if not cursor.rowcount:
        raise HTTPException(404, '评论不存在')
    return bool(pinned)


def delete(db, comment_id, user):
    row = db.execute('SELECT user_id FROM coding_comments WHERE id=?', (comment_id,)).fetchone()
    if row is None or (row['user_id'] != user['id'] and not user['is_admin']):
        raise HTTPException(404, '评论不存在')
    db.execute('DELETE FROM coding_comments WHERE id=?', (comment_id,))
