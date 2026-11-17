"""Interview balances and one-time voucher changes share the caller's transaction."""
import secrets
import sqlite3
import time
from fastapi import HTTPException
from app.config import load_config
from app.services import points

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
ADMIN_CREDITS = 999999


def default_credits(db):
    return int(db.execute("SELECT value FROM app_settings WHERE key='default_interview_credits'").fetchone()[0])


def packages(db):
    return [dict(row) for row in db.execute('SELECT id,price_fen,credits FROM voucher_packages WHERE deleted=0 ORDER BY created,id')]


def adjust(db, uid, balance, *, kind='admin', amount_fen=0, reference=''):
    """Set a nonnegative balance and record the exact difference in the same commit."""
    row = db.execute('SELECT interview_credits FROM users WHERE id=?', (uid,)).fetchone()
    if row is None:
        raise HTTPException(404, '账号不存在')
    delta = balance - row['interview_credits']
    db.execute('UPDATE users SET interview_credits=? WHERE id=?', (balance, uid))
    db.execute('''INSERT INTO credit_ledger(user_id,delta,balance_after,kind,amount_fen,reference,created)
        VALUES (?,?,?,?,?,?,?)''', (uid, delta, balance, kind, amount_fen, reference, time.time()))


def charge_interview(db, iid, uid):
    """Charge once at successful start, using fresh account values under a write lock."""
    interview = db.execute('SELECT credit_charged FROM interviews WHERE id=?', (iid,)).fetchone()
    if interview['credit_charged']:
        return
    user = db.execute('SELECT is_admin,interview_credits FROM users WHERE id=?', (uid,)).fetchone()
    if not user['is_admin']:
        if user['interview_credits'] < 1:
            raise HTTPException(409, '模拟面试次数已用完，请在个人主页使用积分购买次数后再开始')
        adjust(db, uid, user['interview_credits'] - 1, kind='interview', reference=str(iid))
    db.execute('UPDATE interviews SET credit_charged=1 WHERE id=?', (iid,))


def generate_vouchers(db, package, count):
    """Generate 120-bit random codes, with a unique database constraint and bounded retries."""
    config = load_config()['credits']
    if count > config['max_voucher_batch']:
        raise HTTPException(422, f"单批最多生成 {config['max_voucher_batch']} 张卡密")
    item = db.execute('SELECT * FROM voucher_packages WHERE id=? AND deleted=0', (package,)).fetchone()
    if item is None:
        raise HTTPException(422, '请选择有效的卡密套餐')
    batch = secrets.token_hex(12)
    result = []
    for _ in range(count):
        for attempt in range(10):
            raw = ''.join(secrets.choice(ALPHABET) for _ in range(24))
            code = '-'.join(raw[index:index + 4] for index in range(0, 24, 4))
            try:
                cursor = db.execute('''INSERT INTO vouchers(code,package,credits,price_fen,batch,created)
                    VALUES (?,?,?,?,?,?)''', (code, package, item['credits'], item['price_fen'], batch, time.time()))
            except sqlite3.IntegrityError:
                continue
            result.append({'id': cursor.lastrowid, 'code': code, 'package': package,
                           'credits': item['credits'], 'price_fen': item['price_fen'], 'batch': batch})
            break
        else:
            raise HTTPException(503, '卡密随机生成失败，请重试，本批次尚未保存')
    return result


def profile(db, uid):
    user = db.execute('SELECT username,is_admin,interview_credits,points FROM users WHERE id=?', (uid,)).fetchone()
    redemptions = [{'id': row['id'], 'code_suffix': row['code'][-4:], 'package': row['package'],
                    'credits': row['credits'], 'points': row['credits'], 'amount_fen': row['price_fen'], 'redeemed_at': row['redeemed_at']}
                   for row in db.execute('SELECT * FROM vouchers WHERE redeemed_by=? ORDER BY redeemed_at DESC,id DESC', (uid,))]
    return {'username': user['username'], 'is_admin': bool(user['is_admin']),
            'shop_url': load_config()['credits']['shop_url'],
            'points': user['points'], 'interview_points_cost': points.cost(db),
            'points_history': [dict(row) for row in db.execute('SELECT id,delta,balance_after,kind,reference,created FROM points_ledger WHERE user_id=? ORDER BY id DESC LIMIT 50', (uid,))],
            'remaining': None if user['is_admin'] else user['interview_credits'],
            'redeemed_amount_fen': sum(row['amount_fen'] for row in redemptions),
            'redemptions': redemptions}
