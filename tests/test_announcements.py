from test_system import client, login


def test_default_guidance_announcement_is_seeded_and_visible(client):
    alice=login(client,'alice')
    response=client.get('/api/announcements',headers=alice)
    assert response.status_code==200
    notice=next(item for item in response.json() if item['title']=='平台功能与奖励规则说明')
    assert notice['status']=='published'
    assert notice['remind_on_first_visit'] is False
    assert notice['reminder_pending'] is False
    assert notice['cover_url']=='/static/assets/announcement-cover.png'
    assert any(block['type']=='link' and 'wzyp.cn/shop/E1GQFV0P' in block['url'] for block in notice['blocks'])
    content=' '.join(block.get('text','') for block in notice['blocks'])
    assert '每 5 道' in content
    assert '第 7 天新增 1 次' in content and '第 14 天再新增 2 次' in content
    assert '卡密兑换' in content and '转赠' in content


def test_initialization_refreshes_only_untouched_default_announcement(client):
    from app.db import connect
    from app.services.announcements import initialize
    with connect() as db:
        db.execute("UPDATE announcements SET blocks='[]',summary='旧规则' WHERE title='平台功能与奖励规则说明'")
        initialize(db)
        seeded=db.execute("SELECT * FROM announcements WHERE title='平台功能与奖励规则说明'").fetchone()
        assert '第 14 天再新增 2 次' in ' '.join(block.get('text','') for block in __import__('json').loads(seeded['blocks']))
        db.execute("UPDATE announcements SET blocks='[]',summary='管理员版本',updated_by=1 WHERE id=?",(seeded['id'],))
        initialize(db)
        preserved=db.execute('SELECT summary,blocks FROM announcements WHERE id=?',(seeded['id'],)).fetchone()
        assert preserved['summary']=='管理员版本' and preserved['blocks']=='[]'


