from test_system import client, login


def test_default_guidance_announcement_is_seeded_and_visible(client):
    alice=login(client,'alice')
    response=client.get('/api/announcements',headers=alice)
    assert response.status_code==200
    notice=next(item for item in response.json() if item['title']=='平台功能与奖励规则说明')
    assert notice['status']=='published'
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


def test_only_administrators_manage_announcements(client):
    alice=login(client,'alice')
    assert client.get('/api/admin/announcements',headers=alice).status_code==403
    response=client.post('/api/admin/announcements',headers=alice,json={
        'title':'no','summary':'','cover_url':'','blocks':[]})
    assert response.status_code==403


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
