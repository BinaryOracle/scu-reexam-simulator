"""Superadministrator backup download, dry-run upload, and confirmed restore."""
import hmac
import logging
import re
import tempfile
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.background import BackgroundTask

from app.db import connect
from app.services.auth import administrator
from app.services import backups, backup_restore
from app.services.backup_maintenance import exclusive_restore

logger = logging.getLogger(__name__)


def backup_owner(actor=Depends(administrator)):
    if not actor['is_superadmin']:
        raise HTTPException(403, '完整备份包含账号密码，仅超级管理员可备份和恢复')
    return actor


router = APIRouter(prefix='/api/admin/backups', tags=['数据备份'], dependencies=[Depends(backup_owner)])


class BackupExportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    modules: list[str] = Field(min_length=1, max_length=len(backups.MODULES))

    @field_validator('modules')
    @classmethod
    def validate_modules(cls, value):
        if len(set(value)) != len(value) or set(value) - backups.module_ids():
            raise ValueError('请选择有效且不重复的备份模块')
        return value


@router.get('/modules')
def backup_modules():
    with connect() as db:
        return backups.list_modules(db)


@router.post('/export')
def export_backup(payload: BackupExportRequest):
    output = tempfile.TemporaryFile()
    try:
        with connect() as db:
            db.execute('BEGIN')
            backups.write_backup(db, payload.modules, output)
    except (OSError, ValueError) as error:
        output.close()
        logger.exception('Backup export failed')
        raise HTTPException(422, '备份导出失败，请检查文件路径、磁盘空间和存储权限后重试') from error
    except Exception:
        output.close()
        raise

    def chunks():
        while chunk := output.read(1024 * 1024):
            yield chunk
    filename = f'scu-reexam-backup-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    return StreamingResponse(chunks(), media_type='application/zip', background=BackgroundTask(output.close), headers={
        'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })


@router.post('/preview')
def preview_backup(file: UploadFile = File(...)):
    archive = None
    try:
        archive = backup_restore.Archive(file.file)
        with connect() as db:
            db.execute('BEGIN')
            backup_restore.validate_against(db, archive)
        return archive.summary()
    except backup_restore.BackupError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        if archive:
            archive.close()
        file.file.close()


@router.post('/restore')
def restore_backup(file: UploadFile = File(...), sha256: str = Form(...), confirmation: str = Form(...)):
    if confirmation != 'RESTORE' or not re.fullmatch(r'[a-f0-9]{64}', sha256):
        raise HTTPException(422, '请先预览备份并确认恢复操作')
    archive = None
    try:
        with exclusive_restore():
            archive = backup_restore.Archive(file.file)
            if not hmac.compare_digest(archive.digest, sha256):
                raise HTTPException(409, '备份文件已变更，请重新选择并预览')
            with connect() as db:
                result = backup_restore.restore(db, archive)
            logger.info('Backup restored: modules=%s safety=%s', archive.modules, result['safety_backup'])
            return result
    except backup_restore.BackupError as error:
        raise HTTPException(422, str(error)) from error
    except OSError as error:
        logger.exception('Backup restore encountered a filesystem failure')
        raise HTTPException(503, '恢复未完成，已尝试回退。请检查磁盘空间和存储权限后重试；安全副本保存在 backups.directory') from error
    except RuntimeError as error:
        logger.exception('Backup restore rollback failed')
        raise HTTPException(503, str(error)) from error
    finally:
        if archive:
            archive.close()
        file.file.close()
