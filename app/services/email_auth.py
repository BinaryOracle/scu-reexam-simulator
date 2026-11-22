"""SMTP-delivered, single-use email login with persisted rate and attempt limits."""
import math
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.headerregistry import Address

from fastapi import HTTPException

from app.config import load_config
from app.db import connect, allocate_user_id
from app.services.auth import issue_session, public_user
from app.services.credits import default_credits, adjust
from app.services.security import hash_password, verify_password
from app.services.password_vault import encrypt_password


def _now():
    return time.time()


def normalize_email(value: str) -> str:
    """Canonicalize an ASCII mailbox; reject display names, controls, and invalid labels."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise HTTPException(422, '请输入有效邮箱地址')
    email = value.strip().lower()
    if len(email) > 254 or email.count('@') != 1:
        raise HTTPException(422, '请输入有效邮箱地址')
    local, domain = email.split('@')
    labels = domain.split('.')
    if (not 1 <= len(local) <= 64 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
            or local.startswith('.') or local.endswith('.') or '..' in local
            or len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                     for label in labels)):
        raise HTTPException(422, '请输入有效邮箱地址')
    return email


def _smtp_config():
    """Resolve deployment secrets without exposing them in responses or logs."""
    config = dict(load_config()['email_auth'])
    if not config['enabled']:
        raise HTTPException(503, '邮箱登录尚未启用，请联系管理员配置 email_auth 和 SMTP 邮箱授权码')
    config['smtp_password'] = config['smtp_password'] or os.environ.get(config['smtp_password_env'], '')
    if not config['smtp_username'] or not config['smtp_password']:
        raise HTTPException(503, '邮箱发送未配置，请联系管理员填写 SMTP 用户名并设置邮箱授权码环境变量')
    try:
        config['from_email'] = normalize_email(config['from_email'] or config['smtp_username'])
    except HTTPException:
        raise HTTPException(503, '发件邮箱无效，请联系管理员检查 email_auth.from_email') from None
    return config


def settings():
    """Expose only whether SMTP email login has the required configuration."""
    try:
        _smtp_config()
    except HTTPException:
        return {'enabled': False}
    return {'enabled': True}


def _send_message(config, email, code, purpose='login'):
    message = EmailMessage()
    action = {'login': '登录', 'rebind': '邮箱换绑', 'password': '修改密码', 'delete': '注销账号'}[purpose]
    message['Subject'] = f'复试模拟系统{action}验证码'
    message['From'] = Address(config['from_name'], addr_spec=config['from_email'])
    message['To'] = email
    message.set_content(f"您的{action}验证码为：{code}\n\n有效期 {config['code_ttl_seconds']} 秒，仅可使用一次。请勿向他人透露。\n如非本人操作，请忽略此邮件。")
    context = ssl.create_default_context()
    transport = smtplib.SMTP_SSL if config['smtp_security'] == 'ssl' else smtplib.SMTP
    options = {'timeout': config['timeout_seconds']}
    if config['smtp_security'] == 'ssl':
        options['context'] = context
    with transport(config['smtp_host'], config['smtp_port'], **options) as smtp:
        if config['smtp_security'] == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(config['smtp_username'], config['smtp_password'])
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def _limit_wait(db, scope, identity, now, window, maximum):
    row = db.execute('SELECT * FROM email_auth_limits WHERE scope=? AND identity=?', (scope, identity)).fetchone()
    if row and row['window_start'] + window > now and row['count'] >= maximum:
        return max(1, math.ceil(row['window_start'] + window - now))
    return 0


def _count(db, scope, identity, now, window):
    db.execute('''INSERT INTO email_auth_limits(scope,identity,window_start,count) VALUES (?,?,?,1)
        ON CONFLICT(scope,identity) DO UPDATE SET
        count=CASE WHEN window_start+?<=? THEN 1 ELSE count+1 END,
        window_start=CASE WHEN window_start+?<=? THEN excluded.window_start ELSE window_start END''',
        (scope, identity, now, window, now, window, now))


def _too_many(wait):
    return HTTPException(429, f'请求过于频繁，请在 {wait} 秒后重试', headers={'Retry-After': str(wait)})


def _active_user(db, uid, token=None):
    user = db.execute('SELECT * FROM users WHERE id=? AND is_active=1', (uid,)).fetchone()
    if user is None:
        raise HTTPException(401, '登录已过期或账号已停用，请重新登录')
    if token is not None and not db.execute('SELECT 1 FROM sessions WHERE token=? AND user_id=? AND expires>?',
                                           (token, uid, time.time())).fetchone():
        raise HTTPException(401, '登录已过期，请重新登录')
    return user


def _send_code(value, ip, *, uid=None, purpose='login'):
    """Reserve persisted limits, then deliver outside a write transaction."""
    config = _smtp_config()
    now = _now()
    code = f'{secrets.randbelow(1000000):06d}'
    digest, challenge_id = hash_password(code), secrets.token_hex(16)
    table = 'email_challenges' if uid is None else 'account_email_challenges'
    condition = 'email=?' if uid is None else 'user_id=? AND purpose=?'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if uid is None:
            email = normalize_email(value)
            user = db.execute('SELECT is_active FROM users WHERE email=? COLLATE NOCASE', (email,)).fetchone()
            if user and not user['is_active']:
                raise HTTPException(403, '账号已停用，请联系管理员')
            identity = (email,)
        else:
            user = _active_user(db, uid)
            email = normalize_email(value if purpose == 'rebind' else user['email'] or '')
            if purpose == 'rebind':
                if email == user['email']:
                    raise HTTPException(409, '新邮箱与当前邮箱相同')
                if db.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND id!=?', (email, uid)).fetchone():
                    raise HTTPException(409, '该邮箱已绑定其他账号，请使用其他邮箱')
            identity = (uid, purpose)
        previous = db.execute(f'SELECT created FROM {table} WHERE {condition}', identity).fetchone()
        if previous and previous['created'] + config['resend_seconds'] > now:
            raise _too_many(max(1, math.ceil(previous['created'] + config['resend_seconds'] - now)))
        for scope, key, maximum in (('send_email', email, config['max_email_codes']),
                                    ('send_ip', ip, config['max_ip_codes'])):
            wait = _limit_wait(db, scope, key, now, config['rate_window_seconds'], maximum)
            if wait:
                raise _too_many(wait)
        for scope, key in (('send_email', email), ('send_ip', ip)):
            _count(db, scope, key, now, config['rate_window_seconds'])
        if uid is None:
            db.execute("""INSERT INTO email_challenges(email,challenge_id,code_hash,created,expires,attempts,status)
                VALUES (?,?,?,?,?,0,'pending') ON CONFLICT(email) DO UPDATE SET
                challenge_id=excluded.challenge_id,code_hash=excluded.code_hash,created=excluded.created,
                expires=excluded.expires,attempts=0,status='pending' """,
                (email, challenge_id, digest, now, now + config['code_ttl_seconds']))
        else:
            db.execute("""INSERT INTO account_email_challenges(user_id,purpose,email,source_email,challenge_id,
                code_hash,created,expires,attempts,status) VALUES (?,?,?,?,?,?,?,?,0,'pending')
                ON CONFLICT(user_id,purpose) DO UPDATE SET email=excluded.email,source_email=excluded.source_email,
                challenge_id=excluded.challenge_id,code_hash=excluded.code_hash,created=excluded.created,
                expires=excluded.expires,attempts=0,status='pending' """,
                (uid, purpose, email, user['email'], challenge_id, digest, now, now + config['code_ttl_seconds']))
        for cleanup_table in ('email_challenges', 'account_email_challenges'):
            db.execute(f'DELETE FROM {cleanup_table} WHERE expires<? AND created<?',
                       (now, now - config['resend_seconds']))
        db.execute('DELETE FROM email_auth_limits WHERE window_start<=?', (now - config['rate_window_seconds'],))
    try:
        _send_message(config, email, code, purpose)
    except (OSError, smtplib.SMTPException):
        with connect() as db:
            db.execute(f"UPDATE {table} SET status='failed' WHERE {condition} AND challenge_id=?", (*identity, challenge_id))
        raise HTTPException(503, '验证码发送失败，请联系管理员检查 SMTP 服务、邮箱授权码和发件权限后重试') from None
    with connect() as db:
        updated = db.execute(f"UPDATE {table} SET status='ready' WHERE {condition} AND challenge_id=? AND status='pending'",
                             (*identity, challenge_id)).rowcount
    if not updated:
        raise HTTPException(503, '验证码已更新或操作已失效，请重新获取验证码')
    return {'message': '验证码已发送，请检查收件箱及垃圾邮件', 'retry_after': config['resend_seconds']}


def send_code(value: str, ip: str):
    """Send a login-only verification code to a canonical mailbox."""
    return _send_code(normalize_email(value), ip)


def send_rebind_code(uid: int, value: str, ip: str):
    """Send a user-bound code that verifies the proposed new mailbox."""
    return _send_code(normalize_email(value), ip, uid=uid, purpose='rebind')


def send_account_code(uid: int, purpose: str, ip: str):
    """Send password/delete verification to the active user's current bound mailbox."""
    if purpose not in ('password', 'delete'):
        raise HTTPException(422, '请选择修改密码或注销账号')
    return _send_code(None, ip, uid=uid, purpose=purpose)


