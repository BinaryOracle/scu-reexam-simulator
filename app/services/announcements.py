"""Published announcements, typed rich-content blocks, and image attachments."""
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from markdown_it import MarkdownIt
from app.config import load_config

DEFAULT_COVER = '/static/assets/announcement-cover.png'
DEFAULT_TITLE = '平台功能与奖励规则说明'
ASSET_PATH = re.compile(r'^/api/announcements/assets/([a-f0-9]{32})$')


def blocks_to_markdown(blocks):
    lines = []
    for block in blocks:
        kind, text = block['type'], block.get('text', '')
        if kind == 'heading':
            lines.append('## ' + text)
        elif kind == 'paragraph':
            lines.append(text)
        elif kind == 'link':
            lines.append(f'[{text}]({block["url"]})')
        elif kind == 'image':
            lines.append(f'![{block.get("alt", "")}](/api/announcements/assets/{block["asset_id"]})')
    return '\n\n'.join(lines)


def validate_markdown(db, content):
    if not isinstance(content, str) or len(content) > 100000:
        raise HTTPException(422, '公告 Markdown 不能为空或超过 100000 个字符')
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough'])
    tokens = renderer.parse(content)
    for token in tokens:
        for child in token.children or []:
            if child.type == 'link_open':
                url = child.attrGet('href') or ''
                parsed = urlsplit(url)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise HTTPException(422, '公告链接只支持有效的 HTTP 或 HTTPS 地址')
            elif child.type == 'image':
                match = ASSET_PATH.fullmatch(child.attrGet('src') or '')
                if not match or not db.execute('SELECT 1 FROM announcement_assets WHERE id=?', (match[1],)).fetchone():
                    raise HTTPException(422, '公告图片须先粘贴或上传到本站')
    return content.strip()


def render_markdown(content):
    renderer = MarkdownIt('commonmark', {'html': False, 'breaks': True})
    renderer.enable(['table', 'strikethrough'])
    tokens = renderer.parse(content or '')
    for token in tokens:
        for child in token.children or []:
            if child.type == 'link_open':
                child.attrSet('target', '_blank')
                child.attrSet('rel', 'noopener noreferrer')
    return renderer.renderer.render(tokens, renderer.options, {})


