"""Administrator-only account provisioning and read access to exam records."""
import sqlite3
import time
import re
from typing import Annotated, Literal
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from app.config import load_config
from app.db import allocate_user_id, connect
from app.services.auth import PUBLIC_USER_FIELDS, administrator, public_user, managed_user, reviewable_interview
from app.services.interviews import details, summary
from app.services.security import hash_password
from app.services.password_vault import decrypt_password, encrypt_password
from app.services.password_vault import PasswordVaultError
from app.services import model_settings
from app.services import feishu_settings
from app.services import credits, points
from app.services.account_deletion import delete_account, remove_account_files
from app.services.problem_content import public_problem

router = APIRouter(prefix='/api/admin', tags=['后台管理'], dependencies=[Depends(administrator)])
Username = Annotated[str, Field(min_length=1)]


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: Username
    password: str = Field(min_length=1)
    is_admin: StrictBool = False
    email: str | None = None
    is_active: StrictBool = True
    can_training: StrictBool = False
    can_coding: StrictBool = False
    can_interview: StrictBool = True
    can_exam: StrictBool = True
    can_practice: StrictBool | None = None
    interview_credits: Annotated[StrictInt, Field(ge=0, le=1000000)] | None = None
    points: Annotated[StrictInt, Field(ge=0, le=1000000000)] | None = None

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        """Associate an optional canonical mailbox with an administrator-created account."""
        if value is None or not value.strip():
            return None
        from app.services.email_auth import normalize_email
        return normalize_email(value)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    is_admin: StrictBool | None = None
    is_active: StrictBool | None = None
    can_training: StrictBool | None = None
    can_coding: StrictBool | None = None
    can_interview: StrictBool | None = None
    can_exam: StrictBool | None = None
    # Kept for one release so older clients can update the former combined grant.
    can_practice: StrictBool | None = None
    interview_credits: Annotated[StrictInt, Field(ge=0, le=1000000)] | None = None
    points: Annotated[StrictInt, Field(ge=0, le=1000000000)] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=1)


class UsernameReset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: Username