def test_announcement_drafts_are_hidden_until_published_and_links_are_validated(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    response=client.post('/api/admin/announcements',headers=admin,json={
        'title':'测试公告','summary':'摘要','cover_url':'','blocks':[{'type':'paragraph','text':'正文'}]})
    assert response.status_code==201,response.text
    item=response.json()
    assert item['status']=='draft'
    assert all(row['id']!=item['id'] for row in client.get('/api/announcements',headers=alice).json())
    bad=client.put(f"/api/admin/announcements/{item['id']}",headers=admin,json={
        'title':'测试公告','summary':'','cover_url':'','blocks':[{'type':'link','text':'坏链接','url':'javascript:alert(1)'}]})
    assert bad.status_code==422
    published=client.post(f"/api/admin/announcements/{item['id']}/status",headers=admin,json={'status':'published'})
    assert published.status_code==200
    assert client.get(f"/api/announcements/{item['id']}",headers=alice).status_code==200
    withdrawn=client.post(f"/api/admin/announcements/{item['id']}/status",headers=admin,json={'status':'withdrawn'})
    assert withdrawn.status_code==200
    assert client.get(f"/api/announcements/{item['id']}",headers=alice).status_code==404


def test_admin_can_delete_announcement_and_deleted_default_is_not_reseeded(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    default=next(item for item in client.get('/api/announcements',headers=alice).json()
                 if item['title']=='平台功能与奖励规则说明')
    deleted=client.delete(f"/api/admin/announcements/{default['id']}",headers=admin)
    assert deleted.status_code==204
    assert client.get(f"/api/announcements/{default['id']}",headers=alice).status_code==404
    from app.db import connect
    from app.services.announcements import initialize
    with connect() as db:
        initialize(db)
        assert db.execute("SELECT 1 FROM announcements WHERE title='平台功能与奖励规则说明'").fetchone() is None


def test_only_administrators_can_delete_announcements(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    created=client.post('/api/admin/announcements',headers=admin,json={
        'title':'待删除公告','summary':'','cover_url':'','body_markdown':'正文'})
    aid=created.json()['id']
    assert client.delete(f'/api/admin/announcements/{aid}',headers=alice).status_code==403
    assert client.delete('/api/admin/announcements/99999',headers=admin).status_code==404


def test_first_visit_announcement_reminder_is_per_user_and_dismissible(client):
    admin,alice,bob=login(client,'manager'),login(client,'alice'),login(client,'bob')
    response=client.post('/api/admin/announcements',headers=admin,json={
        'title':'首次访问提示','summary':'请阅读','cover_url':'','body_markdown':'提醒内容',
        'remind_on_first_visit':True})
    assert response.status_code==201,response.text
    item=response.json()
    assert item['remind_on_first_visit'] is True
    assert client.post(f"/api/admin/announcements/{item['id']}/status",headers=admin,
                       json={'status':'published'}).status_code==200
    alice_items=client.get('/api/announcements',headers=alice).json()
    bob_items=client.get('/api/announcements',headers=bob).json()
    assert next(row for row in alice_items if row['id']==item['id'])['reminder_pending'] is True
    assert next(row for row in bob_items if row['id']==item['id'])['reminder_pending'] is True
    assert client.post(f"/api/announcements/{item['id']}/dismiss-reminder",headers=alice).json()=={'ok':True}
    assert next(row for row in client.get('/api/announcements',headers=alice).json()
                if row['id']==item['id'])['reminder_pending'] is False
    assert next(row for row in client.get('/api/announcements',headers=bob).json()
                if row['id']==item['id'])['reminder_pending'] is True
    assert client.post(f"/api/announcements/{item['id']}/dismiss-reminder",headers=alice).json()=={'ok':True}


def test_announcement_markdown_renders_format_and_keeps_raw_html_inert(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    created=client.post('/api/admin/announcements',headers=admin,json={
        'title':'Markdown 公告','summary':'摘要','cover_url':'',
        'body_markdown':'## 小标题\n\n**重点内容**\n\n<script>alert(1)</script>'})
    assert created.status_code==201,created.text
    item=created.json()
    assert item['body_markdown'].startswith('## 小标题')
    assert '<h2>小标题</h2>' in item['body_html']
    assert '<strong>重点内容</strong>' in item['body_html']
    assert '<script>' not in item['body_html']
    assert '&lt;script&gt;' in item['body_html']
    assert client.post(f"/api/admin/announcements/{item['id']}/status",headers=admin,
                       json={'status':'published'}).status_code==200
    public=client.get(f"/api/announcements/{item['id']}",headers=alice).json()
    assert public['body_markdown']==item['body_markdown']
    assert public['body_html']==item['body_html']


def test_announcement_markdown_images_must_reference_uploaded_local_assets(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    bad=client.post('/api/admin/announcements',headers=admin,json={
        'title':'外链图片','summary':'','cover_url':'',
        'body_markdown':'![外部图片](https://example.com/image.png)'})
    assert bad.status_code==422
    png=b'\x89PNG\r\n\x1a\n'+b'\x00'*32
    uploaded=client.post('/api/admin/announcements/assets',headers=admin,
                         files={'file':('paste.png',png,'image/png')})
    assert uploaded.status_code==201
    asset_id=uploaded.json()['asset_id']
    saved=client.post('/api/admin/announcements',headers=admin,json={
        'title':'粘贴图片','summary':'','cover_url':'',
        'body_markdown':f'![已上传图片](/api/announcements/assets/{asset_id})'})
    assert saved.status_code==201,saved.text
    assert f'/api/announcements/assets/{asset_id}' in saved.json()['body_html']
    assert client.get(f'/api/announcements/assets/{asset_id}',headers=alice).status_code==404


def test_legacy_announcement_blocks_migrate_to_markdown(client):
    admin=login(client,'manager')
    created=client.post('/api/admin/announcements',headers=admin,json={
        'title':'旧格式迁移','summary':'','cover_url':'','body_markdown':'旧内容'})
    assert created.status_code==201
    from app.db import connect
    from app.services.announcements import initialize
    with connect() as db:
        aid=created.json()['id']
        db.execute("UPDATE announcements SET blocks=? WHERE id=?",
                   ('[{"type":"heading","text":"旧公告"},{"type":"paragraph","text":"正文"}]',aid))
        db.execute("UPDATE announcements SET body_markdown='' WHERE id=?",(aid,))
        initialize(db)
        markdown=db.execute('SELECT body_markdown FROM announcements WHERE id=?',(aid,)).fetchone()[0]
        assert markdown=='## 旧公告\n\n正文'


def test_only_administrators_manage_announcements(client):
    alice=login(client,'alice')
    assert client.get('/api/admin/announcements',headers=alice).status_code==403
    response=client.post('/api/admin/announcements',headers=alice,json={
        'title':'no','summary':'','cover_url':'','blocks':[]})
    assert response.status_code==403


def test_admin_announcement_list_is_server_paginated(client):
    admin=login(client,'manager')
    for index in range(11):
        response=client.post('/api/admin/announcements',headers=admin,json={
            'title':f'分页公告 {index:02d}','summary':'','cover_url':'','body_markdown':'正文'})
        assert response.status_code==201
    first=client.get('/api/admin/announcements?page=1&page_size=5',headers=admin).json()
    third=client.get('/api/admin/announcements?page=3&page_size=5',headers=admin).json()
    assert first['total']==third['total']==12
    assert first['page']==1 and third['page']==3
    assert first['page_size']==third['page_size']==5
    assert len(first['items'])==5 and len(third['items'])==2


def test_announcement_images_are_bounded_and_private_until_published(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    png=b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
    upload=client.post('/api/admin/announcements/assets',headers=admin,files={'file':('cover.png',png,'image/png')})
    assert upload.status_code==201,upload.text
    asset=upload.json()
    assert client.get(asset['url'],headers=alice).status_code==404
    too_large=client.post('/api/admin/announcements/assets',headers=admin,
                          files={'file':('large.png',b'\x89PNG\r\n\x1a\n'+b'x'*(5*1024*1024),'image/png')})
    assert too_large.status_code==413
    wrong_type=client.post('/api/admin/announcements/assets',headers=admin,
                           files={'file':('x.png',b'not a png','image/png')})
    assert wrong_type.status_code==415


def test_draft_announcement_cover_is_available_to_admin_but_not_public(client):
    admin,alice=login(client,'manager'),login(client,'alice')
    png=b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
    upload=client.post('/api/admin/announcements/assets',headers=admin,files={'file':('cover.png',png,'image/png')})
    assert upload.status_code==201,upload.text
    asset=upload.json()
    item=client.post('/api/admin/announcements',headers=admin,json={
        'title':'草稿封面','summary':'','cover_url':asset['url'],'blocks':[]})
    assert item.status_code==201,item.text
    admin_url=asset['url'].replace('/api/announcements/assets/','/api/admin/announcements/assets/')
    assert client.get(admin_url,headers=admin).status_code==200
    assert client.get(asset['url'],headers=alice).status_code==404
    published=client.post(f"/api/admin/announcements/{item.json()['id']}/status",headers=admin,
                          json={'status':'published'})
    assert published.status_code==200
    assert client.get(asset['url'],headers=alice).status_code==200


def test_home_resources_require_login_and_exclude_retired_interview_host(client):
    alice=login(client,'alice')
    assert client.get('/api/home/resources').status_code in (401,403)
    response=client.get('/api/home/resources',headers=alice)
    assert response.status_code==200
    resources=response.json()
    assert any(item['group']=='备考路线' and item['stars']==5 for item in resources)
    assert all('8.146.226.137' not in item.get('url','') for item in resources)
