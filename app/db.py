"""SQLite storage and transactional, idempotent account migration."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .config import load_config
from .services.security import hash_password
from .services.password_vault import encrypt_password, initialize_key

SCHEMA_VERSION = 25


@contextmanager
def connect():
    """Commit a successful unit of work, roll back failure, and close it."""
    path = Path(load_config()['app']['database'])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _user_id_highwater(db):
    current = db.execute('SELECT COALESCE(MAX(id),0) FROM users').fetchone()[0]
    stored = db.execute("SELECT value FROM app_settings WHERE key='user_id_highwater'").fetchone()
    return max(current, int(stored[0]) if stored else 0)


def allocate_user_id(db):
    """Reserve a never-reused account ID in the caller's BEGIN IMMEDIATE transaction."""
    uid = _user_id_highwater(db) + 1
    db.execute("""INSERT INTO app_settings(key,value) VALUES ('user_id_highwater',?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (str(uid),))
    return uid


def initialize():
    """Migrate stored data and seed root/root only when no accounts exist."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError('数据库版本高于当前程序，请使用匹配的程序版本')
        statements = [
            '''CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1)),
                can_interview INTEGER NOT NULL DEFAULT 0 CHECK(can_interview IN (0,1)),
                can_exam INTEGER NOT NULL DEFAULT 0 CHECK(can_exam IN (0,1)),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)))''',
            'CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL)',
            "CREATE TABLE IF NOT EXISTS interviews(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL, feedback TEXT)",
            "CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, interview_id INTEGER NOT NULL REFERENCES interviews(id), stage INTEGER NOT NULL, question TEXT NOT NULL, transcript TEXT NOT NULL DEFAULT '', audio_path TEXT, UNIQUE(interview_id, stage))",
            "CREATE TABLE IF NOT EXISTS question_bank(id INTEGER PRIMARY KEY, category TEXT NOT NULL CHECK(category IN ('professional','translation','oral')), subject TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created REAL NOT NULL, updated REAL NOT NULL)",
            'CREATE TABLE IF NOT EXISTS contests(id INTEGER PRIMARY KEY, title TEXT NOT NULL, starts REAL NOT NULL, ends REAL NOT NULL, judge_mode TEXT NOT NULL DEFAULT \'docker\' CHECK(judge_mode IN (\'docker\',\'luogu\')))',
            'CREATE TABLE IF NOT EXISTS problems(id INTEGER PRIMARY KEY, contest_id INTEGER NOT NULL REFERENCES contests(id), title TEXT NOT NULL, statement TEXT NOT NULL, sample_input TEXT NOT NULL, sample_output TEXT NOT NULL, tests TEXT NOT NULL, remote_problem_id TEXT NOT NULL DEFAULT \'\')',
            'CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), problem_id INTEGER NOT NULL REFERENCES problems(id), language TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, remote_submission_id TEXT NOT NULL DEFAULT \'\', detail TEXT NOT NULL DEFAULT \'\')',
            'CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id)',
        ]
        for statement in statements:
            db.execute(statement)
        for table, field, declaration in [
            ('contests', 'judge_mode', "TEXT NOT NULL DEFAULT 'docker' CHECK(judge_mode IN ('docker','luogu'))"),
            ('contests', 'show_ranking', 'INTEGER NOT NULL DEFAULT 1'),
            ('contests', 'ranking_rule', "TEXT NOT NULL DEFAULT 'score'"),
            ('problems', 'remote_problem_id', "TEXT NOT NULL DEFAULT ''"),
            ('problems', 'samples', "TEXT NOT NULL DEFAULT '[]'"),
            ('problems', 'points', 'INTEGER NOT NULL DEFAULT 100'),
            ('submissions', 'remote_submission_id', "TEXT NOT NULL DEFAULT ''"),
            ('submissions', 'detail', "TEXT NOT NULL DEFAULT ''"),
        ]:
            fields = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
            if field not in fields:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {field} {declaration}')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(users)')}
        if 'email' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN email TEXT')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email COLLATE NOCASE)')
        db.execute('''CREATE TABLE IF NOT EXISTS email_challenges(
            email TEXT PRIMARY KEY,challenge_id TEXT NOT NULL,code_hash TEXT NOT NULL,
            created REAL NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('pending','ready','used','failed')))''')
        db.execute('''CREATE TABLE IF NOT EXISTS email_auth_limits(
            scope TEXT NOT NULL,identity TEXT NOT NULL,window_start REAL NOT NULL,
            count INTEGER NOT NULL,PRIMARY KEY(scope,identity))''')
        db.execute('CREATE INDEX IF NOT EXISTS email_limits_by_window ON email_auth_limits(window_start)')
        db.execute('CREATE INDEX IF NOT EXISTS email_challenges_by_expiry ON email_challenges(expires)')
        db.execute('''CREATE TABLE IF NOT EXISTS account_email_challenges(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL CHECK(purpose IN ('rebind','password','delete')),
            email TEXT NOT NULL,source_email TEXT,challenge_id TEXT NOT NULL,code_hash TEXT NOT NULL,
            created REAL NOT NULL,expires REAL NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('pending','ready','used','failed')),
            PRIMARY KEY(user_id,purpose))''')
        db.execute('CREATE INDEX IF NOT EXISTS account_email_challenges_by_expiry ON account_email_challenges(expires)')
        if 'password_ciphertext' not in columns:
            db.execute("ALTER TABLE users ADD COLUMN password_ciphertext TEXT NOT NULL DEFAULT ''")
        initialize_key(has_passwords=bool(db.execute("SELECT 1 FROM users WHERE password_ciphertext != '' LIMIT 1").fetchone()))
        initial_credits = load_config()['credits']['default_credits']
        if 'interview_credits' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN interview_credits INTEGER NOT NULL DEFAULT 1 CHECK(interview_credits>=0)')
            db.execute('UPDATE users SET interview_credits=?', (initial_credits,))
        db.execute('CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("""INSERT INTO app_settings(key,value) VALUES ('user_id_highwater',?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (str(_user_id_highwater(db)),))
        db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('default_interview_credits',?)", (str(initial_credits),))
        db.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES ('luogu_app_origin',?)", ('http://127.0.0.1:8000',))
        db.execute('''CREATE TABLE IF NOT EXISTS vouchers(
            id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,package TEXT NOT NULL CHECK(package IN ('three','ten')),
            credits INTEGER NOT NULL CHECK(credits>0),price_fen INTEGER NOT NULL CHECK(price_fen>0),
            batch TEXT NOT NULL,created REAL NOT NULL,redeemed_by INTEGER REFERENCES users(id),redeemed_at REAL,
            CHECK((redeemed_by IS NULL AND redeemed_at IS NULL) OR (redeemed_by IS NOT NULL AND redeemed_at IS NOT NULL)))''')
        db.execute('CREATE INDEX IF NOT EXISTS vouchers_by_package ON vouchers(package,redeemed_by)')
        db.execute('CREATE INDEX IF NOT EXISTS vouchers_by_user ON vouchers(redeemed_by,redeemed_at)')
        db.execute('''CREATE TABLE IF NOT EXISTS credit_ledger(
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL CHECK(balance_after>=0),kind TEXT NOT NULL,
            amount_fen INTEGER NOT NULL DEFAULT 0,reference TEXT NOT NULL DEFAULT '',created REAL NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS ledger_by_user ON credit_ledger(user_id,created)')
        if 'role' in columns:
            # The old teacher account managed exams; it becomes the administrator.
            for field, default in [('is_admin', 0), ('can_interview', 0), ('can_exam', 0), ('is_active', 1)]:
                db.execute(f'ALTER TABLE users ADD COLUMN {field} INTEGER NOT NULL DEFAULT {default} CHECK({field} IN (0,1))')
            db.execute("UPDATE users SET is_admin=(role='teacher'),can_interview=(role='student'),can_exam=(role='student')")
            db.execute('ALTER TABLE users DROP COLUMN role')
        interview_columns = {row['name'] for row in db.execute('PRAGMA table_info(interviews)')}
        if 'credit_charged' not in interview_columns:
            db.execute('ALTER TABLE interviews ADD COLUMN credit_charged INTEGER NOT NULL DEFAULT 0 CHECK(credit_charged IN (0,1))')
            if 'started_at' in interview_columns:
                db.execute('UPDATE interviews SET credit_charged=1 WHERE started_at IS NOT NULL')
        if 'title' not in interview_columns:
            db.execute("ALTER TABLE interviews ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        for field, default in [('workflow_version', 1), ('intro_completed', 0)]:
            if field not in interview_columns:
                db.execute(f'ALTER TABLE interviews ADD COLUMN {field} INTEGER NOT NULL DEFAULT {default}')
        answer_columns = {row['name'] for row in db.execute('PRAGMA table_info(answers)')}
        for field, declaration in [('subject', "TEXT NOT NULL DEFAULT ''"), ('question_choices', 'INTEGER NOT NULL DEFAULT 0')]:
            if field not in answer_columns:
                db.execute(f'ALTER TABLE answers ADD COLUMN {field} {declaration}')
        if 'question_history' not in answer_columns:
            db.execute("ALTER TABLE answers ADD COLUMN question_history TEXT NOT NULL DEFAULT '[]'")
            # Earlier versions overwrote replaced questions; retain only surviving evidence.
            for answer in db.execute('SELECT id,question,subject FROM answers WHERE stage=2 AND question_choices>0').fetchall():
                history = [{'question': answer['question'], 'subject': answer['subject']}]
                db.execute('UPDATE answers SET question_history=? WHERE id=?',
                           (json.dumps(history, ensure_ascii=False), answer['id']))
        for field in ('started_at', 'deadline_at', 'ended_at'):
            if field not in interview_columns:
                db.execute(f'ALTER TABLE interviews ADD COLUMN {field} REAL')
        db.execute('''CREATE TABLE IF NOT EXISTS presentations(
            interview_id INTEGER PRIMARY KEY REFERENCES interviews(id),
            directory TEXT NOT NULL, name TEXT NOT NULL, pages INTEGER NOT NULL)''')
        db.execute("""CREATE TABLE IF NOT EXISTS interview_recordings(
            id TEXT PRIMARY KEY, interview_id INTEGER NOT NULL REFERENCES interviews(id),
            created REAL NOT NULL, audio_path TEXT, mime_type TEXT NOT NULL DEFAULT 'audio/webm',
            digest TEXT, finalized INTEGER NOT NULL DEFAULT 0, transcript TEXT NOT NULL DEFAULT '')""")
        db.execute('CREATE INDEX IF NOT EXISTS recordings_by_interview ON interview_recordings(interview_id)')
        db.execute('''CREATE TABLE IF NOT EXISTS speech_cache(
            cache_key TEXT PRIMARY KEY, interview_id INTEGER REFERENCES interviews(id) ON DELETE CASCADE,
            content BLOB NOT NULL, mime_type TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS speech_cache_by_interview ON speech_cache(interview_id)')
        db.execute('CREATE INDEX IF NOT EXISTS question_bank_by_category ON question_bank(category,subject,active)')
        if version < 7:
            seed = Path(__file__).resolve().parent / 'assets' / 'question-bank' / 'catalog.json'
            now = time.time()
            for item in json.loads(seed.read_text(encoding='utf-8')):
                db.execute('INSERT INTO question_bank(category,subject,content,created,updated) VALUES (?,?,?,?,?)',
                           (item['category'], item.get('subject', ''), item['content'], now, now))
        if version < 2:
            db.execute('UPDATE users SET can_interview=1,can_exam=1 WHERE is_admin=1')
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            db.execute('''INSERT INTO users(id,username,password,password_ciphertext,is_admin,can_interview,can_exam)
                VALUES (?,?,?,?,1,1,1)''', (allocate_user_id(db), 'root', hash_password('root'), encrypt_password('root')))
        if 'is_superadmin' not in columns:
            db.execute('ALTER TABLE users ADD COLUMN is_superadmin INTEGER NOT NULL DEFAULT 0 CHECK(is_superadmin IN (0,1))')
            # Bind the owner once; later username changes must never change authority.
            owner = db.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY (username='root') DESC,id LIMIT 1").fetchone()
            if owner:
                db.execute('UPDATE users SET is_superadmin=1 WHERE id=?', (owner['id'],))
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS single_superadmin ON users(is_superadmin) WHERE is_superadmin=1')
        db.execute('''CREATE TABLE IF NOT EXISTS voucher_packages(
            id TEXT PRIMARY KEY,price_fen INTEGER NOT NULL CHECK(price_fen>0),
            credits INTEGER NOT NULL CHECK(credits>0),created REAL NOT NULL,UNIQUE(price_fen,credits))''')
        voucher_columns = {row['name'] for row in db.execute('PRAGMA table_info(vouchers)')}
        if 'redeemed_username' not in voucher_columns:
            # Preserve issued-card values, including packages changed in config later.
            for row in db.execute('SELECT DISTINCT package,price_fen,credits FROM vouchers ORDER BY id'):
                db.execute('INSERT OR IGNORE INTO voucher_packages VALUES (?,?,?,?)',
                           (row['package'], row['price_fen'], row['credits'], time.time()))
            for key, item in load_config()['credits']['packages'].items():
                db.execute('INSERT OR IGNORE INTO voucher_packages VALUES (?,?,?,?)',
                           (key, item['price_fen'], item['credits'], time.time()))
            db.execute('''CREATE TABLE vouchers_v10(
                id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,package TEXT NOT NULL REFERENCES voucher_packages(id),
                credits INTEGER NOT NULL CHECK(credits>0),price_fen INTEGER NOT NULL CHECK(price_fen>0),
                batch TEXT NOT NULL,created REAL NOT NULL,redeemed_by INTEGER REFERENCES users(id),redeemed_at REAL,
                redeemed_username TEXT NOT NULL DEFAULT '',CHECK(redeemed_by IS NULL OR redeemed_at IS NOT NULL))''')
            db.execute('''INSERT INTO vouchers_v10 SELECT v.*,COALESCE(u.username,'') FROM vouchers v
                LEFT JOIN users u ON u.id=v.redeemed_by''')
            db.execute('DROP TABLE vouchers')
            db.execute('ALTER TABLE vouchers_v10 RENAME TO vouchers')
        db.execute('CREATE INDEX IF NOT EXISTS vouchers_by_package ON vouchers(package,redeemed_at)')
        db.execute('CREATE INDEX IF NOT EXISTS vouchers_by_user ON vouchers(redeemed_by,redeemed_at)')
        if version < 9:
            db.execute('UPDATE users SET interview_credits=999999 WHERE is_admin=1')
        from .services.training_schema import initialize_training
        initialize_training(db, seed=version < 16)
        from .services.training_mastery import initialize_mastery
        initialize_mastery(db, backfill=version < 19)
        from .services.credit_transfers import initialize_transfers
        initialize_transfers(db)
        if version < 18:
            from .services.training_schema import repair_answer_format
            repair_answer_format(db)
        from .services.training_schema import initialize_sections
        initialize_sections(db, seed=version < 20, seed_literature=version < 21, seed_software=version < 22)
        from .services.contribution_rewards import initialize as initialize_contribution_rewards
        initialize_contribution_rewards(db)
        from .services.announcements import initialize as initialize_announcements
        initialize_announcements(db)
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