class AccountEmail(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str | None

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        """Allow an empty mailbox to remove email login from an existing account."""
        return AccountCreate.validate_email(value)


class BankQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: str = Field(pattern='^(professional|translation|oral)$')
    subject: str = Field(default='', max_length=40)
    content: str = Field(min_length=1, max_length=12000)
    active: StrictBool = True

    @model_validator(mode='after')
    def validate_question(self):
        """Store nonempty prompts in the correct subject and language."""
        from app.services.question_bank import LABELS
        self.content = self.content.strip()
        if not self.content:
            raise ValueError('题目内容不能为空')
        if self.category == 'professional' and self.subject not in LABELS:
            raise ValueError('专业课必须选择数据结构、操作系统或计算机网络')
        if self.category != 'professional' and self.subject:
            raise ValueError('英文题库不填写专业课学科')
        if self.category != 'professional' and (re.search(r'[\u4e00-\u9fff]', self.content) or not re.search(r'[A-Za-z]', self.content)):
            raise ValueError('翻译和口语题目请以英文保存')
        return self


class LuoguSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    app_origin: str = Field(min_length=1, max_length=300)

    @field_validator('app_origin')
    @classmethod
    def validate_app_origin(cls, value):
        """Accept one secure HTTP origin, allowing plain HTTP only for loopback development."""
        value = value.strip()
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError('请输入有效的知序网站来源地址') from error
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('请输入只包含协议、域名和端口的网站来源，不要填写路径或参数')
        hostname = parsed.hostname.lower()
        local = hostname in ('localhost', '127.0.0.1', '::1')
        if parsed.scheme != 'https' and not local:
            raise ValueError('正式网站必须使用 HTTPS；HTTP 仅支持 localhost 或 127.0.0.1')
        host = f'[{hostname}]' if ':' in hostname else hostname
        netloc = f'{host}:{port}' if port is not None else host
        return f'{parsed.scheme}://{netloc}'


class ModelServiceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = None
    clear_api_key: StrictBool = False
    provider: Literal['dashscope', 'openai'] | None = None
    protocol: Literal['dashscope_audio', 'dashscope_native'] | None = None
    voice: str | None = Field(default=None, max_length=120)

    @field_validator('base_url')
    @classmethod
    def validate_base_url(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value.strip())
        try:
            parsed.port
        except ValueError as error:
            raise ValueError('请输入有效的模型服务地址') from error
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(ord(char) < 32 for char in value)):
            raise ValueError('模型服务地址必须是有效的 HTTP/HTTPS 地址，不含账号、参数或片段')
        return value.strip().rstrip('/')

    @field_validator('model', 'voice')
    @classmethod
    def validate_name(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError('模型名称和音色不能为空，且不能包含控制字符')
        return value

class ModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interview: ModelServiceUpdate | None = None
    asr: ModelServiceUpdate | None = None
    tts: ModelServiceUpdate | None = None
    trends: ModelServiceUpdate | None = None


class FeishuSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    app_id: str | None = Field(default=None, max_length=256)
    app_secret: str | None = Field(default=None, max_length=4096)
    clear_app_secret: StrictBool = False
    redirect_uri: str | None = Field(default=None, max_length=2048)

    @field_validator('redirect_uri')
    @classmethod
    def validate_redirect(cls, value):
        from app.services.feishu_oauth import validate_redirect_uri
        if value is None:
            raise ValueError('回调地址不能为空')
        return validate_redirect_uri(value)

    @field_validator('app_id', 'app_secret')
    @classmethod
    def validate_feishu_credential(cls, value):
        """Reject whitespace-only and multiline credential values."""
        if value is None:
            return value
        value = value.strip()
        if any(char in value for char in ('\r', '\n', '\x00')):
            raise ValueError('飞书凭证不能包含换行或控制字符')
        return value

    @model_validator(mode='after')
    def validate_secret_action(self):
        """Require one explicit action when updating the App Secret."""
        if self.clear_app_secret and self.app_secret:
            raise ValueError('不能同时设置和清除飞书 App Secret')
        return self


def find_user(db, uid):
    row = db.execute(f'SELECT {PUBLIC_USER_FIELDS} FROM users WHERE id=?', (uid,)).fetchone()
    if row is None:
        raise HTTPException(404, '账号不存在')
    return row


@router.get('/luogu-settings')
def get_luogu_settings():
    with connect() as db:
        row = db.execute("SELECT value FROM app_settings WHERE key='luogu_app_origin'").fetchone()
        return {'app_origin': row['value']}


@router.patch('/luogu-settings')
def update_luogu_settings(payload: LuoguSettings):
    with connect() as db:
        db.execute("UPDATE app_settings SET value=? WHERE key='luogu_app_origin'", (payload.app_origin,))
    return {'app_origin': payload.app_origin}


@router.get('/feishu-settings')
def get_feishu_settings():
    try:
        with connect() as db:
            return feishu_settings.public_settings(db)
    except PasswordVaultError as error:
        raise HTTPException(503, '密钥加密服务不可用，请管理员检查密钥文件') from error


@router.patch('/feishu-settings')
def update_feishu_settings(payload: FeishuSettingsUpdate):
    try:
        with connect() as db:
            return feishu_settings.update(db, payload.model_dump(exclude_unset=True))
    except PasswordVaultError as error:
        raise HTTPException(503, '密钥加密服务不可用，请管理员检查密钥文件') from error


@router.get('/model-settings')
def get_model_settings():
    config = load_config()
    with connect() as db:
        overrides = model_settings.read(db)
    try:
        return model_settings.public_settings(config, overrides)
    except PasswordVaultError as error:
        raise HTTPException(503, '密钥加密服务不可用，请管理员检查密钥文件') from error


@router.patch('/model-settings')
def update_model_settings(payload: ModelSettingsUpdate):
    changes = payload.model_dump(exclude_unset=True)
    allowed = {
        'interview': {'base_url', 'model', 'api_key', 'clear_api_key'},
        'asr': {'base_url', 'model', 'api_key', 'clear_api_key'},
        'tts': {'base_url', 'model', 'api_key', 'clear_api_key', 'provider', 'protocol', 'voice'},
        'trends': {'base_url', 'model', 'api_key', 'clear_api_key'},
    }
    for service, fields in changes.items():
        unsupported = set(fields) - allowed[service]
        if unsupported:
            raise HTTPException(422, f'{service} 不支持配置字段：{", ".join(sorted(unsupported))}')
        api_key = fields.get('api_key')
        if api_key is not None and (len(api_key) > 4096 or any(char in api_key for char in ('\r', '\n', '\x00'))):
            raise HTTPException(422, f'{service} API Key 格式无效')
        if fields.get('clear_api_key') and api_key:
            raise HTTPException(422, f'{service} 不能同时设置和清除 API Key')
    config = load_config()
    try:
        with connect() as db:
            overrides = model_settings.apply_update(db, model_settings.read(db), changes)
    except PasswordVaultError as error:
        raise HTTPException(503, '密钥加密服务不可用，请管理员检查密钥文件') from error
    return model_settings.public_settings(config, overrides)


@router.get('/users')
def users(actor=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN')
        user_fields = ','.join('u.' + field for field in PUBLIC_USER_FIELDS.split(','))
        from app.services import service_packages
        totals = service_packages.summaries(db)
        return [{**public_user(row, admin_view=True), 'password_available': bool(row['password_ciphertext']),
                 'referrer_name': row['referrer_name'], 'referrer_email': row['referrer_email'], **totals[row['id']]}
                for row in db.execute(f'''SELECT {user_fields},u.password_ciphertext,
                    COALESCE(r.username,'') AS referrer_name,COALESCE(r.email,'') AS referrer_email
                    FROM users u LEFT JOIN users r ON r.id=u.referrer_id
                    WHERE (? OR u.is_admin=0) ORDER BY u.id DESC''', (actor['is_superadmin'],))]


@router.get('/contest-participants')
def eligible_contest_users():
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT id,username,email,is_active FROM users WHERE is_admin=0 ORDER BY username COLLATE NOCASE,id')]


@router.get('/contests/{cid}/participants')
def contest_roster(cid: int):
    with connect() as db:
        contest = db.execute('SELECT access_mode FROM contests WHERE id=?', (cid,)).fetchone()
        if not contest:
            raise HTTPException(404, '比赛不存在')
        ids = [row[0] for row in db.execute('SELECT user_id FROM contest_participants WHERE contest_id=? ORDER BY user_id', (cid,))]
        if contest['access_mode'] == 'all':
            ids = [row[0] for row in db.execute('SELECT id FROM users WHERE is_admin=0')]
        return {'participant_ids': ids, 'legacy_open': contest['access_mode'] == 'all'}


@router.post('/users/{uid}/reveal-password')
def reveal_password(uid: int, actor=Depends(administrator)):
    """Reveal one encrypted password only on an explicit administrator request."""
    with connect() as db:
        managed_user(db, uid, actor)
        row = db.execute('SELECT password_ciphertext FROM users WHERE id=?', (uid,)).fetchone()
        if not row['password_ciphertext']:
            raise HTTPException(409, '旧账号密码不可恢复，请重置密码或由用户成功登录一次后再查看')
        password = decrypt_password(row['password_ciphertext'])
    return JSONResponse({'password': password}, headers={'Cache-Control': 'no-store'})


@router.get('/question-bank')
def list_question_bank(category: str | None = None):
    with connect() as db:
        if category:
            return [dict(row) for row in db.execute('SELECT * FROM question_bank WHERE category=? ORDER BY id', (category,))]
        return [dict(row) for row in db.execute('SELECT * FROM question_bank ORDER BY category,subject,id')]


@router.post('/question-bank', status_code=201)
def create_bank_question(payload: BankQuestion):
    with connect() as db:
        now = time.time()
        cursor = db.execute('''INSERT INTO question_bank(category,subject,content,active,created,updated)
            VALUES (?,?,?,?,?,?)''', (payload.category, payload.subject, payload.content.strip(), payload.active, now, now))
        return dict(db.execute('SELECT * FROM question_bank WHERE id=?', (cursor.lastrowid,)).fetchone())


@router.get('/question-bank/{qid}')
def get_bank_question(qid: int):
    with connect() as db:
        row = db.execute('SELECT * FROM question_bank WHERE id=?', (qid,)).fetchone()
        if not row:
            raise HTTPException(404, '题目不存在')
        return dict(row)


@router.patch('/question-bank/{qid}')
def update_bank_question(qid: int, payload: BankQuestion):
    with connect() as db:
        changed = db.execute('''UPDATE question_bank SET category=?,subject=?,content=?,active=?,updated=? WHERE id=?''',
            (payload.category, payload.subject, payload.content.strip(), payload.active, time.time(), qid)).rowcount
        if not changed:
            raise HTTPException(404, '题目不存在')
        return dict(db.execute('SELECT * FROM question_bank WHERE id=?', (qid,)).fetchone())


@router.delete('/question-bank/{qid}', status_code=204)
def delete_bank_question(qid: int):
    with connect() as db:
        if not db.execute('DELETE FROM question_bank WHERE id=?', (qid,)).rowcount:
            raise HTTPException(404, '题目不存在')


@router.post('/users', status_code=201)
def create_user(payload: AccountCreate, actor=Depends(administrator)):
    if payload.is_admin and not actor['is_superadmin']:
        raise HTTPException(403, '仅超级管理员可以创建管理员')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        initial = credits.ADMIN_CREDITS if payload.is_admin else payload.interview_credits if payload.interview_credits is not None else credits.default_credits(db)
        try:
            legacy_grant = payload.can_practice
            training = payload.can_training if legacy_grant is None else legacy_grant
            coding = payload.can_coding if legacy_grant is None else legacy_grant
            from app.services import referrals
            uid = db.execute('''INSERT INTO users(id,username,password,password_ciphertext,is_admin,email,is_active,interview_credits,can_interview,can_exam,can_practice,can_training,can_coding,invite_code)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (allocate_user_id(db), payload.username, hash_password(payload.password), encrypt_password(payload.password), payload.is_admin,
                payload.email, payload.is_active, 0, payload.can_interview, payload.can_exam, int(training and coding), training, coding, referrals._code(db))).lastrowid
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, '用户名或邮箱已存在，请使用其他用户名或邮箱') from error
        credits.adjust(db, uid, initial, kind='initial')
        if payload.points:
            points.adjust(db, uid, payload.points, kind='admin_adjust')
        return public_user(find_user(db, uid), admin_view=True)


@router.patch('/users/{uid}')
def update_user(uid: int, payload: AccountUpdate, actor=Depends(administrator)):
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, '请提供有效的管理角色、面试次数或账号状态')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = managed_user(db, uid, actor)
        if changes.get('is_admin') is True and not actor['is_superadmin']:
            raise HTTPException(403, '仅超级管理员可以授予管理权限')
        if uid == actor['id'] and (changes.get('is_admin') is False or changes.get('is_active') is False):
            raise HTTPException(409, '不能撤销自己的后台权限或停用当前账号，请由其他管理员操作')
        if old['is_admin'] and old['is_active'] and (changes.get('is_admin') is False or changes.get('is_active') is False):
            count = db.execute('SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1').fetchone()[0]
            if count <= 1:
                raise HTTPException(409, '至少保留一个启用的管理员账号')
        legacy_grant = bool(old['can_practice'] and not old['can_training'] and not old['can_coding'])
        current_training = bool(old['can_training'] or legacy_grant)
        current_coding = bool(old['can_coding'] or legacy_grant)
        if 'can_practice' in changes:
            current_training = current_coding = changes.pop('can_practice')
        current_training = changes.get('can_training', current_training)
        current_coding = changes.get('can_coding', current_coding)
        if 'can_training' in changes or 'can_coding' in changes or 'can_practice' in payload.model_fields_set:
            changes['can_practice'] = int(current_training and current_coding)
        if changes.get('is_admin', old['is_admin']):
            changes['interview_credits'] = credits.ADMIN_CREDITS
            changes['can_interview'] = changes['can_exam'] = 1
        if 'interview_credits' in changes:
            credits.adjust(db, uid, changes.pop('interview_credits'))
        if 'points' in changes:
            points.adjust(db, uid, changes.pop('points') - old['points'], kind='admin_adjust')
        # Field names are drawn only from the closed AccountUpdate model.
        assignments = ','.join(f'{key}=?' for key in changes)
        if changes:
            db.execute(f'UPDATE users SET {assignments} WHERE id=?', (*changes.values(), uid))
        if changes.get('is_active') is False:
            db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
        return public_user(find_user(db, uid), admin_view=True)


@router.post('/users/{uid}/username')
def reset_username(uid: int, payload: UsernameReset, actor=Depends(administrator)):
    """Rename the login identifier without changing identity or stored records."""
    with connect() as db:
        managed_user(db, uid, actor)
        try:
            db.execute('UPDATE users SET username=? WHERE id=?', (payload.username, uid))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, '用户名已存在，请使用其他用户名') from error
        return public_user(find_user(db, uid), admin_view=True)


@router.post('/users/{uid}/email')
def update_email(uid: int, payload: AccountEmail, actor=Depends(administrator)):
    """Replace the login mailbox without changing identity, sessions, or private records."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = managed_user(db, uid, actor)
        if account['email'] != payload.email:
            try:
                db.execute('UPDATE users SET email=? WHERE id=?', (payload.email, uid))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, '邮箱已关联其他账号，请使用其他邮箱') from error
            db.execute('DELETE FROM account_email_challenges WHERE user_id=? OR email IN (?,?)',
                (uid, account['email'], payload.email))
            for email in (account['email'], payload.email):
                db.execute('DELETE FROM email_challenges WHERE email=? COLLATE NOCASE', (email,))
        return public_user(find_user(db, uid), admin_view=True)


@router.post('/users/{uid}/password')
def reset_password(uid: int, payload: PasswordReset, actor=Depends(administrator)):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        managed_user(db, uid, actor)
        db.execute('UPDATE users SET password=?,password_ciphertext=? WHERE id=?',
                   (hash_password(payload.password), encrypt_password(payload.password), uid))
        db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))
    return {'message': '密码已重置，该账号的登录会话已失效'}


@router.delete('/users/{uid}', status_code=204)
def delete_user(uid: int, actor=Depends(administrator)):
    """Delete private account data while preserving spent voucher status and issue values."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        account = managed_user(db, uid, actor)
        if account['is_superadmin'] or uid == actor['id']:
            raise HTTPException(409, '不能删除超级管理员或当前登录账号')
        files = delete_account(db, account)
    remove_account_files(files)


@router.get('/interviews')
def interviews(actor=Depends(administrator)):
    with connect() as db:
        return [{**summary(row), 'user_id': row['user_id'], 'username': row['username']} for row in db.execute('''SELECT interviews.*,username
            FROM interviews JOIN users ON users.id=interviews.user_id WHERE (? OR users.is_admin=0)
            ORDER BY interviews.id DESC''', (actor['is_superadmin'],))]


@router.get('/interviews/{iid}')
def get_interview(iid: int, actor=Depends(administrator)):
    with connect() as db:
        reviewable_interview(db, iid, actor)
        return details(db, iid)


@router.get('/interviews/{iid}/answers/{stage}/audio')
def get_audio(iid: int, stage: int, actor=Depends(administrator)):
    with connect() as db:
        reviewable_interview(db, iid, actor)
        row = db.execute('SELECT audio_path FROM answers WHERE interview_id=? AND stage=?', (iid, stage)).fetchone()
        if not row or not row['audio_path'] or not Path(row['audio_path']).is_file():
            raise HTTPException(404, '录音不存在')
        return FileResponse(row['audio_path'], media_type='audio/webm')


@router.get('/contests')
def contests():
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM contests ORDER BY id DESC')]


@router.get('/contests/{cid}/problems')
def problems(cid: int):
    with connect() as db:
        if not db.execute('SELECT 1 FROM contests WHERE id=?', (cid,)).fetchone():
            raise HTTPException(404, '比赛不存在')
        return [{**public_problem(row), 'points': row['points'],
            'attempt_count': db.execute('''SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=? AND users.is_admin=0''', (row['id'],)).fetchone()[0],
            'accepted_count': db.execute("""SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
                WHERE problem_id=? AND status='Accepted' AND users.is_admin=0""", (row['id'],)).fetchone()[0]}
            for row in db.execute('SELECT * FROM problems WHERE contest_id=? ORDER BY id', (cid,))]


@router.get('/submissions/users')
def submission_users(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                    actor=Depends(administrator)):
    with connect() as db:
        visibility = '' if actor['is_superadmin'] else ' AND users.is_admin=0'
        total = db.execute(f'''SELECT COUNT(*) FROM (
            SELECT submissions.user_id FROM submissions JOIN users ON users.id=submissions.user_id
            WHERE 1=1{visibility} GROUP BY submissions.user_id
        )''').fetchone()[0]
        users = [dict(row) for row in db.execute(f'''SELECT users.id AS user_id,users.username,COUNT(submissions.id) AS submission_count
            FROM users JOIN submissions ON submissions.user_id=users.id
            WHERE 1=1{visibility} GROUP BY users.id,users.username
            ORDER BY users.username COLLATE NOCASE LIMIT ? OFFSET ?''', (page_size,(page-1)*page_size))]
        stats = db.execute(f'''SELECT COUNT(*) AS total,
            SUM(CASE WHEN status='Accepted' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN status IN ('Waiting for browser extension','Submitted','Judging') THEN 1 ELSE 0 END) AS judging
            FROM submissions JOIN users ON users.id=submissions.user_id WHERE 1=1{visibility}''').fetchone()
        return {'items':users,'total':total,'page':page,'page_size':page_size,
            'pages':(total+page_size-1)//page_size,
            'stats':{'total':stats['total'] or 0,'accepted':stats['accepted'] or 0,'judging':stats['judging'] or 0}}


@router.get('/submissions/users/{user_id}')
def user_submissions(user_id: int, page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                     actor=Depends(administrator)):
    with connect() as db:
        user = db.execute('SELECT id,username FROM users WHERE id=? AND (? OR is_admin=0)',
                          (user_id,actor['is_superadmin'])).fetchone()
        if not user: raise HTTPException(404, '用户不存在')
        total = db.execute('SELECT COUNT(*) FROM submissions WHERE user_id=?', (user_id,)).fetchone()[0]
        rows = [dict(row) for row in db.execute('''SELECT submissions.id,users.username,problem_id,problems.title AS problem_title,
            language,status,created,submissions.remote_platform,remote_submission_id,detail FROM submissions
            JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id
            WHERE submissions.user_id=? ORDER BY submissions.id DESC LIMIT ? OFFSET ?''',
            (user_id,page_size,(page-1)*page_size))]
        return {'items':rows,'total':total,'page':page,'page_size':page_size,
            'pages':(total+page_size-1)//page_size}


@router.get('/submissions')
def submissions(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
                contest_id: int | None = Query(default=None, ge=1),
                user_id: int | None = Query(default=None, ge=1),
                problem_id: int | None = Query(default=None, ge=1),
                status: Literal['Accepted'] | None = None,
                participants_only: bool = False, actor=Depends(administrator)):
    """Filter records within an administrator's visibility, including participant-only contest metrics."""
    with connect() as db:
        clauses = []
        params: list[object] = []
        if not actor['is_superadmin'] or participants_only: clauses.append('users.is_admin=0')
        for column, value in [('problems.contest_id', contest_id), ('submissions.user_id', user_id),
                              ('submissions.problem_id', problem_id), ('submissions.status', status)]:
            if value is not None:
                clauses.append(f'{column}=?')
                params.append(value)
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        total = db.execute(f'''SELECT COUNT(*) FROM submissions JOIN users ON users.id=submissions.user_id
            JOIN problems ON problems.id=submissions.problem_id {where}''', params).fetchone()[0]
        rows = [dict(row) for row in db.execute(f'''SELECT submissions.id,username,problem_id,problems.title AS problem_title,
            language,status,created,submissions.remote_platform,remote_submission_id,detail FROM submissions
            JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id
            {where} ORDER BY submissions.id DESC LIMIT ? OFFSET ?''', (*params,page_size,(page-1)*page_size))]
        stats = db.execute(f'''SELECT SUM(CASE WHEN status='Accepted' THEN 1 ELSE 0 END) AS accepted,
            SUM(CASE WHEN status IN ('Waiting for browser extension','Submitted','Judging') THEN 1 ELSE 0 END) AS judging
            FROM submissions JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id {where}''', params).fetchone()
        return {'items': rows, 'total': total, 'page': page, 'page_size': page_size,
            'pages': (total+page_size-1)//page_size,
            'stats': {'accepted': stats['accepted'] or 0, 'judging': stats['judging'] or 0}}


@router.get('/submissions/{sid}')
def submission_detail(sid: int, actor=Depends(administrator)):
    with connect() as db:
        row = db.execute('''SELECT submissions.id,submissions.user_id,submissions.problem_id,users.username,
            problems.title AS problem_title,contests.title AS contest_title,submissions.language,submissions.source,
            submissions.status,submissions.created,submissions.remote_platform,submissions.remote_submission_id,submissions.detail
            FROM submissions JOIN users ON users.id=submissions.user_id JOIN problems ON problems.id=submissions.problem_id
            JOIN contests ON contests.id=problems.contest_id WHERE submissions.id=? AND (? OR users.is_admin=0)''',
            (sid,actor['is_superadmin'])).fetchone()
        if not row: raise HTTPException(404, '提交记录不存在')
        return dict(row)
