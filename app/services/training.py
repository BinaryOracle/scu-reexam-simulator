"""Persisted practice rounds, ordered review cursors and atomic streak rewards."""
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.config import load_config
from app.services import credits
from app.services.training_schema import SECTIONS
from app.services import training_catalog as catalog
from app.services import training_mastery as mastery


def today():
    """Return the deployment's server-side calendar date (Shanghai by default)."""
    return datetime.fromtimestamp(time.time(), ZoneInfo(load_config()['training']['timezone'])).date()


def settings(db):
    config = load_config()['training']
    return {key: int(db.execute('SELECT value FROM app_settings WHERE key=?', ('training_' + key,)).fetchone()[0])
            for key in ('daily_goal', 'round_size')} | {
                key: config[key] for key in ('max_import_items', 'max_import_bytes')
            } | {'collections': [dict(row) for row in db.execute('SELECT id,name,category,active,section_id FROM training_collections ORDER BY position')]}


def day_activity(db, uid, *, freeze=False):
    date = today().isoformat()
    if freeze:
        db.execute('INSERT OR IGNORE INTO training_daily_activity(user_id,date,goal) VALUES (?,?,?)',
                   (uid, date, settings(db)['daily_goal']))
    activity = db.execute('SELECT goal FROM training_daily_activity WHERE user_id=? AND date=?', (uid, date)).fetchone()
    goal = activity[0] if activity else settings(db)['daily_goal']
    count = db.execute('SELECT COUNT(*) FROM training_daily_questions WHERE user_id=? AND date=?', (uid, date)).fetchone()[0]
    return date, goal, count


