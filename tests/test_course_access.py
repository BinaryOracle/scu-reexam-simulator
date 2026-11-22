from test_system import client, login
from test_course_learning import create_ready_course


def paid_course(client, admin):
    course = create_ready_course(client, admin, '积分课程')
    payload = {key: course[key] for key in ('title', 'description', 'publication_status', 'host_id', 'member_ids')}
    payload.update(access_mode='points', points_price=12)
    response = client.patch(f"/api/courses/{course['id']}", headers=admin, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_purchase_debits_once_and_survives_price_and_mode_changes(client):
    from app.db import connect
    admin, alice = login(client, 'manager'), login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    course = paid_course(client, admin)
    cid = course['id']
    with connect() as db:
        db.execute('UPDATE users SET points=20 WHERE id=?', (uid,))
    assert client.post(f'/api/courses/{cid}/enroll', headers=alice).status_code == 404
    assert client.post(f'/api/courses/{cid}/purchase', headers=alice,
                       json={'expected_points_price': 11}).status_code == 409
    for _ in range(2):
        result = client.post(f'/api/courses/{cid}/purchase', headers=alice,
                             json={'expected_points_price': 12})
        assert result.status_code == 200, result.text
        assert result.json()['is_enrolled']
    with connect() as db:
        assert db.execute('SELECT points FROM users WHERE id=?', (uid,)).fetchone()[0] == 8
        assert db.execute("SELECT COUNT(*) FROM points_ledger WHERE user_id=? AND kind='course_purchase'", (uid,)).fetchone()[0] == 1
    payload = {key: course[key] for key in ('title', 'description', 'publication_status', 'host_id', 'member_ids')}
    payload.update(access_mode='roster')
    assert client.patch(f'/api/courses/{cid}', headers=admin, json=payload).status_code == 200
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 200
    assert cid in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    assert client.delete(f'/api/courses/{cid}/enroll', headers=alice).status_code == 409


def test_purchase_insufficient_points_rolls_back_and_hidden_courses_cannot_be_bought(client):
    from app.db import connect
    admin, alice = login(client, 'manager'), login(client, 'alice')
    course = paid_course(client, admin)
    cid = course['id']
    uid = client.get('/api/me', headers=alice).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET points=3 WHERE id=?', (uid,))
    assert client.post(f'/api/courses/{cid}/purchase', headers=alice,
                       json={'expected_points_price': 12}).status_code == 409
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 404
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM course_purchases WHERE user_id=?', (uid,)).fetchone()[0] == 0
        db.execute("UPDATE live_courses SET publication_status='draft' WHERE id=?", (cid,))
    assert client.post(f'/api/courses/{cid}/purchase', headers=alice,
                       json={'expected_points_price': 12}).status_code == 404


def test_preview_needs_both_switches_and_guards_assets_and_tickets(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    course = paid_course(client, admin)
    cid, section = course['id'], course['sections'][0]
    first = section['lessons'][0]
    second = client.post(f"/api/courses/sections/{section['id']}/lessons", headers=admin,
                         json={'title': '付费内容', 'description': '不能泄露的正文', 'position': 1}).json()
    markdown = client.post(f"/api/courses/lessons/{first['id']}/markdown", headers=admin,
                           json={'markdown': '# 可预览正文'}).json()
    video = client.post(f"/api/courses/lessons/{first['id']}/assets?kind=video", headers=admin,
                        files={'file': ('lesson.mp4', b'video', 'video/mp4')}).json()
    response = client.patch(f"/api/courses/lessons/{first['id']}", headers=admin,
                            json={'title': first['title'], 'position': 0, 'preview_enabled': True})
    assert response.status_code == 200, response.text
    assert client.get(f"/api/courses/lessons/{first['id']}", headers=alice).status_code == 404
    assert client.patch(f"/api/courses/sections/{section['id']}", headers=admin,
                        json={'title': section['title'], 'position': 0, 'preview_enabled': True}).status_code == 200
    preview = client.get(f'/api/courses/public/{cid}', headers=alice).json()
    assert preview['access_mode'] == 'points' and preview['points_price'] == 12
    lessons = preview['sections'][0]['lessons']
    assert lessons[0]['can_preview'] and not lessons[0]['locked']
    assert lessons[1]['locked'] and not lessons[1].get('description') and 'items' not in lessons[1]
    assert cid in [row['id'] for row in client.get('/api/courses?scope=public', headers=alice).json()['items']]
    assert client.get(f"/api/courses/lessons/{first['id']}", headers=alice).status_code == 200
    assert client.get(f"/api/courses/lessons/{second['id']}", headers=alice).status_code == 404
    assert client.get(f"/api/courses/assets/{markdown['id']}/markdown", headers=alice).status_code == 200
    assert client.get(f"/api/courses/assets/{markdown['id']}/file", headers=alice).status_code == 200
    ticket = client.post(f"/api/courses/assets/{video['id']}/playback", headers=alice)
    assert ticket.status_code == 200, ticket.text
    assert client.get(ticket.json()['url']).status_code == 200
    assert client.patch(f"/api/courses/sections/{section['id']}", headers=admin,
                        json={'title': section['title'], 'position': 0, 'preview_enabled': False}).status_code == 200
    assert client.get(ticket.json()['url']).status_code == 404
    assert client.get(f"/api/courses/assets/{markdown['id']}/markdown", headers=alice).status_code == 404


def test_points_price_must_be_positive_integer(client):
    admin = login(client, 'manager')
    for price in (0, -1, 1.5, True):
        response = client.post('/api/courses', headers=admin, json={
            'title': '无效价格', 'access_mode': 'points', 'points_price': price})
        assert response.status_code == 422
