"""Fixed Beijing-day coding assignments, private submission histories and reward accounting."""
import json
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.services import credits
from app.services import coding_catalog as catalog

TERMINAL = {'Accepted', 'Wrong Answer', 'Output Limit Exceeded', 'Time Limit Exceeded',
            'Memory Limit Exceeded', 'Runtime Error', 'Compile Error', 'System Error',
            'Submission Failed', 'Judge Error'}


def today():
    """Return the fixed Beijing calendar date used for assignments and attendance."""
    return datetime.fromtimestamp(time.time(), ZoneInfo('Asia/Shanghai')).date()


def settings(db):
    row = db.execute('SELECT * FROM coding_reward_policies WHERE active=1').fetchone()
    if row is None:
        raise RuntimeError('算法投稿奖励规则未初始化')
    return dict(row)


def set_settings(db, user, questions_per_reward, credits_per_reward):
    current = settings(db)
    if (current['questions_per_reward'], current['credits_per_reward']) == (questions_per_reward, credits_per_reward):
        return current
    db.execute('UPDATE coding_reward_policies SET active=0 WHERE active=1')
    db.execute('''INSERT INTO coding_reward_policies(questions_per_reward,credits_per_reward,active,created,created_by)
        VALUES (?,?,1,?,?)''', (questions_per_reward, credits_per_reward, time.time(), user['id']))
    return settings(db)


def contribution(db, user):
    policy = settings(db)
    count = db.execute('SELECT COUNT(*) FROM coding_contribution_approvals WHERE user_id=? AND policy_id=?',
                       (user['id'], policy['id'])).fetchone()[0]
    earned = db.execute('SELECT COALESCE(SUM(credits),0) FROM coding_contribution_grants WHERE user_id=?',
                        (user['id'],)).fetchone()[0]
    return {key: policy[key] for key in ('questions_per_reward', 'credits_per_reward')} | {
        'policy_id': policy['id'], 'approved_count': count, 'credits_earned': earned, 'exempt': bool(user['is_admin'])}


def reward_contribution(db, question):
    """Count a question's first approval once and atomically award its policy milestone."""
    uid = question['owner_user_id']
    if uid is None or question['owner_admin']:
        return
    policy = settings(db)
    cursor = db.execute('''INSERT OR IGNORE INTO coding_contribution_approvals(question_id,user_id,policy_id,created)
        VALUES (?,?,?,?)''', (question['id'], uid, policy['id'], time.time()))
    if cursor.rowcount == 0:
        return
    count = db.execute('SELECT COUNT(*) FROM coding_contribution_approvals WHERE user_id=? AND policy_id=?',
                       (uid, policy['id'])).fetchone()[0]
    if count % policy['questions_per_reward']:
        return
    milestone = count // policy['questions_per_reward']
    cursor = db.execute('''INSERT OR IGNORE INTO coding_contribution_grants(user_id,policy_id,milestone,credits,created)
        VALUES (?,?,?,?,?)''', (uid, policy['id'], milestone, policy['credits_per_reward'], time.time()))
    if not cursor.rowcount:
        return
    balance = db.execute('SELECT interview_credits FROM users WHERE id=?', (uid,)).fetchone()[0]
    credits.adjust(db, uid, balance + policy['credits_per_reward'], kind='coding_contribution',
                   reference=f"{policy['id']}:{milestone}")
    ledger = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.execute('UPDATE coding_contribution_grants SET ledger_id=? WHERE id=?', (ledger, cursor.lastrowid))


