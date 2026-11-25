"""Validated package benefits, atomic local grants, and durable external grant jobs."""
import json
import re
import time
from typing import Annotated, Literal
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

MODULES = {'training': 'can_training', 'coding': 'can_coding', 'interview': 'can_interview', 'exam': 'can_exam'}
RESOURCE_PATHS = {'drive/folder': 'folder', 'docx': 'docx', 'docs': 'doc', 'doc': 'doc',
                  'sheets': 'sheet', 'base': 'bitable', 'wiki': 'wiki', 'file': 'file', 'slides': 'slides'}


def resource_location(url):
    """Parse a supported Feishu resource without fetching a user-supplied URL."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or
        not re.fullmatch(r'(?:[A-Za-z0-9-]+\.)*feishu\.cn', parsed.hostname) or
        parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment):
        raise ValueError('请输入不含密码和查询参数的飞书文档或目录 HTTPS 链接')
    match = re.fullmatch(r'/(drive/folder|docx|docs|doc|sheets|base|wiki|file|slides)/([A-Za-z0-9]+)/*', parsed.path)
    if not match:
        raise ValueError('暂不支持此飞书链接，请使用文档或文件夹的直接链接')
    return RESOURCE_PATHS[match[1]], match[2]


class FeishuResource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: StrictStr = Field(default='', max_length=100)
    url: StrictStr = Field(max_length=500)
    permission: Literal['view', 'edit', 'full_access'] = 'view'

    @field_validator('url')
    @classmethod
    def resource_url(cls, value):
        parsed = urlsplit(value.strip())
        # The ordinary share-link source marker carries no permission or password.
        if parsed.query == 'from=from_copylink':
            value = parsed._replace(query='').geturl()
        resource_location(value.strip())
        return value.strip().rstrip('/')


class Benefits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    modules: list[Literal['training', 'coding', 'interview', 'exam']] = Field(default_factory=list, max_length=4)
    gift_points: StrictInt = Field(default=0, ge=0, le=1000000)
    course_ids: list[Annotated[StrictInt, Field(gt=0)]] = Field(default_factory=list, max_length=500)
    feishu_resources: list[FeishuResource] = Field(default_factory=list, max_length=20)

    @field_validator('modules', 'course_ids')
    @classmethod
    def unique_values(cls, values):
        return list(dict.fromkeys(values))

    @field_validator('feishu_resources')
    @classmethod
    def unique_resources(cls, values):
        locations = [resource_location(value.url) for value in values]
        if len(set(locations)) != len(locations):
            raise ValueError('同一飞书资源只能配置一次')
        return values


class FeishuRecipient(BaseModel):
    model_config = ConfigDict(extra='forbid')
    member_type: Literal['email', 'mobile', 'openid']
    member_id: StrictStr = Field(min_length=1, max_length=254)

    @field_validator('member_id')
    @classmethod
    def single_line(cls, value, info):
        value = value.strip()
        patterns = {'email': r'[^\s@]+@[^\s@]+\.[^\s@]+', 'mobile': r'(?:1\d{10}|\+[1-9]\d{6,14})',
                    'openid': r'ou_[A-Za-z0-9_-]+'}
        pattern = patterns.get(info.data.get('member_type'), r'(?!)')
        if not re.fullmatch(pattern, value):
            raise ValueError('请输入有效飞书邮箱或绑定手机号；非中国大陆手机号需包含 + 国际区号')
        return value


def initialize(db):
    for table, column, definition in (
        ('service_packages', 'benefits', "TEXT NOT NULL DEFAULT '{}'"),
        ('service_package_purchases', 'benefits_snapshot', 'TEXT'),
        ('service_package_purchases', 'benefit_source_id', 'INTEGER')):
        if column not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    # Pre-feature purchases intentionally receive no retroactive gifts.
    db.execute("UPDATE service_package_purchases SET benefits_snapshot='{}',benefit_source_id=id WHERE benefits_snapshot IS NULL")
    db.execute('''CREATE TABLE IF NOT EXISTS package_benefit_grants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL REFERENCES service_package_purchases(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('modules','points','course','feishu')),
        target TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','processing','granted','failed')),
        attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
        UNIQUE(purchase_id,kind,target))''')
    db.execute('''CREATE TABLE IF NOT EXISTS package_course_grants(
        purchase_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        access_start_date TEXT, access_end_date TEXT,
        PRIMARY KEY(purchase_id,course_id))''')
    db.execute('CREATE INDEX IF NOT EXISTS package_course_user ON package_course_grants(user_id,course_id)')


def validate_courses(db, benefits, actor):
    """Allow packages to grant only courses managed by the registering administrator."""
    from app.services.live import manage
    for cid in benefits['course_ids']:
        course = db.execute('SELECT * FROM live_courses WHERE id=?', (cid,)).fetchone()
        if not course:
            raise HTTPException(422, f'课程 {cid} 不存在，请重新选择')
        if not manage(course, actor):
            raise HTTPException(403, '套餐只能配置当前管理员可管理的课程')
        if course['publication_status'] != 'published':
            raise HTTPException(422, f'课程「{course["title"]}」尚未发布，不能加入套餐')


def apply(db, purchase_id, uid, pid, benefits, recipient, actor):
    """Apply each user's package benefits once; a removed registration cannot earn again."""
    previous = db.execute('''SELECT id,benefit_source_id,benefits_snapshot FROM service_package_purchases
        WHERE user_id=? AND package_id=? AND id<>? ORDER BY id LIMIT 1''', (uid, pid, purchase_id)).fetchone()
    if previous:
        db.execute('UPDATE service_package_purchases SET benefits_snapshot=?,benefit_source_id=? WHERE id=?',
                   (previous['benefits_snapshot'], previous['benefit_source_id'], purchase_id))
        return
    validate_courses(db, benefits, actor)
    if benefits['feishu_resources'] and recipient is None:
        raise HTTPException(422, '该套餐包含飞书授权，请确认接收人的飞书邮箱或绑定手机号')
    snapshot = {**benefits, 'feishu_recipient': recipient}
    db.execute('UPDATE service_package_purchases SET benefits_snapshot=?,benefit_source_id=? WHERE id=?',
               (json.dumps(snapshot, ensure_ascii=False), purchase_id, purchase_id))

    def record(kind, target, payload, status='granted'):
        db.execute('''INSERT INTO package_benefit_grants(purchase_id,kind,target,payload,status,updated)
            VALUES (?,?,?,?,?,?)''', (purchase_id, kind, str(target), json.dumps(payload, ensure_ascii=False), status, time.time()))

    if benefits['modules']:
        # Materialize old combined grants before updating the independent switches.
        db.execute('''UPDATE users SET can_training=1,can_coding=1
            WHERE id=? AND can_practice=1 AND can_training=0 AND can_coding=0''', (uid,))
        for module in benefits['modules']:
            db.execute(f'UPDATE users SET {MODULES[module]}=1 WHERE id=?', (uid,))
        db.execute('UPDATE users SET can_practice=(can_training AND can_coding) WHERE id=?', (uid,))
        record('modules', 'access', benefits['modules'])
    if benefits['gift_points']:
        from app.services.points import adjust
        adjust(db, uid, benefits['gift_points'], kind='package_gift', reference=str(purchase_id))
        record('points', 'wallet', benefits['gift_points'])
    for cid in benefits['course_ids']:
        course = db.execute('SELECT * FROM live_courses WHERE id=?', (cid,)).fetchone()
        start, end = (course['points_access_start_date'], course['points_access_end_date']) if course['access_mode'] == 'points' else (None, None)
        if course['access_mode'] == 'points' and (not start or not end):
            raise HTTPException(409, f'课程「{course["title"]}」未设置访问起止日期')
        db.execute('''INSERT INTO package_course_grants(purchase_id,course_id,user_id,access_start_date,access_end_date)
            VALUES (?,?,?,?,?)''', (purchase_id, cid, uid, start, end))
        db.execute('DELETE FROM course_library_hidden WHERE course_id=? AND user_id=?', (cid, uid))
        record('course', cid, {'title': course['title'], 'access_start_date': start, 'access_end_date': end})
    for index, resource in enumerate(benefits['feishu_resources']):
        record('feishu', index, {'resource': resource, 'recipient': recipient}, 'pending')


