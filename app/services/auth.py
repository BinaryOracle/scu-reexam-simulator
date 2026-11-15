"""Authentication always re-reads account status and administrator roles from storage."""
import time
from typing import Annotated
from fastapi import Depends, Header, HTTPException
from app.db import connect
from app.services.credits import ADMIN_CREDITS

PUBLIC_USER_FIELDS = 'id,username,email,is_admin,is_superadmin,is_active,interview_credits,can_practice'
FLAGS = ('is_admin', 'is_superadmin', 'is_active')


def public_user(row, *, admin_view=False):
    """Return only safe account fields with JSON boolean account state."""
    return {'id': row['id'], 'username': row['username'], 'email': row['email'],
            'can_practice': bool(row['is_admin'] or row['can_practice']),
            'interview_credits': (ADMIN_CREDITS if admin_view else None) if row['is_admin'] else row['interview_credits'],
            **{key: bool(row[key]) for key in FLAGS}}


def current_user(authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, '请登录')
    with connect() as db:
        row = db.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
            WHERE token=? AND expires>? AND users.is_active=1''', (authorization[7:], time.time())).fetchone()
    if row is None:
        raise HTTPException(401, '登录已过期或账号已停用，请重新登录')
    return public_user(row)


def administrator(user=Depends(current_user)):
    if not user['is_admin']:
        raise HTTPException(403, '需要后台管理权限')
    return user


def managed_user(db, uid, actor):
    """Hide administrator identities from ordinary administrators, including guessed IDs."""
    row = db.execute(f'SELECT {PUBLIC_USER_FIELDS} FROM users WHERE id=?', (uid,)).fetchone()
    if row is None or (row['is_admin'] and not actor['is_superadmin']):
        raise HTTPException(404, '账号不存在')
    return row


def reviewable_interview(db, iid, actor):
    row = db.execute('SELECT user_id FROM interviews WHERE id=?', (iid,)).fetchone()
    if row is None:
        raise HTTPException(404, '面试记录不存在')
    managed_user(db, row['user_id'], actor)


def interview_user(user=Depends(current_user)):
    """Allow every authenticated active account to use the interview module."""
    return user


def exam_user(user=Depends(current_user)):
    """Allow every authenticated active account to use the programming module."""
    return user


def require_practice(user):
    """Apply the same grant to daily training and algorithm practice."""
    if not user['can_practice']:
        raise HTTPException(403, '尚未开通练习权限，请联系管理员开通每日训练与算法题带刷')
    return user


def practice_user(user=Depends(current_user)):
    return require_practice(user)