def default_blocks():
    return [
        {'type':'heading','text':'提交题目，积累面试次数'},
        {'type':'paragraph','text':'你提交到训练题库的题目，经管理员审核通过并公开后计入贡献奖励。当前规则为每 5 道通过审核的题目奖励 1 次模拟面试。进度和奖励记录可在个人主页查看；规则可能由管理员调整，以平台当前规则为准。'},
        {'type':'heading','text':'每日训练与连续签到'},
        {'type':'paragraph','text':'完成每日训练目标后可签到（当前默认每天完成 5 道不同题，具体目标以系统设置为准）。连续签到第 7 天新增 1 次模拟面试机会，第 14 天再新增 2 次，第 21 天再新增 3 次，依此递增；连续 14 天累计获得 3 次。中断后连续天数从第 1 天重新计算，已获得的次数保留。'},
        {'type':'heading','text':'购买和兑换模拟面试次数'},
        {'type':'paragraph','text':'前往联动小铺选择模拟面试次数商品。购买后取得卡密，登录本网站打开个人主页，在“卡密兑换”中粘贴并提交。每个卡密只能兑换一次，兑换后次数会加入当前账户。'},
        {'type':'link','text':'前往联动小铺','url':'https://wzyp.cn/shop/E1GQFV0P'},
        {'type':'heading','text':'转赠剩余次数'},
        {'type':'paragraph','text':'普通用户可在个人主页将剩余次数转赠给其他普通用户，并查看转赠记录。请核对接收方用户名或邮箱和转赠数量；确认后次数会立即转入对方账户。管理员账户不参与转赠。'},
        {'type':'paragraph','text':'模拟面试开始后会扣除 1 次。每日签到和题目贡献奖励按平台实际记录发放。'}]


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS announcements(
        id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',
        cover_url TEXT NOT NULL DEFAULT '',blocks TEXT NOT NULL DEFAULT '[]',body_markdown TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK(status IN ('draft','published','withdrawn')),
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created REAL NOT NULL,updated REAL NOT NULL,published_at REAL,
        remind_on_first_visit INTEGER NOT NULL DEFAULT 0 CHECK(remind_on_first_visit IN (0,1)))''')
    db.execute('CREATE INDEX IF NOT EXISTS announcements_by_status ON announcements(status,published_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS announcement_assets(
        id TEXT PRIMARY KEY,path TEXT NOT NULL,mime_type TEXT NOT NULL,created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created REAL NOT NULL)''')
    columns = {row['name'] for row in db.execute('PRAGMA table_info(announcements)')}
    if 'body_markdown' not in columns:
        db.execute("ALTER TABLE announcements ADD COLUMN body_markdown TEXT NOT NULL DEFAULT ''")
    if 'remind_on_first_visit' not in columns:
        db.execute('ALTER TABLE announcements ADD COLUMN remind_on_first_visit INTEGER NOT NULL DEFAULT 0')
    db.execute('''CREATE TABLE IF NOT EXISTS announcement_dismissals(
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
        dismissed_at REAL NOT NULL,PRIMARY KEY(user_id,announcement_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS announcement_seed_state(
        name TEXT PRIMARY KEY,initialized REAL NOT NULL)''')
    for row in db.execute("SELECT id,blocks FROM announcements WHERE body_markdown='' AND blocks!='[]'").fetchall():
        db.execute('UPDATE announcements SET body_markdown=? WHERE id=?',
                   (blocks_to_markdown(json.loads(row['blocks'])), row['id']))
    seed = db.execute("SELECT 1 FROM announcement_seed_state WHERE name='default_guidance'").fetchone()
    existing = db.execute('SELECT * FROM announcements WHERE title=? LIMIT 1', (DEFAULT_TITLE,)).fetchone()
    if not seed and not existing:
        now = time.time()
        blocks = default_blocks()
        db.execute('''INSERT INTO announcements(title,summary,cover_url,blocks,body_markdown,status,created,updated,published_at)
            VALUES (?,?,?,?,?, 'published',?,?,?)''', (DEFAULT_TITLE, '题目投稿、每日签到、次数购买兑换与转赠说明', DEFAULT_COVER,
            json.dumps(blocks, ensure_ascii=False), blocks_to_markdown(blocks), now, now, now))
    if not seed:
        db.execute("INSERT INTO announcement_seed_state(name,initialized) VALUES ('default_guidance',?)", (time.time(),))
    existing = db.execute('SELECT * FROM announcements WHERE title=? LIMIT 1', (DEFAULT_TITLE,)).fetchone()
    if existing and existing['created_by'] is None and existing['updated_by'] is None:
        # Refresh only the untouched system seed; preserve administrator edits and publication state.
        blocks = default_blocks()
        db.execute('UPDATE announcements SET summary=?,cover_url=?,blocks=?,body_markdown=?,updated=? WHERE id=?',
                   ('题目投稿、每日签到、次数购买兑换与转赠说明', DEFAULT_COVER,
                    json.dumps(blocks, ensure_ascii=False), blocks_to_markdown(blocks), time.time(), existing['id']))


def validate_blocks(blocks):
    if not isinstance(blocks, list) or len(blocks) > 100:
        raise HTTPException(422, '公告内容最多包含 100 个内容块')
    result = []
    for block in blocks:
        if not isinstance(block, dict) or block.get('type') not in ('paragraph','heading','image','link'):
            raise HTTPException(422, '公告内容块类型无效')
        kind = block['type']
        if kind in ('paragraph','heading','link'):
            text = block.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > (10000 if kind == 'paragraph' else 300):
                raise HTTPException(422, '公告文字内容为空或过长')
            item = {'type':kind,'text':text.strip()}
            if kind == 'link':
                url = block.get('url','').strip()
                parsed = urlsplit(url)
                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
                    raise HTTPException(422, '外部链接只支持有效的 HTTP 或 HTTPS 地址')
                item['url'] = url
            result.append(item)
        else:
            asset_id = block.get('asset_id','')
            if not isinstance(asset_id,str) or not re.fullmatch(r'[a-f0-9]{32}',asset_id):
                raise HTTPException(422, '请先上传公告图片')
            result.append({'type':'image','asset_id':asset_id,'alt':str(block.get('alt',''))[:200]})
    return result


def serialize(row, *, admin=False):
    return {'id':row['id'],'title':row['title'],'summary':row['summary'],'cover_url':row['cover_url'],
            'blocks':json.loads(row['blocks']),'body_markdown':row['body_markdown'],
            'body_html':render_markdown(row['body_markdown']),'status':row['status'],'created':row['created'],'updated':row['updated'],
            'published_at':row['published_at'],'remind_on_first_visit':bool(row['remind_on_first_visit'])} | ({'created_by':row['created_by'],'updated_by':row['updated_by']} if admin else {})


