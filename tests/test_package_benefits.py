"""Package benefits use purchase snapshots and grant local access only once."""
from test_system import client, login
from test_service_packages import setup_accounts, create_package
from test_course_access import paid_course
from test_course_learning import create_ready_course


def test_purchase_opens_modules_awards_points_and_enrolls_courses_once(client):
    from app.db import connect
    manager, alice, bob, bid = setup_accounts(client)
    paid = paid_course(client, manager)
    private = create_ready_course(client, manager, '套餐私域课程', access_mode='roster', member_ids=[])
    with connect() as db:
        db.execute('UPDATE users SET can_training=0,can_coding=0,can_practice=0,can_interview=0,can_exam=0 WHERE id=?', (bid,))
    benefits = {'modules': ['training', 'coding', 'interview', 'exam'], 'gift_points': 21,
                'course_ids': [paid['id'], private['id']], 'feishu_resources': []}
    package = create_package(client, manager, benefits=benefits)
    assert package['benefits'] == benefits
    path = f'/api/admin/users/{bid}/package-purchases'
    response = client.post(path, headers=manager, json={'package_id': package['id']})
    assert response.status_code == 201, response.text
    me = client.get('/api/me', headers=bob).json()
    assert me['points'] == 21
    assert all(me[key] for key in ('can_training', 'can_coding', 'can_interview', 'can_exam'))
    for course in (paid, private):
        detail = client.get(f"/api/courses/{course['id']}", headers=bob)
        assert detail.status_code == 200, detail.text
        assert detail.json()['is_enrolled']
        assert client.get(f"/api/courses/lessons/{course['sections'][0]['lessons'][0]['id']}", headers=bob).status_code == 200
        assert client.get(f"/api/live/courses/{course['id']}", headers=bob).status_code == 200
    mine = client.get('/api/courses?scope=mine', headers=bob).json()['items']
    assert {paid['id'], private['id']} <= {row['id'] for row in mine}
    from datetime import date, timedelta
    with connect() as db:
        db.execute('UPDATE package_course_grants SET access_end_date=? WHERE user_id=? AND course_id=?',
                   ((date.today() - timedelta(days=1)).isoformat(), bid, paid['id']))
    assert client.get(f"/api/courses/{paid['id']}", headers=bob).status_code == 404
    assert paid['id'] not in [row['id'] for row in client.get('/api/courses?scope=mine', headers=bob).json()['items']]
    assert client.post(path, headers=manager, json={'package_id': package['id']}).status_code == 409
    assert client.get('/api/me', headers=bob).json()['points'] == 21
    changed = client.patch(f"/api/admin/service-packages/{package['id']}", headers=manager,
                           json={'benefits': {**benefits, 'gift_points': 999}})
    assert changed.status_code == 200
    assert client.get('/api/me', headers=bob).json()['points'] == 21
    detail = client.get(path, headers=manager).json()['items'][0]
    grants = client.get(f"{path}/{detail['id']}/benefits", headers=manager).json()
    assert grants['benefits']['gift_points'] == 21
    assert all(g['status'] == 'granted' for g in grants['grants'])
    assert client.get(f"/api/profile/referrals/{bid}/package-purchases", headers=alice).json() == client.get(path, headers=manager).json()
    assert client.get(f"{path}/{detail['id']}/benefits", headers=alice).status_code == 403
    assert client.delete(f"{path}/{detail['id']}", headers=manager).status_code == 204
    assert client.post(path, headers=manager, json={'package_id': package['id']}).status_code == 201
    assert client.get('/api/me', headers=bob).json()['points'] == 21


def test_package_rejects_unowned_courses_and_bad_resources(client):
    manager, alice, _, _ = setup_accounts(client)
    other_course = create_ready_course(client, manager, '其他管理员课程')
    from app.db import connect
    with connect() as db:
        alice_id = client.get('/api/me', headers=alice).json()['id']
        db.execute('UPDATE live_courses SET owner_id=? WHERE id=?', (alice_id, other_course['id']))
    base = {'name': '套餐', 'price_yuan': '10'}
    for benefits in ({'modules': ['unknown']}, {'gift_points': True}, {'gift_points': -1},
                     {'course_ids': [999999]}, {'course_ids': [other_course['id']]},
                     {'feishu_resources': [{'url': 'https://evil.example/docx/abc', 'permission': 'view'}]},
                     {'feishu_resources': [{'url': 'https://my.feishu.cn/docx/abc?password=secret', 'permission': 'view'}]},
                     {'feishu_resources': [{'url': 'https://my.feishu.cn/docx/abc', 'permission': 'owner'}]}):
        response = client.post('/api/admin/service-packages', headers=manager, json={**base, 'benefits': benefits})
        assert response.status_code in (403, 422), response.text


def test_feishu_failures_persist_and_retry_without_repeating_local_rewards(client, monkeypatch):
    from app.services import feishu_permissions
    manager, _, bob, bid = setup_accounts(client)
    resource = {'url': 'https://my.feishu.cn/drive/folder/Folder123', 'permission': 'edit', 'name': '资料目录'}
    package = create_package(client, manager, benefits={'gift_points': 7, 'feishu_resources': [resource]})
    path = f'/api/admin/users/{bid}/package-purchases'
    missing = client.post(path, headers=manager, json={'package_id': package['id']})
    assert missing.status_code == 422
    assert client.get('/api/me', headers=bob).json()['points'] == 0
    invalid = client.post(path, headers=manager, json={'package_id': package['id'],
                          'feishu_recipient': {'member_type': 'mobile', 'member_id': 'not-a-phone'}})
    assert invalid.status_code == 422
    assert client.get('/api/me', headers=bob).json()['points'] == 0
    calls = []
    def unavailable(resource, recipient):
        calls.append((resource, recipient))
        raise feishu_permissions.GrantError('飞书调用身份无分享权限，请配置协作者权限后重试')
    monkeypatch.setattr(feishu_permissions, 'grant', unavailable)
    recipient = {'member_type': 'mobile', 'member_id': '13800138000'}
    result = client.post(path, headers=manager, json={'package_id': package['id'], 'feishu_recipient': recipient})
    assert result.status_code == 201, result.text
    pid = result.json()['items'][0]['id']
    endpoint = f'{path}/{pid}/benefits'
    detail = client.get(endpoint, headers=manager).json()
    failed = next(g for g in detail['grants'] if g['kind'] == 'feishu')
    assert failed['status'] == 'failed' and failed['attempts'] == 1
    assert '分享权限' in failed['error']
    assert calls[0][1] == recipient
    monkeypatch.setattr(feishu_permissions, 'grant', lambda resource, recipient: calls.append((resource, recipient)))
    assert client.post(endpoint + '/retry', headers=manager).status_code == 202
    detail = client.get(endpoint, headers=manager).json()
    assert all(g['status'] == 'granted' for g in detail['grants'])
    assert len(calls) == 2
    assert client.get('/api/me', headers=bob).json()['points'] == 7
