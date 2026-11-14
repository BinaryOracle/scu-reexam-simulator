"""Shared transactional account deletion and best-effort private-file cleanup."""
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from fastapi import HTTPException


@dataclass(frozen=True)
class AccountFiles:
    """Private files scheduled for removal only after database deletion commits."""
    audio: set[str]
    presentations: set[str]


def delete_account(db, account):
    """Delete owned rows in the caller's transaction and retain spent voucher values."""
    uid = account['id']
    if account['is_superadmin']:
        raise HTTPException(409, '不能删除超级管理员账号')
    if account['is_admin'] and account['is_active']:
        count = db.execute('SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1').fetchone()[0]
        if count <= 1:
            raise HTTPException(409, '至少保留一个启用的管理员账号')
    owned = 'SELECT id FROM interviews WHERE user_id=?'
    audio = {row[0] for row in db.execute(f'SELECT audio_path FROM answers WHERE interview_id IN ({owned}) AND audio_path IS NOT NULL', (uid,))}
    audio.update(row[0] for row in db.execute(f'SELECT audio_path FROM interview_recordings WHERE interview_id IN ({owned}) AND audio_path IS NOT NULL', (uid,)))
    presentations = {row[0] for row in db.execute(f'SELECT directory FROM presentations WHERE interview_id IN ({owned})', (uid,))}
    db.execute('UPDATE vouchers SET redeemed_by=NULL,redeemed_username=? WHERE redeemed_by=?', (account['username'], uid))
    for table in ('answers', 'interview_recordings', 'presentations'):
        db.execute(f'DELETE FROM {table} WHERE interview_id IN ({owned})', (uid,))
    for table in ('interviews', 'submissions', 'sessions', 'credit_ledger'):
        db.execute(f'DELETE FROM {table} WHERE user_id=?', (uid,))
    db.execute('DELETE FROM email_challenges WHERE email=? COLLATE NOCASE', (account['email'],))
    db.execute('''INSERT INTO app_settings(key,value) VALUES ('user_id_highwater',?)
        ON CONFLICT(key) DO UPDATE SET value=CAST(MAX(CAST(app_settings.value AS INTEGER),CAST(excluded.value AS INTEGER)) AS TEXT)''', (str(uid),))
    # Public contributions survive without an owner; private drafts are removed from all draws.
    db.execute("UPDATE training_questions SET deleted=1,question='',answer='',images='[]',source_info='{}' WHERE owner_user_id=? AND visibility='private'", (uid,))
    db.execute('DELETE FROM users WHERE id=?', (uid,))
    return AccountFiles(audio, presentations)


def remove_account_files(files: AccountFiles):
    """Remove files after commit; log filesystem failures without restoring deleted rows."""
    for audio in files.audio:
        try:
            Path(audio).unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).exception('Deleted account file cleanup failed: %s', audio)
    for directory in files.presentations:
        shutil.rmtree(directory, ignore_errors=True)
