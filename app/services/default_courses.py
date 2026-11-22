"""Install bundled course notes once; later edits and deletions belong to administrators."""
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from pathlib import Path

from app.config import load_config


SEED_KEY = 'course_seed:algorithm-beginner'
PRACTICE_CONTENT_KEY = 'course_exercise_seed:algorithm-beginner:pdf'
PRACTICE_CONTENT_VERSION = 2
PRACTICE_STAGE = 'algorithm-book'
CONTENT_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'courses' / 'algorithm-beginner'
FIGURE = re.compile(r'(?<=\]\()figure:(p\d+-\d+\.webp)(?=\))')
PDF_PAGE_NOTE = re.compile(r'^\s*第 \d+(?:[–-]\d+)? 页 · PDF 原文摘录\s*$')
PRACTICE_SECTION = re.compile(
    r'(?mi)^## (?=[^\n]*(?:对应|配套|相关))(?=[^\n]*(?:原题|leetcode|力扣))[^\n]*\s*\n(?:\s*\n)*'
    r'(?:- \[[^\]]+\]\(https://leetcode\.cn/problems/[^)]+\)(?:（力扣会员题）)?\s*\n?)+')
READING_RANGE_SECTION = re.compile(r'(?ms)^## 阅读范围\s*\n.*?(?=^## |\Z)')


def remove_learner_prompts(markdown):
    """Remove source labels and duplicate original-problem links from lesson Markdown."""
    lines = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if (stripped.startswith('> 用户提供的《')
                or stripped.startswith('> 来源：')
                or stripped.startswith('> 本文为本站独立整理的入门学习笔记')
                or stripped in {'> PDF 未收录完整正文。以下只保留原书可读的部分。',
                                '> 原 PDF 未包含此处的动画。'}
                or PDF_PAGE_NOTE.fullmatch(line)):
            continue
        line = re.sub(r'原书第\s*\d+(?:[–-]\d+)?\s*页插图', '插图', line)
        lines.append(line)
    cleaned = PRACTICE_SECTION.sub('', '\n'.join(lines))
    cleaned = READING_RANGE_SECTION.sub('', cleaned)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip() + '\n'


@contextmanager
def seed_files():
    """Remove newly imported files if initialization or its database commit fails."""
    created = []
    try:
        yield created
    except BaseException as error:
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                error.add_note(f'默认课程导入失败，文件需手动清理：{path}（{cleanup_error}）')
        raise


def store_document(directory, content, created):
    """Write a private Markdown asset and register it for rollback cleanup."""
    return store_file(directory, content, created, '.md')


def store_file(directory, content, created, suffix):
    path = directory / (secrets.token_hex(24) + suffix)
    with path.open('xb') as output:
        created.append(path)
        path.chmod(0o600)
        output.write(content)
    return path.name


def render_exercise(exercise, full_statement=''):
    """Use the cached full platform statement, falling back to the book summary."""
    if full_statement.strip():
        return full_statement.strip()
    lines = [exercise['statement']]
    examples = exercise.get('examples', [])
    if examples:
        lines.extend(['', '### 书中示例'])
        for index, example in enumerate(examples, 1):
            lines.extend(['', f'**示例 {index}**', '',
                          '```text', f"输入：{example['input']}", f"输出：{example['output']}", '```'])
            if example.get('note'):
                lines.extend(['', example['note']])
    return '\n'.join(lines)


