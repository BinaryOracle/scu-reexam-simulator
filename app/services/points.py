"""Atomic points wallet and idempotent purchases, owned by the caller transaction."""
import time
from fastapi import HTTPException


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS points_purchases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        product TEXT NOT NULL,quantity INTEGER NOT NULL,cost INTEGER NOT NULL,created REAL NOT NULL,
        request_key TEXT NOT NULL,UNIQUE(user_id,request_key))''')
    db.execute('''CREATE TABLE IF NOT EXISTS leaderboard_settlements(
        period_end TEXT PRIMARY KEY,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS leaderboard_reward_grants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,period_end TEXT NOT NULL REFERENCES leaderboard_settlements(period_end),
        board TEXT NOT NULL,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        username TEXT NOT NULL,rank INTEGER NOT NULL,value INTEGER NOT NULL,points INTEGER NOT NULL,
        UNIQUE(period_end,board,rank))''')
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('leaderboard_rewards_started',?)",
               (str(time.time()),))
    columns = {row['name'] for row in db.execute('PRAGMA table_info(voucher_packages)')}
    if 'deleted' not in columns:
        db.execute('ALTER TABLE voucher_packages ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1))')
    # Earlier versions only hid removed packages. Apply the intended destructive
    # semantics once at startup: their issued codes are no longer redeemable.
    db.execute('DELETE FROM vouchers WHERE package IN (SELECT id FROM voucher_packages WHERE deleted=1)')
    db.execute('DELETE FROM voucher_packages WHERE deleted=1')


def cost(db):
    return int(db.execute("SELECT value FROM app_settings WHERE key='interview_points_cost'").fetchone()[0])


def adjust(db, uid, delta, *, kind, reference=''):
    """Apply an exact wallet change without allowing an overdraft."""
    user = db.execute('SELECT points FROM users WHERE id=?', (uid,)).fetchone()
    if user is None:
        raise HTTPException(404, '账号不存在')
    balance = user['points'] + delta
    if balance < 0:
        raise HTTPException(409, '积分不足，请先通过签到、排行榜奖励或卡密兑换获取积分')
    db.execute('UPDATE users SET points=? WHERE id=?', (balance, uid))
    db.execute('INSERT INTO points_ledger(user_id,delta,balance_after,kind,reference,created) VALUES (?,?,?,?,?,?)',
               (uid, delta, balance, kind, reference, time.time()))
    return balance


def shop(db, uid):
    user = db.execute('SELECT points,interview_credits,is_admin FROM users WHERE id=?', (uid,)).fetchone()
    return {'points': user['points'], 'remaining': None if user['is_admin'] else user['interview_credits'],
            'products': [{'id': 'interview', 'name': '模拟面试次数', 'points_cost': cost(db), 'quantity': 1}],
            'purchases': [dict(row) for row in db.execute('SELECT id,product,quantity,cost,created FROM points_purchases WHERE user_id=? ORDER BY id DESC LIMIT 50', (uid,))]}


def purchase(db, uid, quantity, request_key, expected_unit_cost):
    """Debit points and grant interview allowance exactly once per client request."""
    from app.services import credits
    previous = db.execute('SELECT * FROM points_purchases WHERE user_id=? AND request_key=?', (uid, request_key)).fetchone()
    if previous:
        if previous['quantity'] != quantity:
            raise HTTPException(409, '该购买请求已处理，请勿更改数量后重试')
        return {'already_purchased': True, 'purchase_id': previous['id'], **shop(db, uid)}
    user = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if user['is_admin']:
        raise HTTPException(409, '管理员已开通模拟面试，无需购买次数')
    unit_cost = cost(db)
    if unit_cost != expected_unit_cost:
        raise HTTPException(409, '商品积分价格已调整，请刷新后确认购买')
    total = unit_cost * quantity
    pid = db.execute('INSERT INTO points_purchases(user_id,product,quantity,cost,created,request_key) VALUES (?,\'interview\',?,?,?,?)',
                     (uid, quantity, total, time.time(), request_key)).lastrowid
    adjust(db, uid, -total, kind='purchase_interview', reference=str(pid))
    credits.adjust(db, uid, user['interview_credits'] + quantity, kind='points_purchase', reference=str(pid))
    return {'already_purchased': False, 'purchase_id': pid, **shop(db, uid)}