def list_items(db, *, admin=False, user_id=None, status='', q='', page=1, page_size=10):
    clauses, values = [], []
    if not admin: clauses.append("status='published'")
    elif status: clauses.append('status=?'); values.append(status)
    if q: clauses.append('instr(lower(title),lower(?))>0'); values.append(q)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    order = ' ORDER BY COALESCE(published_at,updated) DESC,id DESC'
    if not admin:
        items = [serialize(row,admin=False) for row in db.execute('SELECT * FROM announcements'+where+order,values)]
        dismissed = {row['announcement_id'] for row in db.execute(
            'SELECT announcement_id FROM announcement_dismissals WHERE user_id=?', (user_id,))} if user_id is not None else set()
        for item in items:
            item['reminder_pending'] = item['remind_on_first_visit'] and item['id'] not in dismissed
        return items
    total = db.execute('SELECT COUNT(*) FROM announcements'+where,values).fetchone()[0]
    rows = db.execute('SELECT * FROM announcements'+where+order+' LIMIT ? OFFSET ?',
                      (*values,page_size,(page-1)*page_size))
    return {'items':[serialize(row,admin=True) for row in rows], 'total':total,
            'page':page, 'page_size':page_size, 'pages':(total+page_size-1)//page_size}


def get_item(db, aid, *, public=False, user_id=None):
    clauses = 'id=? AND status=\'published\'' if public else 'id=?'
    row = db.execute('SELECT * FROM announcements WHERE '+clauses,(aid,)).fetchone()
    if row is None: raise HTTPException(404,'公告不存在或当前不可查看')
    item = serialize(row,admin=not public)
    if public:
        dismissed = db.execute('SELECT 1 FROM announcement_dismissals WHERE user_id=? AND announcement_id=?',
                               (user_id, aid)).fetchone() if user_id is not None else None
        item['reminder_pending'] = item['remind_on_first_visit'] and dismissed is None
    return item


def validate_cover(cover_url):
    is_static = cover_url.startswith('/static/') and '..' not in cover_url
    is_asset = ASSET_PATH.fullmatch(cover_url) is not None
    if cover_url and not (is_static or is_asset):
        raise HTTPException(422,'公告封面地址无效')


def preview(db, *, title, summary, cover_url, body_markdown, blocks=None, remind_on_first_visit=False):
    title, summary = title.strip(), summary.strip()
    if not title or len(title)>120 or len(summary)>500: raise HTTPException(422,'请填写有效的公告标题和摘要')
    validate_cover(cover_url)
    markdown = body_markdown if body_markdown else blocks_to_markdown(validate_blocks(blocks or []))
    markdown = validate_markdown(db, markdown)
    return {'title':title,'summary':summary,'cover_url':cover_url,'body_markdown':markdown,
            'body_html':render_markdown(markdown),'blocks':[],'status':'draft',
            'remind_on_first_visit':remind_on_first_visit}


def save(db, actor_id, *, aid, title, summary, cover_url, body_markdown='', blocks=None, remind_on_first_visit=False):
    title, summary = title.strip(), summary.strip()
    if not title or len(title)>120 or len(summary)>500: raise HTTPException(422,'请填写有效的公告标题和摘要')
    validate_cover(cover_url)
    markdown = body_markdown if body_markdown else blocks_to_markdown(validate_blocks(blocks or []))
    markdown = validate_markdown(db, markdown)
    now = time.time()
    data = (title,summary,cover_url,json.dumps([],ensure_ascii=False),markdown,actor_id,now,int(remind_on_first_visit))
    if aid is None:
        aid=db.execute('''INSERT INTO announcements(title,summary,cover_url,blocks,body_markdown,status,created_by,updated_by,created,updated,remind_on_first_visit)
            VALUES (?,?,?,?,?,\'draft\',?,?,?,?,?)''',(title,summary,cover_url,json.dumps([],ensure_ascii=False),markdown,actor_id,actor_id,now,now,int(remind_on_first_visit))).lastrowid
    else:
        if not db.execute('SELECT 1 FROM announcements WHERE id=?',(aid,)).fetchone(): raise HTTPException(404,'公告不存在')
        db.execute('UPDATE announcements SET title=?,summary=?,cover_url=?,blocks=?,body_markdown=?,updated_by=?,updated=?,remind_on_first_visit=? WHERE id=?',(*data,aid))
    return get_item(db,aid)


def dismiss_reminder(db, user_id, aid):
    row = db.execute("SELECT remind_on_first_visit FROM announcements WHERE id=? AND status='published'", (aid,)).fetchone()
    if row is None or not row['remind_on_first_visit']:
        raise HTTPException(404, '公告提醒不存在或已关闭')
    db.execute('INSERT OR IGNORE INTO announcement_dismissals(user_id,announcement_id,dismissed_at) VALUES (?,?,?)',
               (user_id, aid, time.time()))
    return {'ok': True}


def set_status(db, aid, actor_id, status):
    row=db.execute('SELECT status FROM announcements WHERE id=?',(aid,)).fetchone()
    if not row: raise HTTPException(404,'公告不存在')
    published=time.time() if status=='published' and row['status']!='published' else None
    db.execute('UPDATE announcements SET status=?,updated_by=?,updated=?,published_at=COALESCE(?,published_at) WHERE id=?',
               (status,actor_id,time.time(),published,aid))
    return get_item(db,aid)


def delete_item(db, aid):
    row = db.execute('SELECT * FROM announcements WHERE id=?', (aid,)).fetchone()
    if row is None:
        raise HTTPException(404, '公告不存在')
    asset_ids = set(re.findall(r'/api/announcements/assets/([a-f0-9]{32})', row['body_markdown'] or ''))
    match = ASSET_PATH.fullmatch(row['cover_url'] or '')
    if match:
        asset_ids.add(match[1])
    try:
        asset_ids.update(block['asset_id'] for block in json.loads(row['blocks'])
                         if block.get('type') == 'image' and re.fullmatch(r'[a-f0-9]{32}', block.get('asset_id', '')))
    except (TypeError, ValueError):
        pass
    db.execute('DELETE FROM announcements WHERE id=?', (aid,))
    for asset_id in asset_ids:
        cover = f'/api/announcements/assets/{asset_id}'
        needle = f'"asset_id": "{asset_id}"'
        referenced = db.execute('''SELECT 1 FROM announcements
            WHERE blocks LIKE ? OR body_markdown LIKE ? OR cover_url=? LIMIT 1''',
            ('%' + needle + '%', '%' + cover + '%', cover)).fetchone()
        if referenced:
            continue
        asset = db.execute('SELECT path FROM announcement_assets WHERE id=?', (asset_id,)).fetchone()
        if asset:
            Path(asset['path']).unlink(missing_ok=True)
            db.execute('DELETE FROM announcement_assets WHERE id=?', (asset_id,))


def upload_image(db, actor_id, data, content_type):
    if not data or len(data)>5*1024*1024: raise HTTPException(413,'公告图片为空或超过 5 MB')
    signatures={'image/png':b'\x89PNG\r\n\x1a\n','image/jpeg':b'\xff\xd8\xff','image/webp':b'RIFF'}
    if content_type not in signatures or not data.startswith(signatures[content_type]):
        raise HTTPException(415,'公告图片仅支持 PNG、JPEG 或 WebP')
    suffix={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[content_type]
    asset_id=secrets.token_hex(16)
    directory=Path(load_config()['app']['upload_dir'])/'announcements'; directory.mkdir(parents=True,exist_ok=True)
    path=directory/(asset_id+'.'+suffix)
    path.write_bytes(data)
    try:
        db.execute('INSERT INTO announcement_assets(id,path,mime_type,created_by,created) VALUES (?,?,?,?,?)',
                   (asset_id,str(path),content_type,actor_id,time.time()))
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {'asset_id':asset_id,'url':f'/api/announcements/assets/{asset_id}','mime_type':content_type}


def image_path(db, asset_id, *, admin=False):
    row=db.execute('SELECT * FROM announcement_assets WHERE id=?',(asset_id,)).fetchone()
    if not row: raise HTTPException(404,'公告图片不存在')
    if not admin:
        needle=f'"asset_id": "{asset_id}"'
        cover=f'/api/announcements/assets/{asset_id}'
        if not db.execute("SELECT 1 FROM announcements WHERE status='published' AND (blocks LIKE ? OR body_markdown LIKE ? OR cover_url=?) LIMIT 1",
                          ('%'+needle+'%','%'+cover+'%',cover)).fetchone():
            raise HTTPException(404,'公告图片不存在')
    path=Path(row['path'])
    if not path.is_file(): raise HTTPException(404,'公告图片文件不存在')
    return path,row['mime_type']
