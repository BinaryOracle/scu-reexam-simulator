"""Shared authenticated Markdown preview and question illustration uploads."""
import secrets
import time
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from app.config import load_config
from app.db import connect
from app.services.auth import current_user
from app.services import question_markdown as media
from app.services.problem_content import render_statement

router = APIRouter(prefix='/api/question-markdown', tags=['题目 Markdown'])


class Preview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    markdown: str = Field(max_length=200000)


@router.post('/preview')
def preview(payload: Preview, user=Depends(current_user)):
    return {'html': render_statement(payload.markdown)}


@router.post('/images', status_code=201)
async def upload_image(file: UploadFile = File(...), user=Depends(current_user)):
    maximum = load_config()['question_media']['image_max_mb'] * 1024 * 1024
    try:
        content = await file.read(maximum + 1)
    finally:
        await file.close()
    if len(content) > maximum:
        raise HTTPException(413, f'图片不能超过 {maximum // (1024 * 1024)} MB')
    encoded, (mime, suffix) = media.encode_image(content)
    if len(encoded) > maximum:
        raise HTTPException(413, '图片转换后过大，请压缩后重新上传')
    image_id, storage = secrets.token_hex(16), secrets.token_hex(24) + suffix
    path = media.directory() / storage
    try:
        with path.open('xb') as output:
            path.chmod(0o600)
            output.write(encoded)
        with connect() as db:
            db.execute('INSERT INTO question_markdown_images VALUES (?,?,?,?,?,?)',
                       (image_id, user['id'], storage, mime, len(encoded), time.time()))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'url': f'/api/question-markdown/images/{image_id}'}


@router.get('/images/{image_id}')
def image(image_id: str, user=Depends(current_user)):
    if not media.IMAGE_PATH.fullmatch(f'/api/question-markdown/images/{image_id}'):
        raise HTTPException(404, '题目图片不存在')
    with connect() as db:
        row = db.execute('SELECT * FROM question_markdown_images WHERE id=?', (image_id,)).fetchone()
        if row is None or not media.may_read(db, row, user):
            raise HTTPException(404, '题目图片不存在或当前不可查看')
        path = media.directory() / row['storage_name']
        if not path.is_file():
            raise HTTPException(404, '题目图片文件不可用，请联系管理员')
        return FileResponse(path, media_type=row['mime_type'], headers={
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "default-src 'none'; base-uri 'none'", 'Content-Disposition': 'inline'})
