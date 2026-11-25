"""Validate untrusted ZIP data, stage modular replacements, and restore with rollback."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tempfile
import zipfile

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.config import load_config
from app.services import backups


class BackupError(ValueError):
    """An invalid or incompatible backup; no live data should be changed."""


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or '\x00' in value
            or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise BackupError('备份包含不安全的文件路径')
    return PurePosixPath(value)


def media_target(name):
    path = _relative(name)
    if len(path.parts) < 3 or path.parts[0] != 'media' or path.parts[1] not in backups.media_roots():
        raise BackupError('媒体文件目录无效')
    root = backups.media_roots()[path.parts[1]]
    target = root.joinpath(*path.parts[2:])
    _check_target(target, root)
    return target


def _check_target(target, root):
    if not target.resolve().is_relative_to(root) or any(p.is_symlink() for p in (target, *target.parents)):
        raise BackupError('恢复目标包含符号链接或越出媒体目录')
    config = load_config()
    protected = [Path(config['app']['database']).resolve(), Path(config['security']['password_key_file']).resolve()]
    credentials = config['live'].get('credentials_file')
    if credentials:
        protected.append(Path(credentials).resolve())
    safety = Path(config['backups']['directory']).resolve()
    if target.resolve() in protected or target.resolve().is_relative_to(safety):
        raise BackupError('媒体文件不能覆盖数据库、密钥或安全副本')
    if str(target.resolve()) in {str(protected[0]) + suffix for suffix in ('-wal', '-shm', '-journal')}:
        raise BackupError('媒体文件不能覆盖数据库日志')


def _decode(column, value):
    if not isinstance(value, dict):
        return value
    if set(value) == {'$bytes'}:
        try:
            return base64.b64decode(value['$bytes'], validate=True)
        except (ValueError, TypeError) as error:
            raise BackupError('备份二进制字段无效') from error
    if column in backups.PATH_COLUMNS and set(value) == {'$path'}:
        spec = value['$path']
        if not isinstance(spec, dict) or set(spec) != {'root', 'relative'} or spec['root'] not in backups.media_roots():
            raise BackupError('备份文件路径字段无效')
        root = backups.media_roots()[spec['root']]
        relative = spec['relative']
        target = root if relative == '.' else root.joinpath(*_relative(relative).parts)
        _check_target(target, root)
        return str(target)
    raise BackupError('备份字段格式无效')


def archive_digest(source):
    source.seek(0)
    digest = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
    source.seek(0)
    return digest.hexdigest()


class Archive:
    """Read a bounded archive without extracting paths or running imported SQL."""

    def __init__(self, source):
        self.bundle = None
        self.tables = {}
        self.media = []
        self.source_cipher = None
        try:
            self._read(source)
        except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeError, KeyError, TypeError,
                ValueError, OSError, RuntimeError, NotImplementedError, AttributeError, RecursionError) as error:
            self.close()
            if isinstance(error, BackupError):
                raise
            raise BackupError('备份损坏或格式不正确，请重新导出完整的备份 ZIP') from error

    def _read(self, source):
        config = load_config()['backups']
        source.seek(0, 2)
        if source.tell() > config['max_upload_mb'] * 1024 * 1024:
            raise BackupError('备份文件超过当前配置的上传大小限制')
        source.seek(0)
        self.digest = archive_digest(source)
        self.bundle = zipfile.ZipFile(source)
        entries = self.bundle.infolist()
        if len(entries) > config['max_entries'] or sum(i.file_size for i in entries) > config['max_expanded_mb'] * 1024 * 1024:
            raise BackupError('备份解压后的体积或文件数量超过配置限制')
        names = []
        for info in entries:
            _relative(info.filename)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise BackupError('备份包含不支持的目录、链接或加密 ZIP 项目')
            names.append(info.filename)
        if len(set(names)) != len(names):
            raise BackupError('备份包含重复文件')
        if 'manifest.json' not in names or self.bundle.getinfo('manifest.json').file_size > 8 * 1024 * 1024:
            raise BackupError('备份缺少有效清单')
        self.manifest = json.loads(self.bundle.read('manifest.json'))
        if self.manifest.get('format') != backups.FORMAT:
            raise BackupError('此备份为旧版脱敏导出或不兼容格式，缺少密码和恢复信息，请使用新版重新备份')
        mods = self.manifest.get('modules')
        if not isinstance(mods, list) or not mods or any(not isinstance(m, dict) for m in mods):
            raise BackupError('备份模块清单无效')
        self.modules = [m['id'] for m in mods]
        if (any(not isinstance(m, str) or m not in backups.module_ids() for m in self.modules)
                or len(set(self.modules)) != len(self.modules) or set(backups.selected_ids(self.modules)) != set(self.modules)):
            raise BackupError('备份模块不完整或包含未知模块')
        highwater = self.manifest.get('user_id_highwater')
        sequences = self.manifest.get('sequences')
        tables = {table for mid in self.modules for table in backups.MODULE_BY_ID[mid]['tables']}
        if (type(highwater) is not int or not 0 <= highwater < 2**63 - 1 or not isinstance(sequences, dict)
                or any(table not in tables or type(seq) is not int or not 0 <= seq < 2**63 - 1
                       for table, seq in sequences.items())):
            raise BackupError('备份的账号或记录编号信息无效')
        checksums = self.manifest.get('entries')
        if not isinstance(checksums, dict) or set(checksums) != set(names) - {'manifest.json'}:
            raise BackupError('备份文件与清单不一致')
        for name, expected in checksums.items():
            digest = hashlib.sha256()
            with self.bundle.open(name) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise BackupError('备份完整性校验失败，请使用未损坏的原始文件')
        allowed = {'media/index.json'}
        for mid in self.modules:
            for table in backups.MODULE_BY_ID[mid]['tables']:
                name = f'{mid}/{table}.json'
                if name not in names:
                    raise BackupError('备份缺少模块数据文件，请重新导出')
                allowed.add(name)
                doc = json.loads(self.bundle.read(name))
                columns, rows = doc['columns'], doc['rows']
                if (not isinstance(columns, list) or not columns or any(not isinstance(c, str) for c in columns)
                        or len(set(columns)) != len(columns) or not isinstance(rows, list)
                        or len(rows) > config['max_rows_per_table']):
                    raise BackupError('备份表结构或记录数量无效')
                for row in rows:
                    if not isinstance(row, dict) or set(row) != set(columns):
                        raise BackupError('备份数据缺少字段或包含额外字段')
                    for column, value in row.items():
                        if value is not None and type(value) not in (str, int, float, dict):
                            raise BackupError('备份数据字段类型无效')
                        if isinstance(value, dict):
                            _decode(column, value)
                        if column in backups.PATH_COLUMNS and isinstance(value, str) and Path(value).is_absolute():
                            raise BackupError('备份中的绝对文件路径未转换，请重新导出')
                self.tables[table] = doc
        if set(self.modules) & {'accounts', 'settings'}:
            allowed.add('credentials/password-view.key')
            self.source_cipher = Fernet(self.bundle.read('credentials/password-view.key'))
        targets = set()
        for name in names:
            if name.startswith('media/') and name != 'media/index.json':
                if 'media' not in self.modules:
                    raise BackupError('未选择媒体模块却包含媒体文件')
                target = media_target(name)
                if target in targets:
                    raise BackupError('备份中的多个媒体文件指向同一恢复位置')
                targets.add(target)
                self.media.append((name, target))
                allowed.add(name)
        if set(names) != allowed | {'manifest.json'}:
            raise BackupError('备份包含未声明或不支持的文件')

    def close(self):
        if self.bundle:
            self.bundle.close()

    def summary(self):
        return {'sha256': self.digest, 'exported_at': self.manifest.get('exported_at'),
                'database_version': self.manifest['database_version'],
                'modules': [{'id': mid, 'name': backups.MODULE_BY_ID[mid]['name'],
                             'rows': sum(len(self.tables[t]['rows']) for t in backups.MODULE_BY_ID[mid]['tables'])}
                            for mid in self.modules],
                'files': len(self.media), 'includes_passwords': 'accounts' in self.modules,
                'warnings': (['未包含媒体文件，恢复后相关录音、PPT、课程视频和图片仍需使用当前存储中的文件。']
                             if 'media' not in self.modules else []) + self.manifest.get('missing_media', [])}


def _reencrypt(archive, value, target_cipher):
    try:
        return target_cipher.encrypt(archive.source_cipher.decrypt(value.encode('ascii'))).decode('ascii')
    except (InvalidToken, ValueError, UnicodeError, AttributeError) as error:
        raise BackupError('密码或模型密钥无法解密，备份密钥与数据不匹配') from error


def apply_tables(db, archive):
    """Replace declared tables with foreign keys disabled, then validate the entire database."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if archive.manifest['database_version'] != version:
        raise BackupError(f'数据库版本不匹配：备份为 {archive.manifest["database_version"]}，当前为 {version}，请使用相同版本程序恢复')
    from app.db import _user_id_highwater
    highwater = _user_id_highwater(db)
    references = archive.manifest.get('user_references')
    if not isinstance(references, dict):
        raise BackupError('备份缺少关联账号校验信息')
    if 'accounts' not in archive.modules:
        for uid, expected in references.items():
            if not isinstance(uid, str) or not uid.isdigit() or not isinstance(expected, str):
                raise BackupError('备份关联账号信息无效')
            user = db.execute('SELECT id,username,email FROM users WHERE id=?', (uid,)).fetchone()
            if not user or backups.user_identity(user) != expected:
                raise BackupError('关联账号与备份不一致，请同时备份并恢复账号与积分模块，避免记录关联到其他用户')
    target_cipher = Fernet(Path(load_config()['security']['password_key_file']).read_bytes())
    for table, doc in archive.tables.items():
        current = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
        if doc['columns'] != current:
            raise BackupError(f'{table} 表结构与当前程序不兼容，请使用匹配的程序版本')
    for table in archive.tables:
        db.execute(f'DELETE FROM "{table}"')
    for table, doc in archive.tables.items():
        columns = doc['columns']
        sql = f'INSERT INTO "{table}" ({",".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({",".join("?" for _ in columns)})'
        for row in doc['rows']:
            values = {column: _decode(column, row[column]) for column in columns}
            if table == 'app_settings':
                from app.services.feishu_oauth import TRANSIENT_KEYS
                if values['key'] in TRANSIENT_KEYS:
                    continue
            if table == 'users' and values.get('password_ciphertext'):
                values['password_ciphertext'] = _reencrypt(archive, values['password_ciphertext'], target_cipher)
            if table == 'app_settings' and values['key'] == 'ai_model_settings':
                settings = json.loads(values['value'])
                for service in settings.values():
                    if service.get('api_key_encrypted'):
                        service['api_key_encrypted'] = _reencrypt(archive, service['api_key_encrypted'], target_cipher)
                values['value'] = json.dumps(settings, ensure_ascii=False)
            if table == 'app_settings' and values['key'] == 'feishu_credentials':
                settings = json.loads(values['value'])
                if settings.get('app_secret_encrypted'):
                    settings['app_secret_encrypted'] = _reencrypt(archive, settings['app_secret_encrypted'], target_cipher)
                values['value'] = json.dumps(settings, ensure_ascii=False)
            db.execute(sql, [values[column] for column in columns])
    for table in backups.TRANSIENT_TABLES:
        db.execute(f'DELETE FROM "{table}"')
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise BackupError('所选模块与当前数据存在关联冲突，请将关联模块一起备份并恢复；当前数据未改变')
    if not db.execute('SELECT 1 FROM users WHERE is_superadmin=1 AND is_admin=1 AND is_active=1').fetchone():
        raise BackupError('恢复后必须保留至少一个启用的超级管理员，当前数据未改变')
    for table, sequence in archive.manifest['sequences'].items():
        current = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone()
        if current:
            db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?', (max(current[0], sequence), table))
        else:
            db.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (table, sequence))
    # Account IDs must not be reused, even when settings were restored independently.
    db.execute("INSERT INTO app_settings(key,value) VALUES ('user_id_highwater',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (str(max(highwater, _user_id_highwater(db), archive.manifest['user_id_highwater'])),))
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise BackupError('恢复后的数据库完整性校验失败')


def copy_database(db, target):
    """Use SQLite's online backup API, including committed WAL pages, under the caller's lock."""
    database_path = db.execute('PRAGMA database_list').fetchone()[2]
    # A separate reader avoids SQLite backup waiting on the caller's own write transaction.
    reader = sqlite3.connect(Path(database_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    try:
        reader.backup(target)
    finally:
        reader.close()


def validate_against(db, archive):
    """Dry-run the exact replacement against a private snapshot without changing live data."""
    stage = sqlite3.connect(':memory:')
    stage.row_factory = sqlite3.Row
    try:
        copy_database(db, stage)
        stage.execute('PRAGMA foreign_keys=OFF')
        apply_tables(stage, archive)
    except (sqlite3.Error, ValueError, KeyError, TypeError, AttributeError) as error:
        if isinstance(error, BackupError):
            raise
        raise BackupError('备份数据与当前数据库约束不兼容，当前数据未改变') from error
    finally:
        stage.close()


def require_idle(db):
    if db.execute("SELECT 1 FROM interviews WHERE started_at IS NOT NULL AND ended_at IS NULL AND deadline_at>unixepoch() LIMIT 1").fetchone():
        raise HTTPException(409, '有面试正在进行，请结束面试后再恢复备份')
    if db.execute("SELECT 1 FROM live_lessons WHERE status='live' LIMIT 1").fetchone() or db.execute(
            "SELECT 1 FROM live_recordings WHERE status IN ('starting','recording','stopping','unknown') LIMIT 1").fetchone():
        raise HTTPException(409, '有直播或录制正在进行，请结束后再恢复备份')


def restore(db, archive):
    """Commit data and installed media together; retain an operator-readable pre-restore snapshot."""
    config = load_config()
    safety_root = Path(config['backups']['directory'])
    safety_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    safety = Path(tempfile.mkdtemp(prefix='before-restore-', dir=safety_root))
    changed = []
    committed = False
    db.execute('PRAGMA foreign_keys=OFF')
    try:
        db.execute('BEGIN IMMEDIATE')
        require_idle(db)
        validate_against(db, archive)
        snapshot = safety / 'database.sqlite3'
        descriptor = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        safety_db = sqlite3.connect(snapshot)
        try:
            copy_database(db, safety_db)
            safety_db.execute('PRAGMA journal_mode=DELETE')
        finally:
            safety_db.close()
        shutil.copyfile(config['security']['password_key_file'], safety / 'password-view.key')
        (safety / 'password-view.key').chmod(0o600)
        apply_tables(db, archive)
        (safety / 'rollback.json').write_text(json.dumps({'media': [
            {'target': str(target), 'previous': f'media/{index}' if target.exists() else None}
            for index, (_, target) in enumerate(archive.media)]}, ensure_ascii=False, indent=2))
        (safety / 'rollback.json').chmod(0o600)
        with tempfile.TemporaryDirectory(prefix='restore-stage-', dir=safety_root) as staging:
            for index, (name, target) in enumerate(archive.media):
                staged = Path(staging) / str(index)
                with archive.bundle.open(name) as source, staged.open('wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                staged.chmod(0o600)
                root = backups.media_roots()[PurePosixPath(name).parts[1]]
                _check_target(target, root)
                old = safety / 'media' / str(index)
                if target.exists():
                    if not target.is_file():
                        raise BackupError('媒体恢复目标不是普通文件')
                    old.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copyfile(target, old)
                    old.chmod(0o600)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # A sibling temporary file keeps the final replacement atomic across devices.
                descriptor, temporary = tempfile.mkstemp(prefix='.restore-', dir=target.parent)
                try:
                    with os.fdopen(descriptor, 'wb') as output, staged.open('rb') as source:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    changed.append((target, old if old.exists() else None))
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
        db.commit()
        committed = True
    finally:
        if not committed:
            db.rollback()
            failures = []
            for target, old in reversed(changed):
                try:
                    if old:
                        shutil.copyfile(old, target)
                    else:
                        target.unlink(missing_ok=True)
                except OSError:
                    failures.append(str(target))
            if failures:
                raise RuntimeError(f'恢复失败且部分媒体无法自动回退，请停止操作并从安全副本 {safety.name} 修复')
        db.execute('PRAGMA foreign_keys=ON')
    return {'restored': True, 'safety_backup': safety.name, 'requires_login': True}
