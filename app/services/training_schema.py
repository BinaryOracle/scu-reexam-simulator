"""Independent learning catalog and per-account training persistence."""
import json
import hashlib
import time
from pathlib import Path
from app.config import load_config

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'training'
SECTIONS = [('interview', '面试篇'), ('written_c', '笔试-软件工程篇'), ('written_ai', '笔试-人工智能篇')]
AI_COLLECTIONS = [
    ('written_c', 'c_programming', '综合与历年题', 'professional', 'software_engineering'),
    ('written_ai', 'ai_ml', '机器学习', 'professional', 'machine_learning'),
    ('written_ai', 'ai_dl', '深度学习', 'professional', 'deep_learning'),
    ('written_ai', 'ai_llm', '大模型', 'professional', 'large_language_models'),
    ('written_ai', 'ai_agent_rag', 'Agent 与 RAG', 'professional', 'agent_rag'),
    ('written_ai', 'ai_literature_translation', '文献翻译', 'translation', 'literature_translation'),
]
SOFTWARE_COLLECTIONS = [
    ('written_c', 'se_fundamentals', '软件工程基础', 'professional', 'software_engineering'),
    ('written_c', 'se_requirements', '需求分析', 'professional', 'software_engineering'),
    ('written_c', 'se_design', '软件设计', 'professional', 'software_engineering'),
    ('written_c', 'se_testing', '软件测试', 'professional', 'software_engineering'),
    ('written_c', 'se_management', '项目与配置管理', 'professional', 'software_engineering'),
]
COLLECTIONS = [
    ('data_structures', '数据结构', 'professional', 'data_structures'),
    ('operating_systems', '操作系统', 'professional', 'operating_systems'),
    ('computer_networks', '计算机网络', 'professional', 'computer_networks'),
    ('translation', '英文翻译', 'translation', ''),
    ('oral', '英文问答', 'oral', ''),
]


def repair_answer_format(db, *, items=None, previous_hashes=None):
    """Replace only known original answers, including unchanged saved card copies."""
    if items is None:
        items = json.loads((ASSETS / 'catalog.json').read_text())
    if previous_hashes is None:
        previous_hashes = json.loads((ASSETS / 'answer-format-v1.json').read_text())
    for item in items:
        expected = previous_hashes.get(item['source_key'])
        if expected is None:
            continue
        row = db.execute('SELECT id,answer FROM training_questions WHERE source_key=? AND owner_user_id IS NULL',
                         (item['source_key'],)).fetchone()
        if row is None:
            continue
        if hashlib.sha256(row['answer'].encode()).hexdigest() == expected and row['answer'] != item['answer']:
            db.execute('UPDATE training_questions SET answer=?,version=version+1,updated=? WHERE id=?',
                       (item['answer'], time.time(), row['id']))
        for card in db.execute('SELECT id,snapshot FROM training_session_cards WHERE question_id=?',(row['id'],)):
            snapshot = json.loads(card['snapshot'])
            if hashlib.sha256(snapshot['answer'].encode()).hexdigest() == expected and snapshot['answer'] != item['answer']:
                snapshot['answer'] = item['answer']
                db.execute('UPDATE training_session_cards SET snapshot=? WHERE id=?',
                           (json.dumps(snapshot,ensure_ascii=False),card['id']))


