"""Separate practice leaderboards and transactional weekly points awards."""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from app.services import points

SHANGHAI = ZoneInfo('Asia/Shanghai')
BOARD_LABELS = {
    'training_checkins': '每日训练打卡', 'training_questions': '抽题训练',
    'coding_checkins': '算法带刷打卡', 'coding_solved': '题目通过',
}
SCOPES = {'training': ('training_checkins', 'training_questions'),
          'coding': ('coding_checkins', 'coding_solved')}
REWARDS = (3, 2, 1)
_LIMIT = 100


def period(now=None):
    """Use Saturday midnight in Shanghai as the Friday-night settlement instant."""
    current = now or datetime.now(SHANGHAI)
    if isinstance(current, (float, int)):
        current = datetime.fromtimestamp(current, SHANGHAI)
    current = current.astimezone(SHANGHAI)
    start = datetime.combine(current.date() - timedelta(days=(current.weekday() - 5) % 7), time(), SHANGHAI)
    return start, start + timedelta(days=7)


def _ranked(db, key, start=None, end=None):
    source = {
        'training_checkins': ('training_checkins', 'COUNT(*)', 'date', ''),
        'training_questions': ('training_daily_questions', 'COUNT(*)', 'date', ''),
        'coding_checkins': ('coding_checkins', 'COUNT(*)', 'date', ''),
        'coding_solved': ('coding_submissions', 'COUNT(DISTINCT question_id)', 'completed_date', "status='Accepted'"),
    }
    table, aggregate, date_column, clause = source[key]
    conditions, args = ([clause] if clause else []), []
    if start is not None:
        conditions.extend((f'{date_column}>=?', f'{date_column}<?'))
        args.extend((start.date().isoformat(), end.date().isoformat()))
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    rows = db.execute(f'''SELECT u.id,u.username,COALESCE(s.value,0) value FROM users u
        LEFT JOIN (SELECT user_id,{aggregate} value FROM {table}{where} GROUP BY user_id) s ON s.user_id=u.id
        WHERE u.is_admin=0 AND u.is_active=1''', args).fetchall()
    ordered = sorted(rows, key=lambda r: (-int(r['value']), r['username'].casefold(), r['id']))
    return [{'user_id': r['id'], 'rank': i, 'username': r['username'], 'value': int(r['value'])}
            for i, r in enumerate(ordered, 1)]


def snapshot(db, user, scope='training', range='weekly', now=None):
    """Return only the requested module's boards without exposing account identifiers."""
    start, end = period(now)
    boards, mine = {}, {}
    for key in SCOPES[scope]:
        rows = _ranked(db, key, start if range == 'weekly' else None, end)
        mine[key] = next((r['rank'] for r in rows if r['user_id'] == user['id']), None)
        boards[key] = [{k: v for k, v in row.items() if k != 'user_id'} for row in rows[:_LIMIT]]
    return {'scope': scope, 'range': range, 'boards': boards, 'me': None if user['is_admin'] else mine,
            'metric_labels': {key: BOARD_LABELS[key] for key in boards},
            'period': {'label': f'{start:%m.%d} — {(end - timedelta(days=1)):%m.%d}',
                       'starts_at': start.timestamp(), 'next_settlement_at': end.timestamp(),
                       'timezone': 'Asia/Shanghai'}, 'rewards': list(REWARDS)}


def settle_due(db, now=None):
    """Settle missed completed weeks once; the caller holds BEGIN IMMEDIATE."""
    now = now or datetime.now(SHANGHAI)
    if isinstance(now, (float, int)):
        now = datetime.fromtimestamp(now, SHANGHAI)
    latest_end, _ = period(now)
    activated = float(db.execute("SELECT value FROM app_settings WHERE key='leaderboard_rewards_started'").fetchone()[0])
    activated_at = datetime.fromtimestamp(activated, SHANGHAI)
    first_start, _ = period(activated_at)
    start, count = first_start, 0
    while start < latest_end:
        end = start + timedelta(days=7)
        end_key = end.isoformat()
        inserted = db.execute('INSERT OR IGNORE INTO leaderboard_settlements(period_end,created) VALUES (?,?)',
                              (end_key, now.timestamp())).rowcount
        if inserted:
            for key in BOARD_LABELS:
                for row, reward in zip(_ranked(db, key, start, end)[:3], REWARDS):
                    if row['value'] <= 0:
                        continue
                    reference = f'{end_key}/{key}/{row["rank"]}'
                    points.adjust(db, row['user_id'], reward, kind='leaderboard_reward', reference=reference)
                    db.execute('''INSERT INTO leaderboard_reward_grants(period_end,board,user_id,username,rank,value,points)
                        VALUES (?,?,?,?,?,?,?)''', (end_key, key, row['user_id'], row['username'], row['rank'], row['value'], reward))
            count += 1
        start = end
    return count
