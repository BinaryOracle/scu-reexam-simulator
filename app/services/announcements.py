"""Published announcements, typed rich-content blocks, and image attachments."""
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from app.config import load_config

DEFAULT_COVER = '/static/assets/announcement-cover.png'
DEFAULT_TITLE = '平台功能与奖励规则说明'


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
        cover_url TEXT NOT NULL DEFAULT '',blocks TEXT NOT NULL DEFAULT '[]',status TEXT NOT NULL CHECK(status IN ('draft','published','withdrawn')),
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created REAL NOT NULL,updated REAL NOT NULL,published_at REAL)''')
    db.execute('CREATE INDEX IF NOT EXISTS announcements_by_status ON announcements(status,published_at)')
    db.execute('''CREATE TABLE IF NOT EXISTS announcement_assets(
        id TEXT PRIMARY KEY,path TEXT NOT NULL,mime_type TEXT NOT NULL,created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created REAL NOT NULL)''')
    existing = db.execute('SELECT * FROM announcements WHERE title=? LIMIT 1', (DEFAULT_TITLE,)).fetchone()
    if not existing:
        now = time.time()
        db.execute('''INSERT INTO announcements(title,summary,cover_url,blocks,status,created,updated,published_at)
            VALUES (?,?,?,?,?,?,?,?)''', (DEFAULT_TITLE, '题目投稿、每日签到、次数购买兑换与转赠说明', DEFAULT_COVER,
            json.dumps(default_blocks(), ensure_ascii=False), 'published', now, now, now))
    elif existing['created_by'] is None and existing['updated_by'] is None:
        # Refresh only the untouched system seed; preserve administrator edits and publication state.
        db.execute('UPDATE announcements SET summary=?,cover_url=?,blocks=?,updated=? WHERE id=?',
                   ('题目投稿、每日签到、次数购买兑换与转赠说明', DEFAULT_COVER,
                    json.dumps(default_blocks(), ensure_ascii=False), time.time(), existing['id']))


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
            'blocks':json.loads(row['blocks']),'status':row['status'],'created':row['created'],'updated':row['updated'],
            'published_at':row['published_at']} | ({'created_by':row['created_by'],'updated_by':row['updated_by']} if admin else {})


def list_items(db, *, admin=False, status='', q=''):
    clauses, values = [], []
    if not admin: clauses.append("status='published'")
    elif status: clauses.append('status=?'); values.append(status)
    if q: clauses.append('instr(lower(title),lower(?))>0'); values.append(q)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    return [serialize(row,admin=admin) for row in db.execute('SELECT * FROM announcements'+where+' ORDER BY COALESCE(published_at,updated) DESC,id DESC',values)]


def get_item(db, aid, *, public=False):
    clauses = 'id=? AND status=\'published\'' if public else 'id=?'
    row = db.execute('SELECT * FROM announcements WHERE '+clauses,(aid,)).fetchone()
    if row is None: raise HTTPException(404,'公告不存在或当前不可查看')
    return serialize(row,admin=not public)


def save(db, actor_id, *, aid, title, summary, cover_url, blocks):
    title, summary = title.strip(), summary.strip()
    if not title or len(title)>120 or len(summary)>500: raise HTTPException(422,'请填写有效的公告标题和摘要')
    parsed = validate_blocks(blocks)
    is_static = cover_url.startswith('/static/') and '..' not in cover_url
    is_asset = re.fullmatch(r'/api/announcements/assets/[a-f0-9]{32}', cover_url) is not None
    if cover_url and not (is_static or is_asset):
        raise HTTPException(422,'公告封面地址无效')
    now = time.time()
    data = (title,summary,cover_url,json.dumps(parsed,ensure_ascii=False),actor_id,now)
    if aid is None:
        aid=db.execute('''INSERT INTO announcements(title,summary,cover_url,blocks,status,created_by,updated_by,created,updated)
            VALUES (?,?,?,?,\'draft\',?,?,?,?)''',(title,summary,cover_url,json.dumps(parsed,ensure_ascii=False),actor_id,actor_id,now,now)).lastrowid
    else:
        if not db.execute('SELECT 1 FROM announcements WHERE id=?',(aid,)).fetchone(): raise HTTPException(404,'公告不存在')
        db.execute('UPDATE announcements SET title=?,summary=?,cover_url=?,blocks=?,updated_by=?,updated=? WHERE id=?',(*data,aid))
    return get_item(db,aid)


def set_status(db, aid, actor_id, status):
    row=db.execute('SELECT status FROM announcements WHERE id=?',(aid,)).fetchone()
    if not row: raise HTTPException(404,'公告不存在')
    published=time.time() if status=='published' and row['status']!='published' else None
    db.execute('UPDATE announcements SET status=?,updated_by=?,updated=?,published_at=COALESCE(?,published_at) WHERE id=?',
               (status,actor_id,time.time(),published,aid))
    return get_item(db,aid)


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
        if not db.execute("SELECT 1 FROM announcements WHERE status='published' AND (blocks LIKE ? OR cover_url=?) LIMIT 1",('%'+needle+'%',cover)).fetchone():
            raise HTTPException(404,'公告图片不存在')
    path=Path(row['path'])
    if not path.is_file(): raise HTTPException(404,'公告图片文件不存在')
    return path,row['mime_type']