def details(db, uid, purchase_id):
    row = db.execute('SELECT * FROM service_package_purchases WHERE id=? AND user_id=?', (purchase_id, uid)).fetchone()
    if not row:
        raise HTTPException(404, '购买记录不存在')
    return {'benefits': json.loads(row['benefits_snapshot']), 'source_purchase_id': row['benefit_source_id'],
            'grants': [{**dict(grant), 'payload': json.loads(grant['payload'])} for grant in db.execute('''SELECT
                id,kind,target,payload,status,attempts,error,updated FROM package_benefit_grants
                WHERE purchase_id=? ORDER BY id''', (row['benefit_source_id'],))]}


def process_purchase(purchase_id):
    """Claim external jobs outside the network call; preserve failed jobs for explicit retry."""
    from app.db import connect
    from app.services import feishu_permissions
    from app.config import load_config
    lease = load_config()['feishu']['lease_seconds']
    with connect() as db:
        row = db.execute('SELECT benefit_source_id FROM service_package_purchases WHERE id=?', (purchase_id,)).fetchone()
        if not row:
            return
        source_id = row['benefit_source_id']
        ids = [row['id'] for row in db.execute("SELECT id FROM package_benefit_grants WHERE purchase_id=? AND kind='feishu'", (source_id,))]
    for gid in ids:
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            changed = db.execute('''UPDATE package_benefit_grants SET status='processing',attempts=attempts+1,
                lease_until=?,updated=? WHERE id=? AND
                (status IN ('pending','failed') OR (status='processing' AND lease_until<?))''', (now + lease, now, gid, now))
            if not changed.rowcount:
                continue
            job = db.execute('SELECT payload,attempts FROM package_benefit_grants WHERE id=?', (gid,)).fetchone()
            payload, attempt = json.loads(job['payload']), job['attempts']
        error = ''
        try:
            feishu_permissions.grant(payload['resource'], payload['recipient'])
        except feishu_permissions.GrantError as failure:
            error = str(failure)
        except Exception:
            # Unexpected provider failures must leave a visible, retryable job without leaking payloads.
            error = '飞书授权处理异常，结果待核实，请检查服务端配置后重试'
        with connect() as db:
            db.execute('''UPDATE package_benefit_grants SET status=?,error=?,lease_until=0,updated=?
                WHERE id=? AND status='processing' AND attempts=?''',
                ('failed' if error else 'granted', error, time.time(), gid, attempt))
