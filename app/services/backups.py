"""Versioned module archives with complete account credentials and portable media paths."""
import base64
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import zipfile

from app.config import load_config

FORMAT = 'scu-reexam-backup-v2'
MODULES = (
    {'id': 'accounts', 'name': '账号与权限', 'description': '账号、权限、密码哈希与加密密码', 'tables': ('users',)},
    {'id': 'interviews', 'name': '模拟面试', 'description': '面试、回答、PPT 和录音记录',
     'tables': ('interviews', 'answers', 'presentations', 'interview_start_requests', 'interview_recordings')},
    {'id': 'question_bank', 'name': '面试题库与题目图片', 'description': '面试题库、训练与算法题共用的图片引用',
     'tables': ('question_bank', 'question_markdown_images', 'question_markdown_image_refs')},
    {'id': 'contests', 'name': '上机考试', 'description': '比赛、题目、提交和参赛关系',
     'tables': ('contests', 'problems', 'submissions', 'contest_participants')},
    {'id': 'training', 'name': '每日训练', 'description': '训练题库、练习进度、签到与投稿奖励',
     'tables': ('training_collections', 'training_questions', 'training_favorites', 'training_sessions',
                'training_session_cards', 'training_sequential_progress', 'training_daily_activity',
                'training_daily_questions', 'training_checkins', 'training_reward_grants',
                'training_review_events', 'training_mastery', 'contribution_reward_policies',
                'contribution_approvals', 'contribution_reward_grants')},
    {'id': 'coding', 'name': '算法带刷', 'description': '带刷题库、提交、收藏、评论和贡献记录',
     'tables': ('coding_stages', 'coding_questions', 'coding_submissions', 'coding_favorites',
                'coding_comments', 'coding_comment_likes', 'coding_daily', 'coding_checkins',
                'coding_reward_policies', 'coding_contribution_approvals', 'coding_contribution_grants',
                'coding_review_events')},
    {'id': 'courses', 'name': '课程', 'description': '章节、课时、资料和学习进度（与直播课一并备份）',
     'tables': ('course_sections', 'course_lessons', 'course_assets', 'course_markdown_images',
                'course_lesson_items', 'course_self_enrollments', 'course_library_hidden', 'course_progress')},
    {'id': 'live', 'name': '直播课', 'description': '课程主体、直播、互动、录播和资料（与课程一并备份）',
     'tables': ('live_courses', 'live_members', 'live_lessons', 'live_messages', 'live_materials',
                'live_recordings', 'live_webhooks', 'live_moderation', 'live_likes')},
    {'id': 'credits', 'name': '积分与兑换', 'description': '卡密、套餐、消费流水与榜单奖励（与账号一并备份）',
     'tables': ('vouchers', 'voucher_packages', 'credit_ledger', 'points_ledger', 'points_purchases',
                'credit_transfers', 'leaderboard_settlements', 'leaderboard_reward_grants')},
    {'id': 'announcements', 'name': '公告与趋势', 'description': '公告、阅读状态与 AI 趋势内容',
     'tables': ('announcements', 'announcement_assets', 'announcement_dismissals', 'announcement_seed_state', 'ai_trends')},
    {'id': 'settings', 'name': '系统设置', 'description': '后台设置、首页配置与加密的模型凭据', 'tables': ('app_settings',)},
    {'id': 'media', 'name': '媒体文件', 'description': '录音、PPT、课程视频、附件和图片，完整迁移时请勾选', 'tables': (), 'media': True},
)
MODULE_BY_ID = {item['id']: item for item in MODULES}
TRANSIENT_TABLES = ('sessions', 'email_challenges', 'email_auth_limits', 'account_email_challenges',
                    'course_playback_tickets', 'live_playback', 'live_presence', 'speech_cache')
PATH_COLUMNS = {'path', 'audio_path', 'directory', 'storage_path'}


def module_ids():
    return set(MODULE_BY_ID)


def selected_ids(selected):
    """Keep wallet balances and course/live relations together in every archive."""
    result = set(selected)
    for group in ({'accounts', 'credits'}, {'courses', 'live'}):
        if result & group:
            result |= group
    return [item['id'] for item in MODULES if item['id'] in result]


def media_roots():
    config = load_config()
    return {name: Path(config[section][field]).resolve() for name, section, field in (
        ('audio', 'app', 'upload_dir'), ('live', 'live', 'directory'),
        ('courses', 'course_media', 'directory'), ('presentations', 'presentation', 'directory'),
        ('questions', 'question_media', 'directory'))}


