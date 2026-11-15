"""Contest-specific enrollment; legacy open contests retain their access until edited."""
from fastapi import HTTPException


def can_access(db, contest, user):
    return bool(user['is_admin'] or contest['access_mode'] == 'all' or db.execute(
        'SELECT 1 FROM contest_participants WHERE contest_id=? AND user_id=?',
        (contest['id'], user['id'])).fetchone())


def require_access(db, cid, user):
    contest = db.execute('SELECT * FROM contests WHERE id=?', (cid,)).fetchone()
    if not contest:
        raise HTTPException(404, '比赛不存在')
    if not can_access(db, contest, user):
        raise HTTPException(403, '你不在本场比赛的参赛名单中，请联系管理员')
    return contest


def set_participants(db, cid, ids):
    """Replace a roster in the caller's transaction; reject stale or administrator IDs."""
    ids = set(ids)
    for uid in ids:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND is_admin=0', (uid,)).fetchone():
            raise HTTPException(422, '参赛名单包含不存在的用户或管理员，请刷新名单后重试')
    db.execute('DELETE FROM contest_participants WHERE contest_id=?', (cid,))
    db.executemany('INSERT INTO contest_participants(contest_id,user_id) VALUES (?,?)', ((cid, uid) for uid in ids))
    db.execute("UPDATE contests SET access_mode='selected' WHERE id=?", (cid,))