def consume_account_code(db, uid: int, purpose: str, code: str):
    """Return an HTTP error or consume the code; callers commit failed attempt counters before raising."""
    config = load_config()['email_auth']
    row = db.execute('SELECT * FROM account_email_challenges WHERE user_id=? AND purpose=?', (uid, purpose)).fetchone()
    user = db.execute('SELECT email,is_active FROM users WHERE id=?', (uid,)).fetchone()
    error = HTTPException(400, '验证码无效或已过期，请重新获取')
    if (not row or not user or not user['is_active'] or row['source_email'] != user['email']
            or row['status'] != 'ready' or row['expires'] <= _now() or row['attempts'] >= config['max_attempts']):
        return error
    if not verify_password(code, row['code_hash']):
        db.execute('UPDATE account_email_challenges SET attempts=attempts+1 WHERE user_id=? AND purpose=?', (uid, purpose))
        return error
    db.execute("UPDATE account_email_challenges SET status='used' WHERE user_id=? AND purpose=?", (uid, purpose))
    return None


def rebind_email(uid: int, value: str, code: str, token: str):
    """Verify the new mailbox and replace its binding while retaining only the current session."""
    email, result, failure = normalize_email(value), None, None
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user = _active_user(db, uid, token)
        row = db.execute("SELECT email FROM account_email_challenges WHERE user_id=? AND purpose='rebind'", (uid,)).fetchone()
        if not row or row['email'] != email:
            failure = HTTPException(400, '验证码无效或已过期，请重新获取')
        elif db.execute('SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND id!=?', (email, uid)).fetchone():
            failure = HTTPException(409, '该邮箱已绑定其他账号，请使用其他邮箱')
        else:
            failure = consume_account_code(db, uid, 'rebind', code)
            if failure is None:
                db.execute('UPDATE users SET email=? WHERE id=?', (email, uid))
                db.execute('DELETE FROM email_challenges WHERE email IN (?,?)', (email, user['email']))
                db.execute('DELETE FROM account_email_challenges WHERE user_id=? OR email IN (?,?)', (uid, email, user['email']))
                db.execute('DELETE FROM sessions WHERE user_id=? AND token!=?', (uid, token))
                result = {**public_user(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()), 'reauth_required': False}
    if failure:
        raise failure
    return result


