"""Cumulative leaderboards for ordinary practice accounts."""
from collections.abc import Mapping
import sqlite3


_LIMIT = 100


def _ranked(rows: list[sqlite3.Row], *, value_key: str = 'value') -> list[dict]:
    """Return stable, ordinal rankings without exposing account internals."""
    ordered = sorted(
        rows,
        key=lambda row: (-int(row[value_key] or 0), str(row['username']).casefold(), int(row['id'])),
    )[:_LIMIT]
    return [
        {
            'rank': index,
            'username': row['username'],
            'value': int(row[value_key] or 0),
            **({key: int(row[key] or 0) for key in ('training_checkins', 'coding_checkins') if key in row.keys()}),
        }
        for index, row in enumerate(ordered, 1)
    ]


def _board(db: sqlite3.Connection, query: str) -> list[dict]:
    """Execute a leaderboard aggregation query and normalize its rows."""
    return _ranked(list(db.execute(query)))


def snapshot(db: sqlite3.Connection, user: Mapping) -> dict:
    """Build the three cumulative boards and the current ordinary user's ranks."""
    boards = {
        'checkins': _board(db, '''
            SELECT u.id, u.username,
                   COALESCE(training.total, 0) + COALESCE(coding.total, 0) AS value,
                   COALESCE(training.total, 0) AS training_checkins,
                   COALESCE(coding.total, 0) AS coding_checkins
            FROM users u
            LEFT JOIN (SELECT user_id, COUNT(*) AS total FROM training_checkins GROUP BY user_id) training
              ON training.user_id = u.id
            LEFT JOIN (SELECT user_id, COUNT(*) AS total FROM coding_checkins GROUP BY user_id) coding
              ON coding.user_id = u.id
            WHERE u.is_admin = 0
        '''),
        'training_questions': _board(db, '''
            SELECT u.id, u.username, COUNT(q.question_id) AS value
            FROM users u
            LEFT JOIN training_daily_questions q ON q.user_id = u.id
            WHERE u.is_admin = 0
            GROUP BY u.id, u.username
        '''),
        'coding_solved': _board(db, '''
            SELECT u.id, u.username, COUNT(DISTINCT CASE WHEN s.status = 'Accepted' THEN s.question_id END) AS value
            FROM users u
            LEFT JOIN coding_submissions s ON s.user_id = u.id
            WHERE u.is_admin = 0
            GROUP BY u.id, u.username
        '''),
    }
    current_id = int(user['id'])
    current = None
    if not bool(user['is_admin']):
        current = {
            key: next((item['rank'] for item in items if item['username'] == user['username']), None)
            for key, items in boards.items()
        }
    return {'boards': boards, 'me': current, 'metric_labels': {
        'checkins': '打卡天数',
        'training_questions': '抽题训练',
        'coding_solved': '上机通过',
    }}
