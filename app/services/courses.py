"""Course storage and the lifecycle of server-recorded live lessons."""
import logging
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from fastapi import HTTPException
from app.config import load_config
from app.db import connect
from app.services.auth import current_user

log = logging.getLogger(__name__)
LEASE_SECONDS = 30
SEGMENT = re.compile(r'segment-[0-9]{6}\.ts')
PRIVATE = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
# Administrators can view published courses in the learner interface without a student grant.
VISIBLE = """c.published=1 AND (? OR c.access_mode='all' OR EXISTS (
    SELECT 1 FROM course_learners a WHERE a.course_id=c.id AND a.user_id=?))"""


def initialize(db):
    for statement in (
        '''CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
            published INTEGER NOT NULL CHECK(published IN (0,1)),
            access_mode TEXT NOT NULL DEFAULT 'restricted' CHECK(access_mode IN ('all','restricted')))''',
        '''CREATE TABLE IF NOT EXISTS course_learners (
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY(course_id,user_id))''',
        'CREATE INDEX IF NOT EXISTS course_learners_user ON course_learners(user_id)',
        '''CREATE TABLE IF NOT EXISTS course_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title TEXT NOT NULL, description TEXT NOT NULL, position INTEGER NOT NULL,
            live_start REAL, live_end REAL,
            CHECK((live_start IS NULL AND live_end IS NULL) OR
                (live_start IS NOT NULL AND live_end IS NOT NULL AND live_end>live_start)))''',
        '''CREATE TABLE IF NOT EXISTS course_files (
            id TEXT PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('material','video')), name TEXT NOT NULL,
            mime TEXT NOT NULL, size INTEGER NOT NULL, created REAL NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS course_broadcasts (
            id TEXT PRIMARY KEY, lesson_id INTEGER NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
            started REAL NOT NULL, lease_until REAL NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('recording','ready','failed')))''',
        'CREATE INDEX IF NOT EXISTS course_lessons_order ON course_lessons(course_id,position,id)',
        'CREATE INDEX IF NOT EXISTS course_files_lesson ON course_files(lesson_id,created)',
        'CREATE INDEX IF NOT EXISTS course_broadcasts_lesson ON course_broadcasts(lesson_id,started)',
        """CREATE UNIQUE INDEX IF NOT EXISTS course_one_broadcast ON course_broadcasts(lesson_id)
            WHERE state='recording'""",
    ):
        db.execute(statement)
    if 'access_mode' not in {row['name'] for row in db.execute('PRAGMA table_info(courses)')}:
        db.execute("""ALTER TABLE courses ADD COLUMN access_mode TEXT NOT NULL DEFAULT 'restricted'
            CHECK(access_mode IN ('all','restricted'))""")
        # Preserve the audience of courses created before the access controls existed.
        db.execute("UPDATE courses SET access_mode='all'")


def file_root():
    return Path(load_config()['courses']['directory'])


def course(db, cid):
    item = db.execute('SELECT * FROM courses WHERE id=?', (cid,)).fetchone()
    if item is None:
        raise HTTPException(404, '课程不存在')
    return item


def visible_course(db, cid, user, *, preview=False):
    if preview and user['is_admin']:
        return course(db, cid)
    item = db.execute(f'SELECT c.* FROM courses c WHERE c.id=? AND {VISIBLE}',
                      (cid, user['is_admin'], user['id'])).fetchone()
    if item is None:
        raise HTTPException(404, '课程不存在')
    return item


def lesson(db, cid, lid):
    row = db.execute('SELECT * FROM course_lessons WHERE course_id=? AND id=?', (cid, lid)).fetchone()
    if row is None:
        raise HTTPException(404, '课节不存在')
    return row


def manifest(path):
    try:
        text = (path / 'index.m3u8').read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    lines = text.splitlines()
    if not lines or lines[0] != '#EXTM3U' or not any(line.startswith('#EXTINF:') for line in lines):
        return None
    segments = [line for line in lines if line and not line.startswith('#')]
    if not segments or any(not SEGMENT.fullmatch(line) for line in segments):
        return None
    return text


def seal(db, bid, root):
    # Finalized HLS segments double as the replay. A killed worker may not have written ENDLIST.
    state = 'ready' if manifest(root / 'live' / bid) else 'failed'
    changed = db.execute("""UPDATE course_broadcasts SET state=? WHERE id=? AND state='recording'""",
                         (state, bid)).rowcount
    return state if changed else None


def recover(db, root, now):
    """Recover orphaned broadcasts after a stream worker exits unexpectedly."""
    if not db.execute("SELECT 1 FROM course_broadcasts WHERE state='recording' AND lease_until<=?",
                      (now,)).fetchone():
        return
    if not db.in_transaction:
        db.execute('BEGIN IMMEDIATE')
    stale = db.execute("SELECT id FROM course_broadcasts WHERE state='recording' AND lease_until<=?", (now,))
    for row in stale.fetchall():
        seal(db, row['id'], root)


