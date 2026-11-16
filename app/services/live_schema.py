"""Idempotent private classroom tables; no initialization occurs on import."""


def initialize_live(db):
    statements = [
        '''CREATE TABLE IF NOT EXISTS live_courses(id INTEGER PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',host_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE)''',
        '''CREATE TABLE IF NOT EXISTS live_members(course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,PRIMARY KEY(course_id,user_id))''',
        '''CREATE TABLE IF NOT EXISTS live_lessons(id INTEGER PRIMARY KEY,course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',starts_at REAL NOT NULL,status TEXT NOT NULL DEFAULT 'scheduled',likes INTEGER NOT NULL DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS live_presence(lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,seen REAL NOT NULL,hand INTEGER NOT NULL DEFAULT 0,request_share INTEGER NOT NULL DEFAULT 0,can_speak INTEGER NOT NULL DEFAULT 0,can_share INTEGER NOT NULL DEFAULT 0,muted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(lesson_id,user_id))''',
        '''CREATE TABLE IF NOT EXISTS live_messages(id INTEGER PRIMARY KEY,lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,content TEXT NOT NULL,created REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS live_materials(id INTEGER PRIMARY KEY,lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,name TEXT NOT NULL,path TEXT NOT NULL,size INTEGER NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS live_recordings(id INTEGER PRIMARY KEY,lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,egress_id TEXT UNIQUE,status TEXT NOT NULL,path TEXT NOT NULL,error TEXT NOT NULL DEFAULT '')''',
        '''CREATE TABLE IF NOT EXISTS live_playback(token TEXT PRIMARY KEY,recording_id INTEGER NOT NULL REFERENCES live_recordings(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS live_webhooks(id TEXT PRIMARY KEY,created REAL NOT NULL)''',
    ]
    statements += [
        '''CREATE TABLE IF NOT EXISTS live_moderation(lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,muted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(lesson_id,user_id))''',
        '''INSERT OR IGNORE INTO live_moderation SELECT lesson_id,user_id,muted FROM live_presence WHERE muted=1''',
        '''CREATE UNIQUE INDEX IF NOT EXISTS live_single_sharer ON live_presence(lesson_id) WHERE can_share=1''',
        '''CREATE TABLE IF NOT EXISTS live_likes(lesson_id INTEGER NOT NULL REFERENCES live_lessons(id) ON DELETE CASCADE,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,created REAL NOT NULL,PRIMARY KEY(lesson_id,user_id))''',
    ]
    for statement in statements:
        db.execute(statement)
