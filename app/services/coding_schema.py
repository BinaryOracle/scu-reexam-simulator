"""Independent coding catalog, submissions and atomic attendance/reward storage."""
import json
import time
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'coding'


def initialize_coding(db):
    """Create tables and insert missing stable catalog keys in the caller's transaction."""
    statements = [
        '''CREATE TABLE IF NOT EXISTS coding_stages(
            id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
            position INTEGER NOT NULL CHECK(position>=0),active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)))''',
        '''CREATE TABLE IF NOT EXISTS coding_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,source_key TEXT UNIQUE,
            stage_id TEXT NOT NULL REFERENCES coding_stages(id),owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            title TEXT NOT NULL,topic TEXT NOT NULL DEFAULT '',difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
            stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),position INTEGER NOT NULL CHECK(position>=0),
            statement TEXT NOT NULL DEFAULT '',samples TEXT NOT NULL DEFAULT '[]',reference_code TEXT NOT NULL DEFAULT '',
            reference_language TEXT NOT NULL DEFAULT 'cpp11',source_url TEXT NOT NULL DEFAULT '',
            remote_problem_id TEXT NOT NULL DEFAULT '',judge_mode TEXT NOT NULL CHECK(judge_mode IN ('luogu','samples')),
            source_info TEXT NOT NULL DEFAULT '{}',visibility TEXT NOT NULL CHECK(visibility IN ('public','private')),
            review_status TEXT NOT NULL CHECK(review_status IN ('draft','pending','approved','rejected')),
            review_reason TEXT NOT NULL DEFAULT '',reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at REAL,version INTEGER NOT NULL DEFAULT 1,content_version INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS coding_questions_stage ON coding_questions(stage_id,deleted,active,visibility,position)',
        'CREATE INDEX IF NOT EXISTS coding_questions_owner ON coding_questions(owner_user_id,review_status)',
        '''CREATE TABLE IF NOT EXISTS coding_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES coding_questions(id),question_version INTEGER NOT NULL,
            question_content_version INTEGER NOT NULL DEFAULT 0,
            question_title TEXT NOT NULL,judge_mode TEXT NOT NULL,remote_problem_id TEXT NOT NULL DEFAULT '',
            remote_submission_id TEXT NOT NULL DEFAULT '',language TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',passed_cases INTEGER,total_cases INTEGER,created REAL NOT NULL,
            completed REAL,completed_date TEXT)''',
        '''CREATE TABLE IF NOT EXISTS coding_favorites(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES coding_questions(id) ON DELETE CASCADE,
            created REAL NOT NULL,PRIMARY KEY(user_id,question_id))''',
        'CREATE INDEX IF NOT EXISTS coding_favorites_by_question ON coding_favorites(question_id,user_id)',
        '''CREATE TABLE IF NOT EXISTS coding_comments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES coding_questions(id) ON DELETE CASCADE,
            parent_id INTEGER REFERENCES coding_comments(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body TEXT NOT NULL,pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
            created REAL NOT NULL,updated REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS coding_comments_question ON coding_comments(question_id,pinned,created)',
        '''CREATE TABLE IF NOT EXISTS coding_comment_likes(
            comment_id INTEGER NOT NULL REFERENCES coding_comments(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created REAL NOT NULL,PRIMARY KEY(comment_id,user_id))''',
        'CREATE INDEX IF NOT EXISTS coding_comment_likes_by_user ON coding_comment_likes(user_id,comment_id)',
        "CREATE UNIQUE INDEX IF NOT EXISTS coding_remote_submission ON coding_submissions(remote_submission_id) WHERE remote_submission_id<>''",
        'CREATE INDEX IF NOT EXISTS coding_submissions_progress ON coding_submissions(user_id,question_id,status,completed_date)',
        '''CREATE TABLE IF NOT EXISTS coding_daily(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,date TEXT NOT NULL,
            question_id INTEGER NOT NULL REFERENCES coding_questions(id),created REAL NOT NULL,PRIMARY KEY(user_id,date))''',
        '''CREATE TABLE IF NOT EXISTS coding_checkins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,streak INTEGER NOT NULL,credits INTEGER NOT NULL DEFAULT 0,
            ledger_id INTEGER REFERENCES credit_ledger(id) ON DELETE SET NULL,UNIQUE(user_id,date))''',
        '''CREATE TABLE IF NOT EXISTS coding_reward_policies(
            id INTEGER PRIMARY KEY AUTOINCREMENT,questions_per_reward INTEGER NOT NULL CHECK(questions_per_reward>0),
            credits_per_reward INTEGER NOT NULL CHECK(credits_per_reward>0),active INTEGER NOT NULL CHECK(active IN (0,1)),
            created REAL NOT NULL,created_by INTEGER REFERENCES users(id) ON DELETE SET NULL)''',
        'CREATE UNIQUE INDEX IF NOT EXISTS coding_active_policy ON coding_reward_policies(active) WHERE active=1',
        '''CREATE TABLE IF NOT EXISTS coding_contribution_approvals(
            question_id INTEGER PRIMARY KEY REFERENCES coding_questions(id),
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            policy_id INTEGER NOT NULL REFERENCES coding_reward_policies(id),created REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS coding_contribution_grants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            policy_id INTEGER NOT NULL REFERENCES coding_reward_policies(id),milestone INTEGER NOT NULL,
            credits INTEGER NOT NULL,ledger_id INTEGER REFERENCES credit_ledger(id) ON DELETE SET NULL,
            created REAL NOT NULL,UNIQUE(user_id,policy_id,milestone))''',
        '''CREATE TABLE IF NOT EXISTS coding_review_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,question_id INTEGER NOT NULL REFERENCES coding_questions(id),
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,event TEXT NOT NULL,
            version INTEGER NOT NULL,reason TEXT NOT NULL DEFAULT '',created REAL NOT NULL)''',
    ]
    for statement in statements:
        db.execute(statement)
    for table, column, default in (('coding_questions', 'content_version', 1),
                                   ('coding_submissions', 'question_content_version', 0)):
        columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
        if column not in columns:
            # Earlier preview submissions do not identify which judge content was run.
            db.execute(f'ALTER TABLE {table} ADD COLUMN {column} INTEGER NOT NULL DEFAULT {default}')
    if not db.execute('SELECT 1 FROM coding_reward_policies LIMIT 1').fetchone():
        db.execute('INSERT INTO coding_reward_policies(questions_per_reward,credits_per_reward,active,created) VALUES (5,1,1,?)', (time.time(),))
    catalog_path = ASSETS / 'catalog.json'
    if not catalog_path.exists():
        return
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    for stage in catalog['stages']:
        db.execute('INSERT INTO coding_stages(id,title,description,position,active) VALUES (?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                   (stage['id'], stage['title'], stage.get('description', ''), stage['position'], stage.get('active', True)))
    fields = ('stage_id', 'title', 'topic', 'difficulty', 'stars', 'position', 'statement', 'samples',
              'reference_code', 'reference_language', 'source_url', 'remote_problem_id', 'judge_mode', 'source_info')
    now = time.time()
    for item in catalog['questions']:
        values = {'topic': '', 'difficulty': 1, 'stars': 3, 'position': 0, 'statement': '', 'samples': [],
                  'reference_code': '', 'reference_language': 'cpp11', 'source_url': '', 'remote_problem_id': '',
                  'judge_mode': 'samples', 'source_info': {}, **item, 'stage_id': item['stage_id']}
        values['source_info'] = item.get('source_info', item.get('source', {}))
        for key in ('samples', 'source_info'):
            values[key] = json.dumps(values[key], ensure_ascii=False)
        db.execute(f'''INSERT INTO coding_questions(source_key,{','.join(fields)},visibility,review_status,created,updated)
            VALUES (?,{','.join('?' for _ in fields)},'public','approved',?,?) ON CONFLICT(source_key) DO NOTHING''',
            (item['source_key'], *(values[key] for key in fields), now, now))
