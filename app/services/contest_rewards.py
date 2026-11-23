"""Settle each completed contest once in the caller's immediate write transaction."""
import json
import time

from app.services import points
from app.services.contest_scoring import ranked_rows

TERMINAL_STATUSES = ('Accepted', 'Wrong Answer', 'Output Limit Exceeded', 'Time Limit Exceeded',
                     'Memory Limit Exceeded', 'Runtime Error', 'Compile Error', 'System Error', 'Submission Failed')


def initialize(db):
    """Keep award snapshots after contest or account deletion and initialize rollout once."""
    db.execute('''CREATE TABLE IF NOT EXISTS contest_reward_settlements(
        contest_id INTEGER PRIMARY KEY,contest_title TEXT NOT NULL,ended_at REAL NOT NULL,
        rewards TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS contest_reward_grants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL REFERENCES contest_reward_settlements(contest_id),
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        username TEXT NOT NULL,rank INTEGER NOT NULL,score INTEGER NOT NULL,points INTEGER NOT NULL,
        UNIQUE(contest_id,rank),UNIQUE(contest_id,user_id))''')
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('contest_rewards_started',?)", (str(time.time()),))
    db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('contest_rewards','[9,6,3]')")


def rewards(db):
    """Return the administrator's first, second and third place points amounts."""
    return json.loads(db.execute("SELECT value FROM app_settings WHERE key='contest_rewards'").fetchone()[0])


def settle_due(db, now=None, contest_id=None):
    """Award in-time positive-score contestants after all in-time judging finishes.

    The caller holds BEGIN IMMEDIATE so snapshots, wallet changes and receipts commit
    together. Contest IDs intentionally have no live-contest foreign key: deleting
    a contest preserves its settlement and cannot make an old ID eligible again.
    """
    now = time.time() if now is None else now
    activated = float(db.execute("SELECT value FROM app_settings WHERE key='contest_rewards_started'").fetchone()[0])
    query = '''SELECT * FROM contests WHERE ends>? AND ends<? AND id NOT IN
        (SELECT contest_id FROM contest_reward_settlements)'''
    args = [activated, now]
    if contest_id is not None:
        query += ' AND id=?'
        args.append(contest_id)
    count = 0
    for contest in list(db.execute(query, args)):
        placeholders = ','.join('?' for _ in TERMINAL_STATUSES)
        pending = db.execute(f'''SELECT 1 FROM submissions s
            JOIN problems p ON p.id=s.problem_id JOIN users u ON u.id=s.user_id
            WHERE p.contest_id=? AND s.created>=? AND s.created<=? AND u.is_admin=0
            AND s.status NOT IN ({placeholders}) LIMIT 1''',
            (contest['id'], contest['starts'], contest['ends'], *TERMINAL_STATUSES)).fetchone()
        if pending:
            continue
        amounts = rewards(db)
        db.execute('''INSERT INTO contest_reward_settlements(contest_id,contest_title,ended_at,rewards,created)
            VALUES (?,?,?,?,?)''', (contest['id'], contest['title'], contest['ends'], json.dumps(amounts), now))
        for row, amount in zip(ranked_rows(db, contest)[:3], amounts):
            if row['score'] <= 0 or amount <= 0:
                continue
            points.adjust(db, row['user_id'], amount, kind='contest_reward',
                          reference=f'{contest["id"]}/{row["rank"]}')
            db.execute('''INSERT INTO contest_reward_grants(contest_id,user_id,username,rank,score,points)
                VALUES (?,?,?,?,?,?)''',
                (contest['id'], row['user_id'], row['username'], row['rank'], row['score'], amount))
        count += 1
    return count


def summary(db, cid):
    """Project configured or settled amounts, plus immutable award receipts."""
    settlement = db.execute('SELECT rewards FROM contest_reward_settlements WHERE contest_id=?', (cid,)).fetchone()
    activated = float(db.execute("SELECT value FROM app_settings WHERE key='contest_rewards_started'").fetchone()[0])
    contest = db.execute('SELECT ends FROM contests WHERE id=?', (cid,)).fetchone()
    return {'amounts': json.loads(settlement['rewards']) if settlement else rewards(db),
            'settled': bool(settlement),
            'eligible': bool(settlement) or bool(contest and contest['ends'] > activated),
            'grants': [dict(row) for row in db.execute(
                'SELECT user_id,username,rank,points FROM contest_reward_grants WHERE contest_id=? ORDER BY rank', (cid,))]}
