"""Atomic peer transfers: one debit, one credit, and one immutable receipt."""
import time
from fastapi import HTTPException
from app.services.points import adjust


def initialize_transfers(db):
    db.execute('''CREATE TABLE IF NOT EXISTS credit_transfers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,sender_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        recipient_id INTEGER REFERENCES users(id) ON DELETE SET NULL,sender_name TEXT NOT NULL,
        recipient_name TEXT NOT NULL,credits INTEGER NOT NULL CHECK(credits>0),
        idempotency_key TEXT NOT NULL,created REAL NOT NULL,UNIQUE(sender_id,idempotency_key))''')
    db.execute('CREATE INDEX IF NOT EXISTS transfers_by_recipient ON credit_transfers(recipient_id,id)')
    if 'currency' not in {row['name'] for row in db.execute('PRAGMA table_info(credit_transfers)')}:
        db.execute("ALTER TABLE credit_transfers ADD COLUMN currency TEXT NOT NULL DEFAULT 'credits'")


def transfer(db, uid, recipient_name, amount, request_key):
    """Caller holds BEGIN IMMEDIATE; idempotency covers retries and unknown outcomes."""
    sender = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    identifier = recipient_name.strip()
    existing = db.execute('SELECT * FROM credit_transfers WHERE sender_id=? AND idempotency_key=?', (uid, request_key)).fetchone()
    if existing:
        recipient_matches = identifier == existing['recipient_name']
        if existing['recipient_id'] is not None:
            previous_recipient = db.execute('SELECT username,email FROM users WHERE id=?', (existing['recipient_id'],)).fetchone()
            if previous_recipient:
                recipient_matches = recipient_matches or identifier == previous_recipient['username']
                recipient_matches = recipient_matches or bool(previous_recipient['email'] and identifier.casefold() == previous_recipient['email'].casefold())
        if not recipient_matches or existing['credits'] != amount:
            raise HTTPException(409, '本次转赠标识已用于其他内容，请重新发起')
        return dict(id=existing['id'], credits=amount, recipient=existing['recipient_name'],
                    remaining=sender['points'], points=amount, already_transferred=True)
    if sender['is_admin']:
        raise HTTPException(409, '管理员账号请通过后台管理用户积分，无需使用转赠')
    recipient = db.execute('SELECT * FROM users WHERE username=? AND is_active=1 AND is_admin=0', (identifier,)).fetchone()
    if recipient is None:
        recipient = db.execute('SELECT * FROM users WHERE email=? COLLATE NOCASE AND is_active=1 AND is_admin=0', (identifier,)).fetchone()
    if recipient is None:
        raise HTTPException(404, '未找到可接收转赠的普通用户，请核对用户名或邮箱')
    if recipient['id'] == uid:
        raise HTTPException(422, '不能向自己转赠积分')
    if sender['points'] < amount:
        raise HTTPException(409, '积分不足，请调整转赠数量')
    tid = db.execute('''INSERT INTO credit_transfers(sender_id,recipient_id,sender_name,recipient_name,
        credits,idempotency_key,created,currency) VALUES (?,?,?,?,?,?,?,'points')''',
        (uid, recipient['id'], sender['username'], recipient['username'], amount, request_key, time.time())).lastrowid
    adjust(db, uid, -amount, kind='transfer_out', reference=str(tid))
    adjust(db, recipient['id'], amount, kind='transfer_in', reference=str(tid))
    return dict(id=tid, credits=amount, recipient=recipient['username'], remaining=sender['points'] - amount, points=amount,
                already_transferred=False)


def history(db, uid, page):
    page_size = 5
    total = db.execute('SELECT COUNT(*) FROM credit_transfers WHERE sender_id=? OR recipient_id=?', (uid, uid)).fetchone()[0]
    items = []
    for row in db.execute('SELECT * FROM credit_transfers WHERE sender_id=? OR recipient_id=? ORDER BY id DESC LIMIT ? OFFSET ?',
                          (uid, uid, page_size, (page - 1) * page_size)):
        outgoing = row['sender_id'] == uid
        items.append(dict(id=row['id'], direction='out' if outgoing else 'in', credits=row['credits'],
                          other_username=row['recipient_name'] if outgoing else row['sender_name'], created=row['created'], currency=row['currency']))
    return dict(items=items, total=total, page=page, page_size=page_size)