def daily(db, user):
    uid, day = user['id'], today()
    day_string = day.isoformat()
    assignment = db.execute('SELECT * FROM coding_daily WHERE user_id=? AND date=?', (uid, day_string)).fetchone()
    last = db.execute('SELECT * FROM coding_checkins WHERE user_id=? ORDER BY date DESC LIMIT 1', (uid,)).fetchone()
    checked = bool(last and last['date'] == day_string)
    streak = last['streak'] if last and last['date'] in (day_string, (day - timedelta(days=1)).isoformat()) else 0
    question = db.execute(catalog.SELECT + ' WHERE q.id=?', (assignment['question_id'],)).fetchone() if assignment else None
    available = bool(question and catalog.accessible(question, uid) and question['active'] and question['stage_active'])
    solved = bool(assignment and db.execute("""SELECT 1 FROM coding_submissions WHERE user_id=?
        AND question_id=? AND question_content_version=? AND status='Accepted' AND completed_date=? LIMIT 1""",
        (uid, assignment['question_id'], question['content_version'], day_string)).fetchone())
    return {'date': day_string, 'question_id': assignment['question_id'] if assignment else None,
            'question_title': question['title'] if available else ('题目已停用或撤回' if assignment else ''),
            'available': available, 'solved': solved, 'checked_in': checked, 'streak': streak,
            'reward': last['credits'] if checked else 0,
            'next_milestone': (streak // 7 + 1) * 7, 'next_reward': streak // 7 + 1}


def home(db, user):
    from app.services import coding_judge
    stages = []
    for stage in catalog.stages(db):
        if not stage['active']:
            continue
        counts = db.execute("""SELECT COUNT(*) AS total,COALESCE(SUM(EXISTS(SELECT 1 FROM coding_submissions a
            WHERE a.question_id=q.id AND a.user_id=? AND a.question_content_version=q.content_version
            AND a.status='Accepted')),0) AS solved
            FROM coding_questions q WHERE q.stage_id=? AND q.active=1 AND q.deleted=0
            AND (q.visibility='public' OR q.owner_user_id=?)""", (user['id'], stage['id'], user['id'])).fetchone()
        stages.append(stage | dict(counts))
    daily_info = daily(db, user)
    if not user.get('can_practice', user['is_admin']):
        daily_info = {**daily_info, 'question_id': None, 'question_title': ''}
    return {'stages': stages, 'progress': {key: sum(stage[key] for stage in stages) for key in ('total', 'solved')},
            'daily': daily_info, 'can_practice': user.get('can_practice', user['is_admin']),
            'contribution': contribution(db, user), 'judge': coding_judge.availability()}


def assign_daily(db, user):
    """Caller holds BEGIN IMMEDIATE; each account has at most one assignment per date."""
    date = today().isoformat()
    if db.execute('SELECT 1 FROM coding_daily WHERE user_id=? AND date=?', (user['id'], date)).fetchone():
        return daily(db, user)
    rows = db.execute("""SELECT q.id FROM coding_questions q JOIN coding_stages s ON s.id=q.stage_id
        WHERE q.deleted=0 AND q.active=1 AND s.active=1 AND (q.visibility='public' OR q.owner_user_id=?)
        AND (q.judge_mode='luogu' OR json_array_length(q.samples)>0)""", (user['id'],)).fetchall()
    if not rows:
        raise HTTPException(409, '当前没有可练题目，请先添加私人题目或联系管理员')
    selected = secrets.choice(rows)
    db.execute('INSERT INTO coding_daily(user_id,date,question_id,created) VALUES (?,?,?,?)',
               (user['id'], date, selected['id'], time.time()))
    return daily(db, user)


def checkin(db, user):
    """Persist attendance, milestone reward and ledger under the caller's write lock."""
    status = daily(db, user)
    if status['checked_in']:
        return dict(already_checked=True, credits=status['reward'], streak=status['streak'], home=home(db, user))
    if not status['question_id'] or not status['solved']:
        raise HTTPException(409, '请先通过今天的每日一题评测，再打卡')
    streak = status['streak'] + 1
    account = db.execute('SELECT is_admin,interview_credits FROM users WHERE id=?', (user['id'],)).fetchone()
    amount = streak // 7 if streak % 7 == 0 and not account['is_admin'] else 0
    cid = db.execute('INSERT INTO coding_checkins(user_id,date,streak,credits) VALUES (?,?,?,?)',
                     (user['id'], status['date'], streak, amount)).lastrowid
    if amount:
        credits.adjust(db, user['id'], account['interview_credits'] + amount, kind='coding_checkin', reference=str(cid))
        ledger = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.execute('UPDATE coding_checkins SET ledger_id=? WHERE id=?', (ledger, cid))
    return dict(already_checked=False, credits=amount, streak=streak, home=home(db, user))


def submission(db, sid, user, *, owner_only=False):
    row = db.execute('SELECT s.*,u.is_admin AS owner_admin FROM coding_submissions s JOIN users u ON u.id=s.user_id WHERE s.id=?', (sid,)).fetchone()
    if row is None or (row['user_id'] != user['id'] and (owner_only or not user['is_admin'] or
                       (row['owner_admin'] and not user['is_superadmin']))):
        raise HTTPException(404, '提交记录不存在')
    return {key: row[key] for key in row.keys() if key != 'owner_admin'}


def new_submission(db, qid, user, language, source):
    question = catalog.require_access(db, qid, user['id'], practice=True)
    if not source.strip():
        raise HTTPException(422, '请先输入完整代码')
    if question['judge_mode'] == 'samples':
        from app.services import coding_judge
        capability = coding_judge.availability()
        if not capability['available']:
            raise HTTPException(503, capability['notice'])
        if not json.loads(question['samples']):
            raise HTTPException(409, '此题尚无公开样例，请先补充样例或打开原题链接')
    status = 'Waiting for browser extension' if question['judge_mode'] == 'luogu' else 'Judging'
    sid = db.execute('''INSERT INTO coding_submissions(user_id,question_id,question_version,question_content_version,question_title,judge_mode,
        remote_problem_id,language,source,status,created) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (user['id'], qid, question['version'], question['content_version'], question['title'], question['judge_mode'], question['remote_problem_id'],
         language, source, status, time.time())).lastrowid
    return submission(db, sid, user), json.loads(question['samples'])


def finish_local(db, sid, result):
    status = result['status']
    if status not in TERMINAL:
        raise RuntimeError('样例评测器返回了未定义的终态')
    db.execute('''UPDATE coding_submissions SET status=?,detail=?,passed_cases=?,total_cases=?,completed=?,completed_date=?
        WHERE id=? AND status='Judging' AND judge_mode='samples' ''',
        (status, result['detail'], result.get('passed_cases'), result.get('total_cases'), time.time(), today().isoformat(), sid))


def remote_result(db, sid, user, payload):
    row = submission(db, sid, user, owner_only=True)
    if row['judge_mode'] != 'luogu':
        raise HTTPException(409, '此记录不是洛谷评测')
    if payload.get('remote_problem_id') and payload['remote_problem_id'].upper() != row['remote_problem_id']:
        raise HTTPException(409, '远端题目编号与提交记录不一致')
    remote_id, status = payload['remote_submission_id'], payload['status']
    if row['remote_submission_id'] and remote_id != row['remote_submission_id']:
        raise HTTPException(409, '远端提交编号与本地记录不一致')
    if status != 'Submission Failed' and not remote_id:
        raise HTTPException(422, '远端评测状态必须包含洛谷提交编号')
    if row['status'] in TERMINAL:
        if status != row['status']:
            raise HTTPException(409, '已完成的评测结果不能被覆盖')
        return row
    if row['status'] == 'Judging' and status == 'Submitted':
        raise HTTPException(409, '评测状态不能退回待提交')
    if remote_id and db.execute('SELECT 1 FROM coding_submissions WHERE remote_submission_id=? AND id<>?', (remote_id, sid)).fetchone():
        raise HTTPException(409, '此洛谷提交已关联另一条记录')
    terminal = status in TERMINAL
    try:
        db.execute('''UPDATE coding_submissions SET remote_submission_id=?,status=?,detail=?,completed=?,completed_date=? WHERE id=?''',
                   (remote_id, status, payload['detail'], time.time() if terminal else None,
                    today().isoformat() if terminal else None, sid))
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, '此洛谷提交已关联另一条记录') from error
    return submission(db, sid, user)