def initialize_training(db, *, seed):
    """Create training tables in the caller's migration transaction and seed once."""
    statements = [
        '''CREATE TABLE IF NOT EXISTS training_collections(
            id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,
            subject TEXT NOT NULL,position INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1)''',
        '''CREATE TABLE IF NOT EXISTS training_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,collection_id TEXT NOT NULL REFERENCES training_collections(id),
            owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,source_key TEXT UNIQUE,
            position INTEGER NOT NULL,question TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',
            images TEXT NOT NULL DEFAULT '[]',source_info TEXT NOT NULL DEFAULT '{}',
            visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','public')),
            review_status TEXT NOT NULL DEFAULT 'draft' CHECK(review_status IN ('draft','pending','approved','rejected')),
            review_reason TEXT NOT NULL DEFAULT '',reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at REAL,version INTEGER NOT NULL DEFAULT 1,active INTEGER NOT NULL DEFAULT 1,
            deleted INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL,updated REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS training_by_visibility ON training_questions(collection_id,visibility,active,deleted)',
        'CREATE INDEX IF NOT EXISTS training_by_owner ON training_questions(owner_user_id,review_status)',
        '''CREATE TABLE IF NOT EXISTS training_favorites(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES training_questions(id) ON DELETE CASCADE,
            created REAL NOT NULL,PRIMARY KEY(user_id,question_id))''',
        '''CREATE TABLE IF NOT EXISTS training_sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            collection_id TEXT NOT NULL DEFAULT '',source TEXT NOT NULL CHECK(source IN ('all','favorites')),
            mode TEXT NOT NULL CHECK(mode IN ('random','sequential')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','ended')),
            created REAL NOT NULL)''',
        "CREATE UNIQUE INDEX IF NOT EXISTS training_one_active ON training_sessions(user_id) WHERE status='active'",
        '''CREATE TABLE IF NOT EXISTS training_session_cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER NOT NULL REFERENCES training_sessions(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES training_questions(id),position INTEGER NOT NULL,
            snapshot TEXT NOT NULL,sort_key TEXT NOT NULL,completed_at REAL,rating TEXT NOT NULL DEFAULT '',
            UNIQUE(session_id,question_id),UNIQUE(session_id,position))''',
        '''CREATE TABLE IF NOT EXISTS training_sequential_progress(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,filter_key TEXT NOT NULL,
            sort_key TEXT NOT NULL,PRIMARY KEY(user_id,filter_key))''',
        '''CREATE TABLE IF NOT EXISTS training_daily_activity(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,date TEXT NOT NULL,
            goal INTEGER NOT NULL CHECK(goal>0),PRIMARY KEY(user_id,date))''',
        '''CREATE TABLE IF NOT EXISTS training_daily_questions(
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,date TEXT NOT NULL,
            question_id INTEGER NOT NULL REFERENCES training_questions(id),PRIMARY KEY(user_id,date,question_id))''',
        '''CREATE TABLE IF NOT EXISTS training_checkins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,streak INTEGER NOT NULL,streak_start TEXT NOT NULL,UNIQUE(user_id,date))''',
        '''CREATE TABLE IF NOT EXISTS training_reward_grants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,checkin_id INTEGER UNIQUE REFERENCES training_checkins(id) ON DELETE SET NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,date TEXT NOT NULL,streak INTEGER NOT NULL,
            credits INTEGER NOT NULL,ledger_id INTEGER REFERENCES credit_ledger(id) ON DELETE SET NULL)''',
        '''CREATE TABLE IF NOT EXISTS training_review_events(
            id INTEGER PRIMARY KEY,question_id INTEGER NOT NULL REFERENCES training_questions(id),
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,event TEXT NOT NULL,
            version INTEGER NOT NULL,reason TEXT NOT NULL DEFAULT '',created REAL NOT NULL)''',
    ]
    for statement in statements:
        db.execute(statement)
    config = load_config()['training']
    for key in ('daily_goal', 'round_size'):
        db.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES (?,?)',
                   ('training_' + key, str(config[key])))
    for position, (key, name, category, subject) in enumerate(COLLECTIONS):
        db.execute('INSERT OR IGNORE INTO training_collections(id,name,category,subject,position) VALUES (?,?,?,?,?)',
                   (key, name, category, subject, position))
    if seed:
        items = json.loads((ASSETS / 'catalog.json').read_text())
        now = time.time()
        for item in items:
            db.execute('''INSERT OR IGNORE INTO training_questions(
                collection_id,source_key,position,question,answer,images,source_info,
                visibility,review_status,created,updated) VALUES (?,?,?,?,?,?,?,'public','approved',?,?)''',
                (item['collection_id'], item['source_key'], item['position'], item['question'], item['answer'],
                 json.dumps(item.get('images', []), ensure_ascii=False), json.dumps(item['source'], ensure_ascii=False), now, now))


def initialize_sections(db, *, seed, seed_literature=False, seed_software=False):
    """Assign legacy content to sections and seed versioned written-exam banks.

    Existing IDs, snapshots, interview cursors and administrator edits are retained.
    """
    for table in ('training_collections', 'training_sessions'):
        columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
        if 'section_id' not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN section_id TEXT NOT NULL DEFAULT 'interview'")
    for position, (section, cid, name, category, subject) in enumerate(AI_COLLECTIONS, len(COLLECTIONS)):
        db.execute('INSERT OR IGNORE INTO training_collections(id,name,category,subject,position,section_id) VALUES (?,?,?,?,?,?)',
                   (cid, name, category, subject, position, section))
    position = db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM training_collections').fetchone()[0]
    for offset, (section, cid, name, category, subject) in enumerate(SOFTWARE_COLLECTIONS):
        db.execute('INSERT OR IGNORE INTO training_collections(id,name,category,subject,position,section_id) VALUES (?,?,?,?,?,?)',
                   (cid, name, category, subject, position + offset, section))
    db.execute("UPDATE training_collections SET name='综合与历年题',subject='software_engineering' WHERE id='c_programming'")
    seed_files = (['written-ai.json'] if seed else []) + (['written-ai-literature.json'] if seed_literature else []) + (['written-software.json'] if seed_software else [])
    for filename in seed_files:
        now = time.time()
        for item in json.loads((ASSETS / filename).read_text()):
            db.execute("""INSERT OR IGNORE INTO training_questions(
                collection_id,source_key,position,question,answer,images,source_info,
                visibility,review_status,created,updated) VALUES (?,?,?,?,?,?,?,'public','approved',?,?)""",
                (item['collection_id'], item['source_key'], item['position'], item['question'], item['answer'],
                 json.dumps(item.get('images', []), ensure_ascii=False), json.dumps(item['source'], ensure_ascii=False), now, now))