def _media_files():
    roots = media_roots()
    config = load_config()
    protected = {Path(config['app']['database']).resolve(), Path(config['security']['password_key_file']).resolve()}
    credentials = config['live'].get('credentials_file')
    if credentials:
        protected.add(Path(credentials).resolve())
    protected_dirs = [Path(config['backups']['directory']).resolve()]
    files, missing, seen = [], [], set()
    # Start at specific roots so nested course/question directories keep stable logical names.
    for name, root in sorted(roots.items(), key=lambda item: len(item[1].parts), reverse=True):
        if not root.is_dir():
            missing.append(f'{name}（目录不存在）')
            continue
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
                continue
            resolved = path.resolve()
            if resolved in seen or resolved in protected or any(resolved.is_relative_to(p) for p in protected_dirs):
                continue
            # SQLite sidecars are not media, even with unusually broad upload directories.
            if str(resolved) in {str(config['app']['database']) + suffix for suffix in ('-wal', '-shm', '-journal')}:
                continue
            seen.add(resolved)
            files.append((path, f'media/{name}/{path.relative_to(root).as_posix()}'))
    return files, missing


def _encode(column, value):
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode('ascii')}
    if column in PATH_COLUMNS and isinstance(value, str) and value:
        path = Path(value)
        if path.is_absolute():
            for name, root in sorted(media_roots().items(), key=lambda item: len(item[1].parts), reverse=True):
                if path.is_relative_to(root):
                    return {'$path': {'root': name, 'relative': path.relative_to(root).as_posix()}}
            raise ValueError('记录中的文件路径不在已配置的媒体目录中，请检查存储配置后重试')
    return value


def list_modules(db):
    existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = []
    for item in MODULES:
        files = _media_files()[0] if item.get('media') else []
        rows = len(files) if item.get('media') else sum(db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                                                        for table in item['tables'] if table in existing)
        result.append({'id': item['id'], 'name': item['name'], 'description': item['description'], 'rows': rows,
                       'estimated_bytes': sum(path.stat().st_size for path, _ in files), 'media': bool(item.get('media'))})
    return result


def user_identity(row):
    """Bind external user references to an identity, without coupling mutable balances or passwords."""
    return hashlib.sha256(json.dumps([row['id'], row['username'], row['email']], ensure_ascii=False).encode()).hexdigest()


def write_backup(db, selected, output):
    """Write a consistent caller-owned SQLite snapshot and media to a seekable ZIP output."""
    selected = selected_ids(selected)
    manifest = {'format': FORMAT, 'exported_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'database_version': db.execute('PRAGMA user_version').fetchone()[0], 'modules': [], 'entries': {},
                'security': '包含账号密码哈希、加密密码及配套密钥；不包含登录会话和临时验证码。请妥善保管。',
                'missing_media': [], 'user_references': {}}
    existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    from app.db import _user_id_highwater
    manifest['user_id_highwater'] = _user_id_highwater(db)
    included_tables = {table for mid in selected for table in MODULE_BY_ID[mid]['tables']}
    manifest['sequences'] = ({row[0]: row[1] for row in db.execute('SELECT name,seq FROM sqlite_sequence')
                              if row[0] in included_tables} if 'sqlite_sequence' in existing else {})
    referenced_users = set()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
        def put(name, content):
            bundle.writestr(name, content)
            manifest['entries'][name] = hashlib.sha256(content).hexdigest()

        for mid in selected:
            module = MODULE_BY_ID[mid]
            entry = {'id': mid, 'name': module['name'], 'rows': 0, 'files': 0}
            if mid == 'media':
                files, missing = _media_files()
                for path, name in files:
                    digest = hashlib.sha256()
                    with path.open('rb') as source, bundle.open(name, 'w', force_zip64=True) as target:
                        while chunk := source.read(1024 * 1024):
                            digest.update(chunk)
                            target.write(chunk)
                    manifest['entries'][name] = digest.hexdigest()
                entry['files'] = len(files)
                manifest['missing_media'] = missing
            else:
                for table in module['tables']:
                    if table not in existing:
                        continue
                    columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
                    rows = [{column: _encode(column, row[column]) for column in columns}
                            for row in db.execute(f'SELECT * FROM "{table}"')]
                    if 'accounts' not in selected:
                        for fk in db.execute(f'PRAGMA foreign_key_list("{table}")'):
                            if fk[2] == 'users':
                                referenced_users.update(row[fk[3]] for row in rows if row[fk[3]] is not None)
                    entry['rows'] += len(rows)
                    put(f'{mid}/{table}.json', json.dumps({'columns': columns, 'rows': rows}, ensure_ascii=False).encode())
            manifest['modules'].append(entry)
        for uid in referenced_users:
            user = db.execute('SELECT id,username,email FROM users WHERE id=?', (uid,)).fetchone()
            if user:
                manifest['user_references'][str(uid)] = user_identity(user)
        if set(selected) & {'accounts', 'settings'}:
            put('credentials/password-view.key', Path(load_config()['security']['password_key_file']).read_bytes())
        put('media/index.json', json.dumps({'files': [name for name in manifest['entries'] if name.startswith('media/')]},
                                          ensure_ascii=False).encode())
        bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    output.seek(0)
    return manifest


def build_backup(db, selected_modules):
    """Return archive bytes for small programmatic exports; HTTP exports use a temporary file."""
    output = io.BytesIO()
    manifest = write_backup(db, selected_modules, output)
    return output.getvalue(), manifest
