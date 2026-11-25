"""Package catalog and purchase snapshots; catalog availability controls reversible visibility."""
import sqlite3
import time
import json
from fastapi import HTTPException
from app.services.announcements import render_markdown


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS service_packages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        price_fen INTEGER NOT NULL CHECK(price_fen>=0),
        rebate_basis_points INTEGER NOT NULL DEFAULT 500 CHECK(rebate_basis_points BETWEEN 0 AND 10000),
        enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
        created REAL NOT NULL, updated REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS service_package_purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        package_id INTEGER NOT NULL REFERENCES service_packages(id),
        package_name TEXT NOT NULL, price_fen INTEGER NOT NULL CHECK(price_fen>=0),
        rebate_basis_points INTEGER NOT NULL CHECK(rebate_basis_points BETWEEN 0 AND 10000),
        redeemed INTEGER NOT NULL DEFAULT 0 CHECK(redeemed IN (0,1)),
        created REAL NOT NULL, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        removed REAL)''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS service_purchase_active
        ON service_package_purchases(user_id,package_id) WHERE removed IS NULL''')
    from app.services.package_benefits import initialize as initialize_benefits
    initialize_benefits(db)


def catalog(db):
    return [{**dict(row), 'benefits': json.loads(row['benefits']), 'enabled': bool(row['enabled']),
             'description_html': render_markdown(row['description'])}
            for row in db.execute('''SELECT p.*, (SELECT COUNT(*) FROM service_package_purchases b
                WHERE b.package_id=p.id AND b.removed IS NULL) AS purchase_count
                FROM service_packages p ORDER BY p.id DESC''')]


def save_package(db, pid, fields, actor=None):
    if pid is not None and not db.execute('SELECT 1 FROM service_packages WHERE id=?', (pid,)).fetchone():
        raise HTTPException(404, '套餐不存在')
    values = dict(fields)
    if 'name' in values:
        values['name'] = values['name'].strip()
        if not values['name']:
            raise HTTPException(422, '套餐名不能为空')
    for source, target in (('price_yuan', 'price_fen'), ('rebate_percent', 'rebate_basis_points')):
        if source in values:
            values[target] = int(values.pop(source) * 100)
    if 'benefits' in values:
        from app.services.package_benefits import Benefits, validate_courses
        try:
            benefits = Benefits.model_validate(values['benefits']).model_dump(mode='json')
        except Exception as error:
            from pydantic import ValidationError
            if isinstance(error, ValidationError):
                raise HTTPException(422, error.errors(include_input=False, include_context=False)) from error
            raise
        validate_courses(db, benefits, actor)
        values['benefits'] = json.dumps(benefits, ensure_ascii=False)
    values['updated'] = time.time()
    if pid is None:
        values['created'] = values['updated']
        pid = db.execute(f'INSERT INTO service_packages({",".join(values)}) VALUES ({",".join("?" for _ in values)})',
                         tuple(values.values())).lastrowid
    else:
        db.execute(f'UPDATE service_packages SET {",".join(key + "=?" for key in values)} WHERE id=?',
                   (*values.values(), pid))
    return next(item for item in catalog(db) if item['id'] == pid)


def _rebate(price, rate):
    """Round a purchase's fractional fen to the nearest fen, with halves rounded up."""
    return (price * rate + 5000) // 10000


def _summary(rows, has_inviter):
    pending = sum(_rebate(row['price_fen'], row['rebate_basis_points']) for row in rows if not row['redeemed']) if has_inviter else 0
    redeemed = sum(_rebate(row['price_fen'], row['rebate_basis_points']) for row in rows if row['redeemed']) if has_inviter else 0
    return {'purchase_count': len(rows), 'purchase_total_fen': sum(row['price_fen'] for row in rows),
            'rebate_total_fen': pending + redeemed, 'pending_rebate_fen': pending, 'redeemed_rebate_fen': redeemed,
            'rebate_status': ('redeemed' if all(row['redeemed'] for row in rows) else 'pending') if rows and has_inviter else 'unset'}


def summaries(db):
    """Calculate visible purchases in one query for account and invitation lists."""
    grouped = {}
    for row in db.execute('''SELECT b.* FROM service_package_purchases b JOIN service_packages p ON p.id=b.package_id
                            WHERE p.enabled=1 AND b.removed IS NULL'''):
        grouped.setdefault(row['user_id'], []).append(row)
    return {row['id']: _summary(grouped.get(row['id'], []), row['referrer_id'] is not None)
            for row in db.execute('SELECT id,referrer_id FROM users')}


def purchases(db, uid):
    user = db.execute('SELECT referrer_id FROM users WHERE id=?', (uid,)).fetchone()
    if user is None:
        raise HTTPException(404, '用户不存在')
    rows = db.execute('''SELECT b.* FROM service_package_purchases b JOIN service_packages p ON p.id=b.package_id
                        WHERE b.user_id=? AND p.enabled=1 AND b.removed IS NULL ORDER BY b.id DESC''', (uid,)).fetchall()
    return {**_summary(rows, user['referrer_id'] is not None), 'items': [
        {key: row[key] for key in ('id', 'package_id', 'package_name', 'price_fen', 'rebate_basis_points', 'created')}
        | {'rebate_fen': _rebate(row['price_fen'], row['rebate_basis_points']) if user['referrer_id'] is not None else 0,
        'redeemed': bool(row['redeemed'])} for row in rows]}


def benefit_details(db, uid, purchase_id):
    from app.services.package_benefits import details
    return details(db, uid, purchase_id)


def read_purchase(uid, purchase_id):
    from app.db import connect
    with connect() as db:
        result = purchases(db, uid)
        result['items'] = [item for item in result['items'] if item['id'] == purchase_id]
        result['benefits'] = benefit_details(db, uid, purchase_id)
        return result


def add_purchase(db, uid, pid, actor_id, *, recipient=None, actor=None):
    package = db.execute('SELECT * FROM service_packages WHERE id=?', (pid,)).fetchone()
    if not package or not package['enabled']:
        raise HTTPException(409, '套餐不存在或已下架，请刷新后重试')
    benefits = json.loads(package['benefits'])
    from app.services.package_benefits import FeishuRecipient, apply
    if benefits['feishu_resources'] and recipient:
        try:
            recipient = FeishuRecipient.model_validate(recipient).model_dump()
        except ValueError:
            raise HTTPException(422, '请输入有效飞书邮箱或绑定手机号；非中国大陆手机号需包含 + 国际区号') from None
    try:
        purchase_id = db.execute('''INSERT INTO service_package_purchases(user_id,package_id,package_name,price_fen,
            rebate_basis_points,created,created_by) VALUES (?,?,?,?,?,?,?)''',
            (uid, pid, package['name'], package['price_fen'], package['rebate_basis_points'], time.time(), actor_id)).lastrowid
        apply(db, purchase_id, uid, pid, benefits, recipient, actor)
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, '该用户已购买此套餐，请勿重复登记') from error
    return {**purchases(db, uid), 'purchase_id': purchase_id}


def remove_purchase(db, uid, purchase_id):
    changed = db.execute('UPDATE service_package_purchases SET removed=? WHERE id=? AND user_id=? AND removed IS NULL',
                         (time.time(), purchase_id, uid))
    if not changed.rowcount:
        raise HTTPException(404, '购买记录不存在或已移除')


def settle(db, uid, redeemed):
    if purchases(db, uid)['rebate_status'] == 'unset':
        raise HTTPException(409, '没有有效购买记录或邀请者，无需设置返利状态')
    db.execute('''UPDATE service_package_purchases SET redeemed=? WHERE user_id=? AND removed IS NULL
        AND package_id IN (SELECT id FROM service_packages WHERE enabled=1)''', (int(redeemed), uid))
    return purchases(db, uid)
