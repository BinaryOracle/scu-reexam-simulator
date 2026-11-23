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


def test_preview_lesson_returns_a_safe_outline_for_the_study_page(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    course = paid_course(client, admin)
    cid, section = course['id'], course['sections'][0]
    lesson = section['lessons'][0]
    assert client.patch(f"/api/courses/sections/{section['id']}", headers=admin,
                        json={'title': section['title'], 'position': 0, 'preview_enabled': True}).status_code == 200
    assert client.patch(f"/api/courses/lessons/{lesson['id']}", headers=admin,
                        json={'title': lesson['title'], 'position': 0, 'preview_enabled': True}).status_code == 200

    lesson_response = client.get(f"/api/courses/lessons/{lesson['id']}", headers=alice)
    assert lesson_response.status_code == 200, lesson_response.text
    assert lesson_response.json()['preview_only'] is True
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 404

    outline = client.get(f'/api/courses/public/{cid}', headers=alice)
    assert outline.status_code == 200, outline.text
    assert outline.json()['progress_summary'] == {'total': 1, 'completed': 0, 'percent': 0}
    assert outline.json()['sections'][0]['lessons'][0]['progress']['completed'] is False


def test_points_price_must_be_positive_integer(client):
    admin = login(client, 'manager')
    for price in (0, -1, 1.5, True):
        response = client.post('/api/courses', headers=admin, json={
            'title': '无效价格', 'access_mode': 'points', 'points_price': price})
        assert response.status_code == 422


def test_paid_course_duration_is_fixed_at_purchase_and_expires_access(client):
    from app.db import connect
    admin, alice = login(client, 'manager'), login(client, 'alice')
    course = create_ready_course(client, admin, '限时积分课程')
    cid = course['id']
    payload = {key: course[key] for key in ('title', 'description', 'publication_status', 'host_id', 'member_ids')}
    payload.update(access_mode='points', points_price=12, points_access_days=30)
    saved = client.patch(f'/api/courses/{cid}', headers=admin, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()['points_access_days'] == 30
    uid = client.get('/api/me', headers=alice).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET points=20 WHERE id=?', (uid,))
    purchased = client.post(f'/api/courses/{cid}/purchase', headers=alice,
                            json={'expected_points_price': 12})
    assert purchased.status_code == 200, purchased.text
    with connect() as db:
        entitlement = db.execute('SELECT purchased_at,access_expires_at FROM course_purchases WHERE course_id=? AND user_id=?',
                                 (cid, uid)).fetchone()
        assert entitlement['access_expires_at'] == entitlement['purchased_at'] + 30 * 86400

    payload['points_access_days'] = 7
    updated = client.patch(f'/api/courses/{cid}', headers=admin, json=payload)
    assert updated.status_code == 200, updated.text
    with connect() as db:
        assert db.execute('SELECT access_expires_at FROM course_purchases WHERE course_id=? AND user_id=?',
                          (cid, uid)).fetchone()[0] == entitlement['access_expires_at']
        db.execute('UPDATE course_purchases SET access_expires_at=0 WHERE course_id=? AND user_id=?', (cid, uid))
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 404
    assert cid not in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    with connect() as db:
        db.execute('UPDATE users SET points=20 WHERE id=?', (uid,))
    repurchased = client.post(f'/api/courses/{cid}/purchase', headers=alice,
                              json={'expected_points_price': 12})
    assert repurchased.status_code == 200, repurchased.text
    assert repurchased.json()['is_enrolled'] is True
    with connect() as db:
        purchase = db.execute('SELECT points_paid,access_expires_at FROM course_purchases WHERE course_id=? AND user_id=?',
                              (cid, uid)).fetchone()
        assert purchase['points_paid'] == 12
        assert purchase['access_expires_at'] > 0


def test_course_management_detail_reports_participation_by_access_mode(client):
    from app.db import connect
    admin, alice = login(client, 'manager'), login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    public = create_ready_course(client, admin, '公开参与统计')
    assert client.post(f"/api/courses/{public['id']}/enroll", headers=alice).status_code == 200
    public_summary = client.get(f"/api/courses/{public['id']}", headers=admin).json()['enrollment_summary']
    assert public_summary['joined_count'] == 1
    assert public_summary['students'][0]['username'] == 'alice'

    roster = create_ready_course(client, admin, '名单参与统计', access_mode='roster', member_ids=[uid])
    roster_summary = client.get(f"/api/courses/{roster['id']}", headers=admin).json()['enrollment_summary']
    assert roster_summary['assigned_count'] == 1
    assert roster_summary['joined_count'] == 0
    with connect() as db:
        lesson_id = roster['sections'][0]['lessons'][0]['id']
        db.execute('INSERT INTO course_progress(lesson_id,user_id,position_seconds) VALUES (?,?,?)',
                   (lesson_id, uid, 12))
    roster_summary = client.get(f"/api/courses/{roster['id']}", headers=admin).json()['enrollment_summary']
    assert roster_summary['joined_count'] == 1
    assert roster_summary['students'][0]['started'] is True

    paid = create_ready_course(client, admin, '购买参与统计')
    paid_payload = {key: paid[key] for key in ('title', 'description', 'publication_status', 'host_id', 'member_ids')}
    paid_payload.update(access_mode='points', points_price=12)
    assert client.patch(f"/api/courses/{paid['id']}", headers=admin, json=paid_payload).status_code == 200
    with connect() as db:
        db.execute('UPDATE users SET points=20 WHERE id=?', (uid,))
    assert client.post(f"/api/courses/{paid['id']}/purchase", headers=alice,
                       json={'expected_points_price': 12}).status_code == 200
    paid_summary = client.get(f"/api/courses/{paid['id']}", headers=admin).json()['enrollment_summary']
    assert paid_summary['purchased_count'] == 1
    assert paid_summary['students'][0]['username'] == 'alice'
