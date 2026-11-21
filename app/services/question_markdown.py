"""Private question illustration storage and references governed by question access."""
import io
import re
from pathlib import Path
from fastapi import HTTPException
from PIL import Image
from markdown_it import MarkdownIt
from app.config import load_config

IMAGE_PATH = re.compile(r'/api/question-markdown/images/([a-f0-9]{32})')
FORMATS = {'PNG': ('image/png', '.png'), 'JPEG': ('image/jpeg', '.jpg'), 'WEBP': ('image/webp', '.webp')}


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS question_markdown_images(
        id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        storage_name TEXT NOT NULL UNIQUE, mime_type TEXT NOT NULL, size INTEGER NOT NULL,
        created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS question_markdown_image_refs(
        image_id TEXT NOT NULL REFERENCES question_markdown_images(id) ON DELETE CASCADE,
        module TEXT NOT NULL CHECK(module IN ('training','coding')), question_id INTEGER NOT NULL,
        PRIMARY KEY(image_id,module,question_id))''')


def image_ids(*sources):
    """Read actual Markdown image destinations, ignoring code blocks and ordinary links."""
    for source in sources:
        for token in MarkdownIt('commonmark').parse(source or ''):
            for child in token.children or []:
                if child.type != 'image':
                    continue
                match = IMAGE_PATH.fullmatch(child.attrGet('src') or '')
                if match:
                    yield match[1]


def bind(db, actor, module, qid, *sources):
    """Attach owned uploads or retained illustrations after question edit permission checks."""
    for image_id in set(image_ids(*sources)):
        image = db.execute('SELECT owner_id FROM question_markdown_images WHERE id=?', (image_id,)).fetchone()
        retained = db.execute('''SELECT 1 FROM question_markdown_image_refs
            WHERE image_id=? AND module=? AND question_id=?''', (image_id, module, qid)).fetchone()
        if not image or (image['owner_id'] != actor['id'] and not retained):
            raise HTTPException(422, '正文图片不存在或不属于当前题目，请重新上传图片')
        # Keep earlier references for saved training-round snapshots. Reads still
        # require current access to the question, including withdrawal/deletion.
        db.execute('INSERT OR IGNORE INTO question_markdown_image_refs VALUES (?,?,?)', (image_id, module, qid))


def directory():
    path = Path(load_config()['question_media']['directory'])
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def encode_image(content):
    """Decode and re-encode supported raster images without preserving source metadata."""
    try:
        image = Image.open(io.BytesIO(content))
        image.verify()
        image = Image.open(io.BytesIO(content))
        if image.format not in FORMATS or image.width * image.height > 24_000_000:
            raise HTTPException(422, '图片仅支持 PNG、JPG、WebP，最大 2400 万像素')
        format_name = image.format
        image.load()
        image = image.convert('RGBA' if format_name == 'PNG' else 'RGB')
        output = io.BytesIO()
        image.save(output, format=format_name)
        return output.getvalue(), FORMATS[format_name]
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(422, '不是有效的 PNG、JPG 或 WebP 图片') from error


def may_read(db, image, user):
    """Apply owner, learner and moderator access without exposing other private drafts."""
    if image['owner_id'] == user['id']:
        return True
    from app.services import training_catalog, coding_catalog
    for ref in db.execute('SELECT module,question_id FROM question_markdown_image_refs WHERE image_id=?', (image['id'],)):
        if ref['module'] == 'training':
            row = db.execute(training_catalog.SELECT + ' WHERE q.id=? AND q.deleted=0', (ref['question_id'],)).fetchone()
            if row and user['can_training'] and training_catalog.accessible(row, user['id']):
                return True
            if row and user['is_admin']:
                try:
                    training_catalog.reviewable(db, ref['question_id'], user)
                    return True
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
        else:
            row = db.execute(coding_catalog.SELECT + ' WHERE q.id=? AND q.deleted=0', (ref['question_id'],)).fetchone()
            if row and ((user['can_coding'] and coding_catalog.accessible(row, user['id'])) or
                        (user['is_admin'] and coding_catalog.admin_access(row, user))):
                return True
    return False
