"""Course chapters, ordered lesson content, private assets, and learner progress."""


def initialize_course_learning(db):
    """Create course-learning records and map existing live lessons without replacing them."""
    columns = {row['name'] for row in db.execute('PRAGMA table_info(live_courses)')}
    for name, declaration in [
        ('publication_status', "TEXT NOT NULL DEFAULT 'published' CHECK(publication_status IN ('draft','published','archived'))"),
        ('access_mode', "TEXT NOT NULL DEFAULT 'roster' CHECK(access_mode IN ('public','roster','points'))"),
        ('points_price', 'INTEGER NOT NULL DEFAULT 0 CHECK(points_price >= 0)'),
        ('points_access_days', 'INTEGER NOT NULL DEFAULT 0 CHECK(points_access_days >= 0)'),
        ('cover_kind', "TEXT CHECK(cover_kind IN ('preset','upload'))"),
        ('cover_value', 'TEXT'),
        ('cover_asset_id', 'TEXT'),
    ]:
        if name not in columns:
            db.execute(f'ALTER TABLE live_courses ADD COLUMN {name} {declaration}')

    # Replace only the old column constraint, retaining course IDs and all references.
    schema = db.execute("SELECT sql FROM sqlite_master WHERE name='live_courses'").fetchone()[0]
    if "CHECK(access_mode IN ('public','roster'))" in schema:
        modes = list(db.execute('SELECT id,access_mode FROM live_courses'))
        db.execute('ALTER TABLE live_courses DROP COLUMN access_mode')
        db.execute("ALTER TABLE live_courses ADD COLUMN access_mode TEXT NOT NULL DEFAULT 'roster' CHECK(access_mode IN ('public','roster','points'))")
        db.executemany('UPDATE live_courses SET access_mode=? WHERE id=?', [(row[1], row[0]) for row in modes])

    db.execute('''CREATE TABLE IF NOT EXISTS course_sections(
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
        UNIQUE(course_id,position))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_lessons(
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        section_id INTEGER NOT NULL REFERENCES course_sections(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
        UNIQUE(section_id,position))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_assets(
        id INTEGER PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        lesson_id INTEGER NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('video','document')),
        original_name TEXT NOT NULL,
        storage_name TEXT NOT NULL UNIQUE,
        size INTEGER NOT NULL CHECK(size > 0),
        mime_type TEXT NOT NULL,
        uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created REAL NOT NULL DEFAULT (unixepoch())
    )''')
    for table in ('course_sections', 'course_lessons'):
        if 'preview_enabled' not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
            db.execute(f'ALTER TABLE {table} ADD COLUMN preview_enabled INTEGER NOT NULL DEFAULT 0 CHECK(preview_enabled IN (0,1))')
    db.execute('''CREATE TABLE IF NOT EXISTS course_purchases(
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        points_paid INTEGER NOT NULL CHECK(points_paid > 0),
        purchased_at REAL NOT NULL,
        access_expires_at REAL,
        PRIMARY KEY(course_id,user_id))''')
    if 'access_expires_at' not in {row['name'] for row in db.execute('PRAGMA table_info(course_purchases)')}:
        db.execute('ALTER TABLE course_purchases ADD COLUMN access_expires_at REAL')
    image_schema = '''CREATE TABLE IF NOT EXISTS course_markdown_images(
        id TEXT PRIMARY KEY,
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        lesson_id INTEGER REFERENCES course_lessons(id) ON DELETE CASCADE,
        storage_name TEXT NOT NULL UNIQUE,
        mime_type TEXT NOT NULL CHECK(mime_type IN ('image/png','image/jpeg','image/webp')),
        size INTEGER NOT NULL CHECK(size > 0),
        uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created REAL NOT NULL DEFAULT (unixepoch())
    )'''
    image_columns = {row['name']: row for row in db.execute('PRAGMA table_info(course_markdown_images)')}
    if not image_columns:
        db.execute(image_schema)
    elif image_columns['lesson_id']['notnull']:
        db.execute('ALTER TABLE course_markdown_images RENAME TO course_markdown_images_legacy')
        db.execute(image_schema)
        db.execute('''INSERT INTO course_markdown_images(id,course_id,lesson_id,storage_name,mime_type,size,uploaded_by,created)
            SELECT id,course_id,lesson_id,storage_name,mime_type,size,uploaded_by,created
            FROM course_markdown_images_legacy''')
        db.execute('DROP TABLE course_markdown_images_legacy')
    db.execute('''CREATE TABLE IF NOT EXISTS course_lesson_items(
        id INTEGER PRIMARY KEY,
        lesson_id INTEGER NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('live','video','document')),
        position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
        live_lesson_id INTEGER REFERENCES live_lessons(id) ON DELETE SET NULL,
        asset_id INTEGER REFERENCES course_assets(id) ON DELETE CASCADE,
        UNIQUE(lesson_id,position))''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS course_items_live_session ON course_lesson_items(live_lesson_id) WHERE live_lesson_id IS NOT NULL')
    db.execute('''CREATE TABLE IF NOT EXISTS course_self_enrollments(
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        enrolled_at REAL NOT NULL DEFAULT (unixepoch()),
        PRIMARY KEY(course_id,user_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_library_hidden(
        course_id INTEGER NOT NULL REFERENCES live_courses(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY(course_id,user_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_progress(
        lesson_id INTEGER NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        position_seconds REAL NOT NULL DEFAULT 0 CHECK(position_seconds >= 0),
        completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
        updated REAL NOT NULL DEFAULT (unixepoch()),
        PRIMARY KEY(lesson_id,user_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS course_playback_tickets(
        token TEXT PRIMARY KEY,
        asset_id INTEGER NOT NULL REFERENCES course_assets(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires REAL NOT NULL)''')

    live_columns = {row['name'] for row in db.execute('PRAGMA table_info(live_lessons)')}
    if 'course_lesson_id' not in live_columns:
        db.execute('''ALTER TABLE live_lessons ADD COLUMN course_lesson_id INTEGER
            REFERENCES course_lessons(id) ON DELETE SET NULL''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS live_lessons_course_lesson ON live_lessons(course_lesson_id) WHERE course_lesson_id IS NOT NULL')

    for course in db.execute('SELECT id FROM live_courses ORDER BY id'):
        db.execute('''INSERT OR IGNORE INTO course_sections(course_id,title,position)
            VALUES (?, '直播课程内容', 0)''', (course['id'],))
    for live in db.execute('''SELECT * FROM live_lessons
        WHERE course_lesson_id IS NULL ORDER BY course_id,starts_at,id''').fetchall():
        section = db.execute('SELECT id FROM course_sections WHERE course_id=? AND position=0',
                              (live['course_id'],)).fetchone()
        position = db.execute('SELECT COUNT(*) FROM course_lessons WHERE section_id=?',
                              (section['id'],)).fetchone()[0]
        lesson_id = db.execute('''INSERT INTO course_lessons(course_id,section_id,title,description,position)
            VALUES (?,?,?,?,?)''', (live['course_id'], section['id'], live['title'], live['description'], position)).lastrowid
        db.execute('UPDATE live_lessons SET course_lesson_id=? WHERE id=?', (lesson_id, live['id']))
        db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,live_lesson_id)
            VALUES (?,'live',0,?)''', (lesson_id, live['id']))
