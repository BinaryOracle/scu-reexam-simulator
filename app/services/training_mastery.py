"""Personal self-ratings and weighted sampling without replacement."""
import heapq
import math
import random
from app.config import load_config


def initialize_mastery(db, *, backfill):
    """Create private per-question state and replay existing ratings once on upgrade."""
    db.execute('''CREATE TABLE IF NOT EXISTS training_mastery(
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        question_id INTEGER NOT NULL REFERENCES training_questions(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('again','known')),
        review_count INTEGER NOT NULL DEFAULT 0,again_count INTEGER NOT NULL DEFAULT 0,
        known_count INTEGER NOT NULL DEFAULT 0,last_rated REAL NOT NULL,
        PRIMARY KEY(user_id,question_id))''')
    if backfill:
        rows = db.execute('''SELECT s.user_id,c.question_id,c.rating,c.completed_at FROM training_session_cards c
            JOIN training_sessions s ON s.id=c.session_id WHERE c.completed_at IS NOT NULL
            AND c.rating IN ('again','known') ORDER BY c.completed_at,c.id''').fetchall()
        for row in rows:
            record(db, row['user_id'], row['question_id'], row['rating'], row['completed_at'])


def record(db, uid, qid, rating, timestamp):
    """Caller records only a newly completed available card within its write transaction."""
    if rating not in ('again', 'known'):
        return
    db.execute('''INSERT INTO training_mastery(user_id,question_id,status,review_count,again_count,known_count,last_rated)
        VALUES (?,?,?,1,?,?,?) ON CONFLICT(user_id,question_id) DO UPDATE SET
        status=excluded.status,review_count=training_mastery.review_count+1,
        again_count=training_mastery.again_count+excluded.again_count,
        known_count=training_mastery.known_count+excluded.known_count,last_rated=excluded.last_rated''',
        (uid, qid, rating, int(rating == 'again'), int(rating == 'known'), timestamp))


def personal_state(db, uid, qid):
    row = db.execute('SELECT status,review_count,again_count,known_count,last_rated FROM training_mastery WHERE user_id=? AND question_id=?',
                     (uid, qid)).fetchone()
    return dict(row) if row else dict(status='unseen', review_count=0, again_count=0, known_count=0, last_rated=None)


def weights(db, uid, rows):
    config = load_config()['training']
    states = {row['question_id']: row['status'] for row in db.execute('SELECT question_id,status FROM training_mastery WHERE user_id=?', (uid,))}
    return {row['id']: config['weight_' + states.get(row['id'], 'unseen')] for row in rows}


def weighted_sample(rows, size, weights, *, rng=None):
    """Exponential races produce a weighted ordering; keep each candidate at most once."""
    generator = rng if rng is not None else random
    return heapq.nsmallest(min(size, len(rows)), rows,
                          key=lambda row: -math.log1p(-generator.random()) / weights[row['id']])