def home(db, user, section_id='interview'):
    if section_id not in dict(SECTIONS):
        raise HTTPException(422, '请选择有效的训练篇章')
    uid = user['id']
    date, goal, completed = day_activity(db, uid)
    last = db.execute('SELECT * FROM training_checkins WHERE user_id=? ORDER BY date DESC LIMIT 1', (uid,)).fetchone()
    checked = bool(last and last['date'] == date)
    streak = last['streak'] if last and last['date'] in (date, (today() - timedelta(days=1)).isoformat()) else 0
    milestone = (streak // 7 + 1) * 7
    account = db.execute('SELECT is_admin,interview_credits FROM users WHERE id=?', (uid,)).fetchone()
    collections = []
    for item in db.execute('SELECT * FROM training_collections WHERE active=1 ORDER BY position'):
        count = db.execute("""SELECT COUNT(*) FROM training_questions WHERE collection_id=? AND deleted=0 AND active=1
            AND (visibility='public' OR owner_user_id=?)""", (item['id'], uid)).fetchone()[0]
        favorites = db.execute("""SELECT COUNT(*) FROM training_favorites f JOIN training_questions q ON q.id=f.question_id
            WHERE f.user_id=? AND q.collection_id=? AND q.deleted=0 AND q.active=1
            AND (q.visibility='public' OR q.owner_user_id=?)""", (uid, item['id'], uid)).fetchone()[0]
        collections.append({key: item[key] for key in ('id', 'name', 'category', 'subject', 'section_id')} | {'count': count, 'favorites': favorites})
    active = db.execute("SELECT * FROM training_sessions WHERE user_id=? AND status='active'", (uid,)).fetchone()
    active_info = None
    if active:
        counts = db.execute('SELECT COUNT(*),COUNT(completed_at) FROM training_session_cards WHERE session_id=?', (active['id'],)).fetchone()
        active_info = {key: active[key] for key in ('id', 'mode', 'source', 'collection_id', 'section_id')} | dict(total=counts[0], completed=counts[1])
    dates = {row[0] for row in db.execute('SELECT date FROM training_checkins WHERE user_id=? ORDER BY date DESC LIMIT 7', (uid,))}
    recent = [(today() - timedelta(days=n)).isoformat() for n in reversed(range(7))]
    rewards = [dict(row) for row in db.execute('SELECT date,streak,credits FROM training_reward_grants WHERE user_id=? ORDER BY date DESC LIMIT 12', (uid,))]
    return dict(date=date, goal=goal, completed=completed, checked_in=checked, streak=streak,
                default_round_size=settings(db)['round_size'], max_round_questions=load_config()['training']['max_round_questions'],
                mastery={status: db.execute('''SELECT COUNT(*) FROM training_mastery m
                    JOIN training_questions q ON q.id=m.question_id JOIN training_collections c ON c.id=q.collection_id
                    WHERE m.user_id=? AND m.status=? AND q.deleted=0 AND q.active=1 AND c.active=1 AND c.section_id=?
                    AND (q.visibility='public' OR q.owner_user_id=?)''', (uid,status,section_id,uid)).fetchone()[0]
                    for status in ('again','known')},
                next_milestone=milestone, next_reward=milestone // 7,
                remaining=None if account['is_admin'] else account['interview_credits'], is_admin=bool(account['is_admin']),
                recent_days=[dict(date=d, checked_in=d in dates) for d in recent],
                sections=[{'id': sid, 'name': name, 'count': sum(c['count'] for c in collections if c['section_id'] == sid)} for sid, name in SECTIONS],
                section_id=section_id, collections=collections, active_session=active_info, rewards=rewards)


def checkin(db, user):
    """Caller owns BEGIN IMMEDIATE so attendance and credit updates are indivisible."""
    uid = user['id']
    date, goal, count = day_activity(db, uid)
    previous = db.execute('SELECT * FROM training_checkins WHERE user_id=? AND date=?', (uid, date)).fetchone()
    if previous:
        reward = db.execute('SELECT credits FROM training_reward_grants WHERE checkin_id=?', (previous['id'],)).fetchone()
        return dict(already_checked=True, credits=reward[0] if reward else 0, home=home(db, user))
    if count < goal:
        raise HTTPException(409, f'今天已完成 {count}/{goal} 道不同题，完成每日目标后即可签到')
    yesterday = (today() - timedelta(days=1)).isoformat()
    last = db.execute('SELECT * FROM training_checkins WHERE user_id=? AND date=?', (uid, yesterday)).fetchone()
    streak, start = (last['streak'] + 1, last['streak_start']) if last else (1, date)
    cid = db.execute('INSERT INTO training_checkins(user_id,date,streak,streak_start) VALUES (?,?,?,?)',
                     (uid, date, streak, start)).lastrowid
    account = db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    amount = streak // 7 if streak % 7 == 0 and not account['is_admin'] else 0
    if amount:
        credits.adjust(db, uid, account['interview_credits'] + amount, kind='checkin_reward', reference=str(cid))
        ledger_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('INSERT INTO training_reward_grants(checkin_id,user_id,date,streak,credits,ledger_id) VALUES (?,?,?,?,?,?)',
                   (cid, uid, date, streak, amount, ledger_id))
    return dict(already_checked=False, credits=amount, home=home(db, user))


def sort_key(row):
    return [row['collection_position'], row['position'], row['id']]


def filter_key(session):
    legacy = session['collection_id'] + ':' + session['source']
    return legacy if session['section_id'] == 'interview' else session['section_id'] + ':' + legacy


def get_session(db, sid, uid):
    session = db.execute('SELECT * FROM training_sessions WHERE id=? AND user_id=?', (sid, uid)).fetchone()
    if session is None:
        raise HTTPException(404, '训练记录不存在')
    cards = []
    for card in db.execute('SELECT * FROM training_session_cards WHERE session_id=? ORDER BY position', (sid,)):
        current = db.execute(catalog.SELECT + ' WHERE q.id=?', (card['question_id'],)).fetchone()
        available = catalog.accessible(current, uid)
        snapshot = json.loads(card['snapshot'])
        if not available:
            snapshot.update(question='此题已撤回或当前不可用', answer='', images=[], source_info={})
        favorite = db.execute('SELECT 1 FROM training_favorites WHERE user_id=? AND question_id=?', (uid, card['question_id'])).fetchone()
        cards.append(snapshot | dict(id=card['id'], question_id=card['question_id'], completed=card['completed_at'] is not None,
                                     rating=card['rating'], available=available, favorite=bool(favorite),
                                     mastery=mastery.personal_state(db,uid,card['question_id']) if available else None))
    return {key: session[key] for key in ('id', 'status', 'mode', 'source', 'collection_id', 'section_id')} | {
        'total': len(cards), 'completed': sum(c['completed'] for c in cards), 'cards': cards}


def start_session(db, user, collection_id, source, mode, question_count=None, section_id='interview'):
    if section_id not in dict(SECTIONS):
        raise HTTPException(422, '请选择有效的训练篇章')
    uid = user['id']
    if db.execute("SELECT 1 FROM training_sessions WHERE user_id=? AND status='active'", (uid,)).fetchone():
        raise HTTPException(409, '已有未完成训练，请继续或结束上一轮')
    if collection_id and not db.execute('SELECT 1 FROM training_collections WHERE id=? AND active=1 AND section_id=?', (collection_id,section_id)).fetchone():
        raise HTTPException(422, '请选择启用的训练集合')
    where = " WHERE q.deleted=0 AND q.active=1 AND c.active=1 AND (q.visibility='public' OR q.owner_user_id=?)"
    where += ' AND c.section_id=?'
    values = [uid, section_id]
    if collection_id:
        where += ' AND q.collection_id=?'; values.append(collection_id)
    if source == 'favorites':
        where += ' AND EXISTS(SELECT 1 FROM training_favorites f WHERE f.user_id=? AND f.question_id=q.id)'; values.append(uid)
    rows = list(db.execute(catalog.SELECT + where + ' ORDER BY c.position,q.position,q.id', values))
    if not rows:
        raise HTTPException(409, '当前筛选没有可练题目，请先加入重点回顾或选择其他集合')
    whole = question_count == 'all'
    size = len(rows) if whole else question_count if question_count is not None else settings(db)['round_size']
    if not whole and size > load_config()['training']['max_round_questions']:
        raise HTTPException(422, '本轮题数超出允许范围，请减少题数或选择整个题目集合')
    if mode == 'random':
        selected = mastery.weighted_sample(rows, size, mastery.weights(db,uid,rows))
    else:
        progress = db.execute('SELECT sort_key FROM training_sequential_progress WHERE user_id=? AND filter_key=?',
                              (uid, filter_key(dict(collection_id=collection_id, source=source, section_id=section_id)))).fetchone()
        remaining = [row for row in rows if not progress or sort_key(row) > json.loads(progress[0])]
        if whole:
            earlier = [row for row in rows if progress and sort_key(row) <= json.loads(progress[0])]
            selected = remaining + earlier
        else:
            selected = (remaining or rows)[:size]
    sid = db.execute('INSERT INTO training_sessions(user_id,collection_id,source,mode,created,section_id) VALUES (?,?,?,?,?,?)',
                     (uid, collection_id, source, mode, time.time(), section_id)).lastrowid
    for position, row in enumerate(selected):
        snapshot = catalog.serialize(db, row, uid)
        db.execute('INSERT INTO training_session_cards(session_id,question_id,position,snapshot,sort_key) VALUES (?,?,?,?,?)',
                   (sid, row['id'], position, json.dumps(snapshot, ensure_ascii=False), json.dumps(sort_key(row))))
    day_activity(db, uid, freeze=True)
    return get_session(db, sid, uid)


def complete(db, user, sid, card_id, rating):
    uid = user['id']
    session = get_session(db, sid, uid)
    card = db.execute('SELECT * FROM training_session_cards WHERE id=? AND session_id=?', (card_id, sid)).fetchone()
    if card is None:
        raise HTTPException(404, '训练卡片不存在')
    if card['completed_at'] is not None:
        return session
    if session['status'] != 'active':
        raise HTTPException(409, '本轮训练已结束，请开启新一轮')
    first = db.execute('SELECT id FROM training_session_cards WHERE session_id=? AND completed_at IS NULL ORDER BY position LIMIT 1', (sid,)).fetchone()[0]
    if first != card_id:
        raise HTTPException(409, '请先完成当前卡片')
    current = db.execute(catalog.SELECT + ' WHERE q.id=?', (card['question_id'],)).fetchone()
    available = catalog.accessible(current, uid)
    date, _, _ = day_activity(db, uid, freeze=True)
    if available:
        db.execute('INSERT OR IGNORE INTO training_daily_questions VALUES (?,?,?)', (uid, date, card['question_id']))
        mastery.record(db,uid,card['question_id'],rating,time.time())
    db.execute('UPDATE training_session_cards SET completed_at=?,rating=? WHERE id=?', (time.time(), rating if available else 'skipped', card_id))
    if session['mode'] == 'sequential':
        db.execute('''INSERT INTO training_sequential_progress VALUES (?,?,?)
            ON CONFLICT(user_id,filter_key) DO UPDATE SET sort_key=excluded.sort_key''',
            (uid, filter_key(session), card['sort_key']))
    if not db.execute('SELECT 1 FROM training_session_cards WHERE session_id=? AND completed_at IS NULL', (sid,)).fetchone():
        db.execute("UPDATE training_sessions SET status='completed' WHERE id=?", (sid,))
    return get_session(db, sid, uid)