def payload(db, item, root, now):
    cid = item['id']
    lessons = []
    for row in db.execute('SELECT * FROM course_lessons WHERE course_id=? ORDER BY position,id', (cid,)):
        lid = row['id']
        files = [dict(f) for f in db.execute('''SELECT id,kind,name,size,created FROM course_files
            WHERE lesson_id=? ORDER BY created,id''', (lid,))]
        broadcasts = db.execute('SELECT id,state,started FROM course_broadcasts WHERE lesson_id=? ORDER BY started DESC',
                                (lid,)).fetchall()
        active = next((b for b in broadcasts if b['state'] == 'recording'), None)
        start, end = row['live_start'], row['live_end']
        ready = active and manifest(root / 'live' / active['id'])
        if active:
            status = ('live' if ready else 'connecting') if now < end else 'processing'
        elif start is None:
            status = 'unscheduled'
        elif now < start:
            status = 'scheduled'
        elif now < end:
            status = 'ended' if any(b['state'] == 'ready' and b['started'] >= start for b in broadcasts) else 'waiting'
        else:
            status = 'ended'
        lessons.append({**dict(row), 'files': files, 'live_state': status, 'live_id': active['id'] if ready else None,
                        'replays': [dict(b) for b in broadcasts if b['state'] == 'ready'],
                        'last_live_failed': bool(broadcasts and broadcasts[0]['state'] == 'failed')})
    return {**dict(item), 'published': bool(item['published']), 'lessons': lessons, 'server_time': now}


def require_idle(db, cid, lid=None):
    query = """SELECT 1 FROM course_broadcasts b JOIN course_lessons l ON l.id=b.lesson_id
        WHERE b.state='recording' AND l.course_id=?"""
    args = (cid,)
    if lid is not None:
        query += ' AND l.id=?'
        args += (lid,)
    if db.execute(query, args).fetchone():
        raise HTTPException(409, '请先结束正在进行的直播')


def remove_media(root, ids, broadcasts):
    for fid in ids:
        try:
            (root / 'files' / fid).unlink(missing_ok=True)
        except OSError:
            log.warning('Could not remove course file %s', fid)
    for bid in broadcasts:
        path = root / 'live' / bid
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError:
                log.warning('Could not remove course broadcast %s', bid)


def reserve_broadcast(cid, lid, token):
    user = current_user(f'Bearer {token}' if token else None)
    if not user['is_admin']:
        raise HTTPException(403, '需要管理员权限')
    config = load_config()['courses']
    root = Path(config['directory'])
    now = time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        item = course(db, cid)
        row = lesson(db, cid, lid)
        if not item['published']:
            raise HTTPException(409, '请先发布课程')
        if row['live_start'] is None or not row['live_start'] <= now < row['live_end']:
            raise HTTPException(409, '当前不在设置的直播时段')
        recover(db, root, now)
        require_idle(db, cid, lid)
        count = db.execute("SELECT COUNT(*) FROM course_broadcasts WHERE state='recording'").fetchone()[0]
        if count >= config['max_concurrent_live']:
            raise HTTPException(409, '当前已达到同时直播场数上限')
        encoder = shutil.which(config['ffmpeg'])
        if not encoder and config['ffmpeg'] == 'ffmpeg':
            import imageio_ffmpeg
            try:
                encoder = imageio_ffmpeg.get_ffmpeg_exe()
            except RuntimeError:
                pass
        if not encoder:
            raise HTTPException(503, '服务器未配置 FFmpeg，暂时无法直播')
        bid = uuid.uuid4().hex
        db.execute("INSERT INTO course_broadcasts VALUES (?,?,?,?,'recording')",
                   (bid, lid, now, now + LEASE_SECONDS))
    return bid, root, str(Path(encoder).resolve()), min(row['live_end'], now + config['max_live_minutes'] * 60)


def renew_broadcast(bid, token):
    if not current_user(f'Bearer {token}')['is_admin']:
        raise HTTPException(403, '管理员权限已变更')
    with connect() as db:
        changed = db.execute("""UPDATE course_broadcasts SET lease_until=? WHERE id=? AND state='recording'""",
                             (time.time() + LEASE_SECONDS, bid)).rowcount
    if not changed:
        raise HTTPException(409, '直播已结束')


def start_encoder(encoder, directory):
    directory.mkdir(parents=True)
    return subprocess.Popen([
        encoder, '-hide_banner', '-loglevel', 'error', '-nostdin',
        '-f', 'webm', '-probesize', '32768', '-analyzeduration', '500000',
        '-protocol_whitelist', 'pipe', '-i', 'pipe:0',
        '-map', '0:v:0', '-map', '0:a:0?', '-vf',
        'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p',
        '-r', '24', '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-tune', 'zerolatency',
        '-g', '48', '-keyint_min', '48', '-sc_threshold', '0', '-b:v', '1500k',
        '-maxrate', '2000k', '-bufsize', '4000k', '-c:a', 'aac', '-b:a', '96k', '-ar', '48000',
        '-f', 'hls', '-hls_time', '2', '-hls_list_size', '0',
        '-hls_flags', 'independent_segments+temp_file', '-hls_segment_filename', 'segment-%06d.ts', 'index.m3u8',
    ], cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, bufsize=0)


def write_chunk(process, data):
    remaining = memoryview(data)
    while remaining:
        written = process.stdin.write(remaining)
        if not written:
            raise BrokenPipeError('Live encoder stopped')
        remaining = remaining[written:]


def stop_encoder(process, *, kill=False):
    try:
        if kill and process.poll() is None:
            process.kill()
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except OSError:
        if process.poll() is None:
            process.kill()
        process.wait()


def finish_broadcast(bid, root):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return seal(db, bid, root)
