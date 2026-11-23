"""Invitation attribution, signup rewards, and per-user referral history."""
import secrets
from fastapi import HTTPException
from app.services import points, service_packages


def _code(db):
    """Generate a unique referral code using cryptographically secure randomness."""
    while True:
        value = secrets.token_urlsafe(9).replace('-', '').replace('_', '').upper()[:12]
        if not db.execute('SELECT 1 FROM users WHERE invite_code=?', (value,)).fetchone():
            return value


def initialize(db):
    """Add referral fields and backfill unique codes for existing accounts."""
    columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
    for name, declaration in (
        ('invite_code', "TEXT NOT NULL DEFAULT ''"),
        ('referrer_id', 'INTEGER REFERENCES users(id) ON DELETE SET NULL'),
        ('purchase_service', "TEXT NOT NULL DEFAULT ''"),
        ('rebate_redeemed', 'INTEGER NOT NULL DEFAULT 0 CHECK(rebate_redeemed IN (0,1))'),
    ):
        if name not in columns:
            db.execute(f'ALTER TABLE users ADD COLUMN {name} {declaration}')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_invite_code ON users(invite_code) WHERE invite_code!=""')
    for row in db.execute("SELECT id FROM users WHERE invite_code='' OR invite_code IS NULL").fetchall():
        db.execute('UPDATE users SET invite_code=? WHERE id=?', (_code(db), row['id']))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('invite_signup_points','3')")
    db.execute('CREATE INDEX IF NOT EXISTS users_by_referrer ON users(referrer_id,id)')


def attribute_signup(db, invitation_code):
    """Validate an optional code and award its owner once when the account is created."""
    if not invitation_code or not invitation_code.strip():
        return None
    code = invitation_code.strip().upper()
    inviter = db.execute('SELECT id,is_active FROM users WHERE invite_code=?', (code,)).fetchone()
    if not inviter or not inviter['is_active']:
        raise HTTPException(422, '邀请码无效，请检查后重试；也可以留空注册')
    return inviter['id']


def record_signup_reward(db, inviter_id, new_user_id):
    """Credit a referrer in the account-creation transaction."""
    if inviter_id is None:
        return
    reward = int(db.execute("SELECT value FROM app_settings WHERE key='invite_signup_points'").fetchone()[0])
    if reward:
        points.adjust(db, inviter_id, reward, kind='invite_signup', reference=str(new_user_id))


def profile(db, uid):
    """Return the signed-in user's invite link and referred accounts."""
    user = db.execute('SELECT username,invite_code FROM users WHERE id=?', (uid,)).fetchone()
    if not user:
        raise HTTPException(404, '账号不存在')
    totals = service_packages.summaries(db)
    items = [{**dict(row), **totals[row['id']]} for row in db.execute(
        'SELECT id,username,email FROM users WHERE referrer_id=? AND is_admin=0 ORDER BY id', (uid,))]
    return {'invite_code': user['invite_code'], 'signup_reward_points': int(db.execute(
        "SELECT value FROM app_settings WHERE key='invite_signup_points'").fetchone()[0]),
        'total_invited': len(items), 'items': items}