def _create_user(db, email, invitation_code=None):
    """Create an independent mailbox-named account with an administrator-recoverable random password."""
    from app.services import referrals
    referrer_id = referrals.attribute_signup(db, invitation_code)
    if db.execute('SELECT 1 FROM users WHERE username=?', (email,)).fetchone():
        raise HTTPException(409, '该邮箱对应的用户名已存在，请联系管理员处理用户名冲突后重试')
    password = secrets.token_urlsafe(48)
    uid = allocate_user_id(db)
    db.execute("""INSERT INTO users(id,username,password,password_ciphertext,email,interview_credits,
        is_admin,is_superadmin,is_active,can_interview,can_exam,can_practice,can_training,can_coding,invite_code,referrer_id)
        VALUES (?,?,?,?,?,0,0,0,1,1,1,0,0,0,?,?)""",
        (uid, email, hash_password(password), encrypt_password(password), email, referrals._code(db), referrer_id))
    adjust(db, uid, default_credits(db), kind='initial')
    referrals.record_signup_reward(db, referrer_id, uid)
    return db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()


def login(value: str, code: str, ip: str, invitation_code=None):
    """Consume a delivered code, create an account if needed, and issue a session atomically."""
    email = normalize_email(value)
    config = _smtp_config()
    now, result, failure = _now(), None, None
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        wait = _limit_wait(db, 'login_ip', ip, now, config['rate_window_seconds'], config['max_ip_attempts'])
        if wait:
            raise _too_many(wait)
        _count(db, 'login_ip', ip, now, config['rate_window_seconds'])
        challenge = db.execute('SELECT * FROM email_challenges WHERE email=?', (email,)).fetchone()
        if (not challenge or challenge['status'] != 'ready' or challenge['expires'] <= now
                or challenge['attempts'] >= config['max_attempts']):
            failure = HTTPException(401, '验证码无效或已过期，请重新获取')
        elif not verify_password(code, challenge['code_hash']):
            db.execute('UPDATE email_challenges SET attempts=attempts+1 WHERE email=?', (email,))
            failure = HTTPException(401, '验证码无效或已过期，请重新获取')
        else:
            db.execute("UPDATE email_challenges SET status='used' WHERE email=?", (email,))
            user = db.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE', (email,)).fetchone()
            if user and not user['is_active']:
                failure = HTTPException(403, '账号已停用，请联系管理员')
            else:
                user = user or _create_user(db, email, invitation_code)
                token = issue_session(db, user['id'])
                result = {'token': token, **public_user(user)}
    # Failed guesses and consumed codes remain committed even when returning an HTTP error.
    if failure:
        raise failure
    return result