def practice_questions(db, catalog):
    """Register cached full statements without network access or overwriting edited questions."""
    exercises = json.loads((CONTENT_DIRECTORY / 'exercises.json').read_text(encoding='utf-8'))
    statements = json.loads((CONTENT_DIRECTORY / 'leetcode-statements.json').read_text(encoding='utf-8'))
    db.execute('''INSERT INTO coding_stages(id,title,description,position)
        SELECT ?,'算法入门课程','对应 PDF 讲义中的力扣中国区习题。',COALESCE(MAX(position),-1)+1
        FROM coding_stages WHERE true ON CONFLICT(id) DO NOTHING''', (PRACTICE_STAGE,))
    occurrences = {}
    for section in catalog['sections']:
        for lesson in section['lessons']:
            for number in lesson['question_ids']:
                occur = {'file': catalog['source_file'], 'page': lesson['pages'][0], 'section': lesson['title']}
                occurrences.setdefault(number, []).append(occur)
    practice_ids = {}
    for position, question in enumerate(catalog['leetcode_questions']):
        if question.get('paid_only'):
            continue
        number, slug, judge = question['id'], question['slug'], question['judge']
        key = f'algorithm-book:leetcode:{slug}'
        source_url = f'https://leetcode.cn/problems/{slug}/'
        title = f"{number}. {question['title']}"
        source_info = {'platform': 'leetcode', 'question_id': judge['question_id'],
                       'leetcode_metadata': judge['metadata'], 'occurrences': occurrences[number]}
        placeholder = f"### {title}\n\n[查看力扣中国区原题]({source_url})"
        exercise = exercises[str(number)]
        full_statement = statements[slug]['statement']
        if not isinstance(full_statement, str) or not full_statement.strip():
            raise ValueError(f'力扣题面缓存为空：{slug}')
        previous_statement = render_exercise(exercise)
        statement = render_exercise(exercise, full_statement)
        samples = json.dumps([{'input': example['input'], 'output': example['output']}
                              for example in exercise.get('examples', []) if example.get('runnable', True)],
                             ensure_ascii=False)
        # Refresh display and editable public examples without invalidating results from the same remote judge.
        db.execute('''INSERT INTO coding_questions(source_key,stage_id,title,topic,difficulty,stars,position,
            statement,samples,starter_codes,source_url,remote_problem_id,remote_platform,judge_mode,source_info,
            visibility,review_status,created,updated)
            VALUES (?,?,?,'课程练习',?,3,?,?,?,?,?,?,'leetcode','luogu',?,'public','approved',unixepoch(),unixepoch())
            ON CONFLICT(source_key) DO UPDATE SET statement=excluded.statement,samples=excluded.samples,
                version=coding_questions.version+1,updated=excluded.updated
            WHERE coding_questions.deleted=0 AND coding_questions.active=1
                AND coding_questions.content_version=1 AND coding_questions.statement IN (?,?)''',
            (key, PRACTICE_STAGE, title, judge['difficulty'], position, statement, samples,
             json.dumps(judge['starter_codes']), source_url, slug, json.dumps(source_info, ensure_ascii=False),
             placeholder, previous_statement))
        row = db.execute('''SELECT q.id FROM coding_questions q JOIN coding_stages s ON s.id=q.stage_id
            WHERE q.source_key=? AND q.deleted=0 AND q.active=1 AND s.active=1 AND q.visibility='public' ''',
            (key,)).fetchone()
        if row:
            practice_ids[number] = row['id']
    db.execute('''INSERT INTO app_settings(key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
        (PRACTICE_CONTENT_KEY, str(PRACTICE_CONTENT_VERSION)))
    return practice_ids


def render_lesson(catalog, section, lesson, practice_ids, body):
    """Combine learner-facing lesson notes, the document, and practice links.

    Source page and attribution metadata stays in the catalog and question
    records; it is deliberately excluded from the Markdown shown to learners.
    """
    lines = [
        f"# {lesson['title']}",
        '',
        '## 本节导读',
        '',
        lesson['description'],
        '',
    ]
    lines.extend(f'- {point}' for point in lesson['key_points'])
    lines.append('')
    questions = {item['id']: item for item in catalog['leetcode_questions']}
    links = [f"- [{number}. {questions[number]['title']} · 打开代码工作区](/#view=coding/question/{practice_ids[number]})"
             for number in lesson['question_ids'] if number in practice_ids]
    if links:
        lines.extend(['', '::: practice', *links, ':::'])
    lines.extend(['', '## 正文', '', body])
    return '\n'.join(lines)


def store_lesson(db, catalog, section, lesson, practice_ids, directory, created, course_id, lesson_id, uid):
    """Resolve PDF figures to private course image URLs before committing the lesson."""
    def add_figure(match):
        name = match[1]
        content = (CONTENT_DIRECTORY / 'figures' / name).read_bytes()
        image_id = secrets.token_hex(16)
        storage_name = store_file(directory, content, created, '.webp')
        db.execute('''INSERT INTO course_markdown_images(id,course_id,lesson_id,storage_name,mime_type,size,uploaded_by)
            VALUES (?,?,?,?,'image/webp',?,?)''', (image_id, course_id, lesson_id, storage_name, len(content), uid))
        return f'/api/courses/markdown-images/{image_id}'

    body = (CONTENT_DIRECTORY / lesson['document']).read_text(encoding='utf-8')
    if not body.strip():
        raise ValueError(f"默认课程文档不能为空：{lesson['document']}")
    content = render_lesson(catalog, section, lesson, practice_ids, FIGURE.sub(add_figure, body)).encode('utf-8')
    return store_document(directory, content, created), len(content)


def refresh_preview(db, course_id, catalog, practice_ids, directory, created):
    """Refresh generated lesson assets while preserving administrator edits."""
    course = db.execute('SELECT owner_id,host_id FROM live_courses WHERE id=?', (course_id,)).fetchone()
    if not course:
        return
    by_digest = {lesson['legacy_sha256']: (section, lesson)
                 for section in catalog['sections'] for lesson in section['lessons']}
    assets = db.execute('''SELECT a.id,a.lesson_id,a.storage_name FROM course_assets a
        JOIN course_lesson_items i ON i.asset_id=a.id
        WHERE a.course_id=? AND a.mime_type='text/markdown' ''', (course_id,)).fetchall()
    for asset in assets:
        path = directory / asset['storage_name']
        if not path.is_file():
            continue
        try:
            current = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        cleaned = remove_learner_prompts(current)
        if cleaned != current:
            content = cleaned.encode('utf-8')
            storage_name = store_document(directory, content, created)
            db.execute('UPDATE course_assets SET storage_name=?,size=? WHERE id=?',
                       (storage_name, len(content), asset['id']))
            continue
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest not in by_digest:
            continue
        section, lesson = by_digest[digest]
        name, size = store_lesson(db, catalog, section, lesson, practice_ids, directory, created,
                                  course_id, asset['lesson_id'], course['owner_id'] or course['host_id'])
        db.execute('UPDATE course_assets SET storage_name=?,size=? WHERE id=?', (name, size, asset['id']))


def save_marker(db, course_id, catalog):
    db.execute('''INSERT INTO app_settings(key,value) VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
        (SEED_KEY, json.dumps({'course_id': course_id, 'version': catalog['version']})))


