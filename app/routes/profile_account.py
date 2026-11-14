"""Authenticated account settings and verified account deletion."""
import sqlite3
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from app.db import connect
from app.services.auth import current_user, public_user
from app.services.security import hash_password, verify_password
from app.services.password_vault import decrypt_password, encrypt_password
from app.services.account_deletion import delete_account, remove_account_files

router = APIRouter(prefix='/api/profile', tags=['账号设置'])


class UsernameChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1)


class AccountVerification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str | None = None
    current_password: str | None = None


class PasswordChange(AccountVerification):
    password: str = Field(min_length=1)


def _current_account(db, user, authorization):
    """Recheck the exact authenticated session for account changes and password viewing."""
    account = db.execute('''SELECT users.* FROM users JOIN sessions ON sessions.user_id=users.id
        WHERE users.id=? AND sessions.token=? AND sessions.expires>? AND users.is_active=1''',
        (user['id'], authorization[7:], time.time())).fetchone()
    if account is None:
        raise HTTPException(401, '登录已过期或账号已停用，请重新登录')
    return account


def _verification_error(db, account, payload, purpose):
    """Return verification failures so failed code attempts can commit before reporting."""
    if account['email']:
        if not payload.code:
            return HTTPException(422, '请填写当前邮箱收到的验证码')
        from app.services.email_auth import consume_account_code
        return consume_account_code(db, account['id'], purpose, payload.code)
    if not payload.current_password:
        return HTTPException(422, '请填写当前密码')
    if not verify_password(payload.current_password, account['password']):
        return HTTPException(400, '当前密码不正确')
    return None


@router.post('/reveal-password')
def reveal_own_password(authorization: str = Header(), user=Depends(current_user)):
    """Reveal only the current account's encrypted password on an explicit, uncached request."""
    with connect() as db:
        account = _current_account(db, user, authorization)
        if not account['password_ciphertext']:
            raise HTTPException(409, '旧密码暂不可查看，请修改密码或使用密码成功登录后再查看')
        password = decrypt_password(account['password_ciphertext'])
    return JSONResponse({'password': password}, headers={'Cache-Control': 'no-store'})


@router.post('/username')
def change_username(payload: UsernameChange, authorization: str = Header(), user=Depends(current_user)):
    """Rename the authenticated account while retaining email, sessions, and owned data."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = _current_account(db, user, authorization)
        try:
            db.execute('UPDATE users SET username=? WHERE id=?', (payload.username, account['id']))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, '用户名已存在，请使用其他用户名') from error
        return public_user(db.execute('SELECT * FROM users WHERE id=?', (account['id'],)).fetchone())


@router.post('/password')
def change_password(payload: PasswordChange, authorization: str = Header(), user=Depends(current_user)):
    """Verify the current mailbox or legacy password, replace the password, and revoke sessions."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = _current_account(db, user, authorization)
        failure = _verification_error(db, account, payload, 'password')
        if failure is None:
            db.execute('UPDATE users SET password=?,password_ciphertext=? WHERE id=?',
                (hash_password(payload.password), encrypt_password(payload.password), account['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (account['id'],))
    if failure:
        raise failure
    return {'message': '密码已更新，请重新登录'}


@router.delete('/account', status_code=204)
def remove_own_account(payload: AccountVerification, authorization: str = Header(), user=Depends(current_user)):
    """Delete the verified current account and its private data, preserving used vouchers."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = _current_account(db, user, authorization)
        if account['is_superadmin']:
            raise HTTPException(409, '不能删除超级管理员账号')
        failure = _verification_error(db, account, payload, 'delete')
        if failure is None:
            files = delete_account(db, account)
    if failure:
        raise failure
    remove_account_files(files)
    return Response(status_code=204)
