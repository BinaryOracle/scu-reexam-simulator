"""Authentication always re-reads account status and administrator roles from storage."""
import secrets
import time
from typing import Annotated
from fastapi import Depends, Header, HTTPException
from app.config import load_config
from app.db import connect
from app.services.credits import ADMIN_CREDITS

PUBLIC_USER_FIELDS = 'id,username,email,is_admin,is_superadmin,is_active,interview_credits,points,can_interview,can_exam,can_practice,can_training,can_coding'
FLAGS = ('is_admin', 'is_superadmin', 'is_active')


def issue_session(db, user_id):
    """Replace an account's active bearer token and return the new token."""
    token = secrets.token_urlsafe(32)
    expires = time.time() + load_config()['app']['session_hours'] * 3600
    db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
    db.execute('INSERT INTO sessions VALUES (?,?,?)', (token, user_id, expires))
    return token


def public_user(row, *, admin_view=False):
    """Return only safe account fields with JSON boolean account state."""
    # Rows written by pre-v29 clients may still carry only the combined grant.
    legacy_grant = bool(row['can_practice'] and not row['can_training'] and not row['can_coding'])
    training = bool(row['is_admin'] or row['can_training'] or legacy_grant)
    coding = bool(row['is_admin'] or row['can_coding'] or legacy_grant)
    return {'id': row['id'], 'username': row['username'], 'email': row['email'],
            'can_training': training,
            'can_coding': coding,
            'can_practice': bool(training and coding),
            'can_interview': bool(row['is_admin'] or row['can_interview']),
            'can_exam': bool(row['is_admin'] or row['can_exam']),
            'interview_credits': (ADMIN_CREDITS if admin_view else None) if row['is_admin'] else row['interview_credits'],
            'points': row['points'],
            **{key: bool(row[key]) for key in FLAGS}}


def current_user(authorization: Annotated[str | None, Header()] = None):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, '请登录')
    with connect() as db:
        row = db.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id
            WHERE token=? AND expires>? AND users.is_active=1''', (authorization[7:], time.time())).fetchone()
    if row is None:
        raise HTTPException(401, '登录状态已失效；同一账号仅允许一处登录，请重新登录')
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
    """Require an account grant before accessing interview records or endpoints."""
    if not user['can_interview']:
        raise HTTPException(403, '尚未开通模拟面试权限，请联系管理员开通')
    return user


def exam_user(user=Depends(current_user)):
    """Require an account grant before accessing contests or submissions."""
    if not user['can_exam']:
        raise HTTPException(403, '尚未开通上机考试权限，请联系管理员开通')
    return user


def require_training(user):
    """Require the account's daily training grant."""
    if not user['can_training']:
        raise HTTPException(403, '尚未开通每日训练权限，请联系管理员开通')
    return user


def training_user(user=Depends(current_user)):
    return require_training(user)


def require_coding(user):
    """Require the account's algorithm practice grant."""
    if not user['can_coding']:
        raise HTTPException(403, '尚未开通算法题带刷权限，请联系管理员开通')
    return user


def coding_user(user=Depends(current_user)):
    return require_coding(user)


def require_practice(user):
    """Retain the former combined permission check for compatible callers."""
    if not user['can_practice']:
        raise HTTPException(403, '尚未开通练习权限，请联系管理员开通')
    return user


def practice_user(user=Depends(current_user)):
    return require_practice(user)