def initialize_default_courses(db, created):
    """Seed the public course in the caller's transaction, once per database.

    ``created`` must come from ``seed_files()`` surrounding the database context
    so failed commits also remove the newly written assets. The marker intentionally
    survives course deletion and does not depend on the editable course title.
    """
    catalog = json.loads((CONTENT_DIRECTORY / 'catalog.json').read_text(encoding='utf-8'))
    marker = db.execute('SELECT value FROM app_settings WHERE key=?', (SEED_KEY,)).fetchone()
    previous = json.loads(marker['value']) if marker else None
    if previous and int(previous.get('version', 1)) >= catalog['version']:
        practice_marker = db.execute('SELECT value FROM app_settings WHERE key=?', (PRACTICE_CONTENT_KEY,)).fetchone()
        if ((not practice_marker or int(practice_marker['value']) < PRACTICE_CONTENT_VERSION)
                and db.execute('SELECT 1 FROM live_courses WHERE id=?', (previous.get('course_id'),)).fetchone()):
            practice_questions(db, catalog)
        return
    if previous and not db.execute('SELECT 1 FROM live_courses WHERE id=?', (previous.get('course_id'),)).fetchone():
        save_marker(db, None, catalog)
        return
    practice_ids = practice_questions(db, catalog)
    if previous and previous.get('version', 1) >= 3:
        directory = Path(load_config()['course_media']['directory']).resolve() / 'assets'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        refresh_preview(db, previous['course_id'], catalog, {}, directory, created)
        save_marker(db, previous['course_id'], catalog)
        return
    guide = json.loads((CONTENT_DIRECTORY / 'guide.json').read_text(encoding='utf-8'))
    for section in catalog['sections']:
        for lesson in section['lessons']:
            lesson['key_points'] = guide[str(lesson['pages'][0])]
    directory = Path(load_config()['course_media']['directory']).resolve() / 'assets'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if previous and previous.get('version') == 2:
        refresh_preview(db, previous['course_id'], catalog, practice_ids, directory, created)
        save_marker(db, previous['course_id'], catalog)
        return
    if previous:
        db.execute("UPDATE live_courses SET publication_status='archived' WHERE id=?",
                   (previous['course_id'],))
    owner = db.execute('''SELECT id FROM users WHERE is_admin=1
        ORDER BY is_superadmin DESC,id LIMIT 1''').fetchone()
    if not owner:
        raise RuntimeError('默认课程导入需要一个管理员账号')
    uid = owner['id']
    course_id = db.execute('''INSERT INTO live_courses(title,description,host_id,owner_id,
        publication_status,access_mode,cover_kind,cover_value)
        VALUES (?,?,?,?,'published','public','preset',?)''',
        (catalog['title'], catalog['description'], uid, uid, catalog['cover_value'])).lastrowid
    for section_position, section in enumerate(catalog['sections']):
        section_id = db.execute('INSERT INTO course_sections(course_id,title,position) VALUES (?,?,?)',
            (course_id, section['title'], section_position)).lastrowid
        for position, lesson in enumerate(section['lessons']):
            lesson_id = db.execute('''INSERT INTO course_lessons(course_id,section_id,title,description,position)
                VALUES (?,?,?,?,?)''',
                (course_id, section_id, lesson['title'], lesson['description'], position)).lastrowid
            storage_name, size = store_lesson(db, catalog, section, lesson, practice_ids, directory, created,
                                              course_id, lesson_id, uid)
            original_name = lesson['title'].replace('/', '-').replace('\\', '-') + '.md'
            asset_id = db.execute('''INSERT INTO course_assets(course_id,lesson_id,kind,original_name,
                storage_name,size,mime_type,uploaded_by) VALUES (?,?,'document',?,?,?,'text/markdown',?)''',
                (course_id, lesson_id, original_name, storage_name, size, uid)).lastrowid
            db.execute('''INSERT INTO course_lesson_items(lesson_id,kind,position,asset_id)
                VALUES (?,'document',0,?)''', (lesson_id, asset_id))
    save_marker(db, course_id, catalog)
