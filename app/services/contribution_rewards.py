"""Versioned, approval-based rewards for user-contributed training questions."""
import time
from fastapi import HTTPException
from app.services import credits


DEFAULT_QUESTIONS = 5
DEFAULT_CREDITS = 1


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS contribution_reward_policies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,questions_per_reward INTEGER NOT NULL CHECK(questions_per_reward>0),
        credits_per_reward INTEGER NOT NULL CHECK(credits_per_reward>0),created REAL NOT NULL,
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,active INTEGER NOT NULL CHECK(active IN (0,1)))''')
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS contribution_one_active_policy
        ON contribution_reward_policies(active) WHERE active=1''')
    db.execute('''CREATE TABLE IF NOT EXISTS contribution_approvals(
        question_id INTEGER PRIMARY KEY REFERENCES training_questions(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,policy_id INTEGER NOT NULL REFERENCES contribution_reward_policies(id),
        created REAL NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS contribution_approvals_by_user ON contribution_approvals(user_id,policy_id)')
    db.execute('''CREATE TABLE IF NOT EXISTS contribution_reward_grants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        policy_id INTEGER NOT NULL REFERENCES contribution_reward_policies(id),milestone INTEGER NOT NULL CHECK(milestone>0),
        credits INTEGER NOT NULL CHECK(credits>0),ledger_id INTEGER REFERENCES credit_ledger(id) ON DELETE SET NULL,
        created REAL NOT NULL,UNIQUE(policy_id,user_id,milestone))''')
    db.execute('CREATE INDEX IF NOT EXISTS contribution_grants_by_user ON contribution_reward_grants(user_id,created)')
    if not db.execute('SELECT 1 FROM contribution_reward_policies LIMIT 1').fetchone():
        db.execute('''INSERT INTO contribution_reward_policies(questions_per_reward,credits_per_reward,created,active)
            VALUES (?,?,?,1)''', (DEFAULT_QUESTIONS, DEFAULT_CREDITS, time.time()))


def current_policy(db):
    row = db.execute('SELECT * FROM contribution_reward_policies WHERE active=1').fetchone()
    if row is None:
        raise RuntimeError('题目投稿奖励规则未初始化')
    return dict(row)


def progress(db, uid):
    user = db.execute('SELECT is_admin FROM users WHERE id=?', (uid,)).fetchone()
    policy = current_policy(db)
    if user is None:
        raise HTTPException(404, '账号不存在')
    if user['is_admin']:
        return {'policy': {key: policy[key] for key in ('id','questions_per_reward','credits_per_reward')},
                'approved_count': 0, 'remaining_questions': 0, 'credits_earned': 0, 'grants': [], 'exempt': True}
    approved = db.execute('SELECT COUNT(*) FROM contribution_approvals WHERE user_id=? AND policy_id=?',
                          (uid, policy['id'])).fetchone()[0]
    grants = [dict(row) for row in db.execute('''SELECT g.credits,g.milestone,g.created FROM contribution_reward_grants g
        WHERE g.user_id=? ORDER BY g.id DESC LIMIT 20''', (uid,))]
    total = db.execute('SELECT COALESCE(SUM(credits),0) FROM contribution_reward_grants WHERE user_id=?', (uid,)).fetchone()[0]
    return {'policy': {key: policy[key] for key in ('id','questions_per_reward','credits_per_reward')},
            'approved_count': approved, 'remaining_questions': policy['questions_per_reward'] - approved % policy['questions_per_reward'],
            'credits_earned': total, 'grants': grants, 'exempt': False}


def approve_question(db, question, now=None):
    """Record an approved ordinary-user contribution and grant each new threshold once."""
    if question['owner_user_id'] is None or question['owner_admin']:
        return None
    now = time.time() if now is None else now
    policy = current_policy(db)
    cursor = db.execute('''INSERT OR IGNORE INTO contribution_approvals(question_id,user_id,policy_id,created)
        VALUES (?,?,?,?)''', (question['id'], question['owner_user_id'], policy['id'], now))
    if cursor.rowcount == 0:
        return None
    approved = db.execute('SELECT COUNT(*) FROM contribution_approvals WHERE user_id=? AND policy_id=?',
                          (question['owner_user_id'], policy['id'])).fetchone()[0]
    earned = 0
    milestone = approved // policy['questions_per_reward']
    if milestone > 0:
        if db.execute('SELECT 1 FROM contribution_reward_grants WHERE user_id=? AND policy_id=? AND milestone=?',
                      (question['owner_user_id'], policy['id'], milestone)).fetchone():
            return {'approved_count': approved, 'credits_granted': 0}
        balance = db.execute('SELECT interview_credits FROM users WHERE id=?', (question['owner_user_id'],)).fetchone()[0]
        credits.adjust(db, question['owner_user_id'], balance + policy['credits_per_reward'],
                       kind='question_contribution', reference=f"{policy['id']}:{milestone}")
        ledger_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('''INSERT INTO contribution_reward_grants(user_id,policy_id,milestone,credits,ledger_id,created)
            VALUES (?,?,?,?,?,?)''', (question['owner_user_id'], policy['id'], milestone,
                                      policy['credits_per_reward'], ledger_id, now))
        earned += policy['credits_per_reward']
    return {'approved_count': approved, 'credits_granted': earned}


def set_policy(db, actor_id, questions, reward_credits):
    old = current_policy(db)
    if old['questions_per_reward'] == questions and old['credits_per_reward'] == reward_credits:
        return old
    db.execute('UPDATE contribution_reward_policies SET active=0 WHERE active=1')
    cursor = db.execute('''INSERT INTO contribution_reward_policies(questions_per_reward,credits_per_reward,created,created_by,active)
        VALUES (?,?,?,?,1)''', (questions, reward_credits, time.time(), actor_id))
    return dict(db.execute('SELECT * FROM contribution_reward_policies WHERE id=?', (cursor.lastrowid,)).fetchone())


def admin_summary(db, page=1, page_size=20):
    policy = current_policy(db)
    total = db.execute('SELECT COUNT(*) FROM users WHERE is_admin=0').fetchone()[0]
    items = [dict(row) for row in db.execute('''SELECT u.id,u.username,
        (SELECT COUNT(*) FROM contribution_approvals a WHERE a.user_id=u.id AND a.policy_id=?) AS approved_count,
        (SELECT COALESCE(SUM(g.credits),0) FROM contribution_reward_grants g WHERE g.user_id=u.id) AS credits_earned
        FROM users u WHERE u.is_admin=0 ORDER BY approved_count DESC,u.id LIMIT ? OFFSET ?''',
        (policy['id'], page_size, (page - 1) * page_size))]
    return {'policy': {key: policy[key] for key in ('id','questions_per_reward','credits_per_reward','created')},
            'items': items, 'total': total, 'page': page, 'page_size': page_size}
