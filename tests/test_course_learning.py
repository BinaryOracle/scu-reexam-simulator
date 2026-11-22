from pathlib import Path

from test_live import create_course
from test_system import client, login


def create_ready_course(client, admin, title, *, access_mode='public', host_id=None, member_ids=None):
    payload = {'title': title, 'publication_status': 'draft', 'access_mode': access_mode,
               'member_ids': member_ids or []}
    if host_id:
        payload['host_id'] = host_id
    course = client.post('/api/courses', headers=admin, json=payload)
    assert course.status_code == 201, course.text
    value = course.json()
    lesson = client.post(f"/api/courses/sections/{value['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '第一讲', 'position': 0})
    assert lesson.status_code == 201, lesson.text
    asset = client.post(f"/api/courses/lessons/{lesson.json()['id']}/assets?kind=document", headers=admin,
                        files={'file': ('handout.pdf', b'%PDF-test', 'application/pdf')})
    assert asset.status_code == 201, asset.text
    payload.update(publication_status='published', host_id=value['host_id'])
    published = client.patch(f"/api/courses/{value['id']}", headers=admin, json=payload)
    assert published.status_code == 200, published.text
    return published.json()


def test_existing_live_lessons_migrate_to_courses_idempotently(client):
    from app.db import connect
    from app.services.course_schema import initialize_course_learning

    admin, alice, course_id = create_course(client)
    lesson = client.post(f'/api/live/courses/{course_id}/lessons', headers=admin,
                         json={'title': '保留的直播课', 'starts_at': 123}).json()
    with connect() as db:
        db.execute("UPDATE live_lessons SET status='ended' WHERE id=?", (lesson['id'],))
        lesson_before = dict(db.execute('SELECT * FROM live_lessons WHERE id=?', (lesson['id'],)).fetchone())
        members_before = [tuple(row) for row in db.execute(
            'SELECT course_id,user_id FROM live_members WHERE course_id=? ORDER BY user_id', (course_id,))]

        initialize_course_learning(db)
        initialize_course_learning(db)

    with connect() as db:
        course = dict(db.execute('SELECT * FROM live_courses WHERE id=?', (course_id,)).fetchone())
        lesson_after = dict(db.execute('SELECT * FROM live_lessons WHERE id=?', (lesson['id'],)).fetchone())
        sections = list(db.execute('SELECT * FROM course_sections WHERE course_id=?', (course_id,)))
        mapped = list(db.execute('''SELECT cl.*,i.kind,i.live_lesson_id FROM course_lessons cl
            JOIN course_lesson_items i ON i.lesson_id=cl.id WHERE cl.course_id=?''', (course_id,)))
        members_after = [tuple(row) for row in db.execute(
            'SELECT course_id,user_id FROM live_members WHERE course_id=? ORDER BY user_id', (course_id,))]

    assert course['publication_status'] == 'published'
    assert course['access_mode'] == 'roster'
    assert {key: value for key, value in lesson_after.items() if key != 'course_lesson_id'} == {
        key: value for key, value in lesson_before.items() if key != 'course_lesson_id'}
    assert members_after == members_before
    assert len(sections) == 1
    assert len(mapped) == 1
    assert mapped[0]['title'] == '保留的直播课'
    assert mapped[0]['kind'] == 'live'
    assert mapped[0]['live_lesson_id'] == lesson['id']
    assert mapped[0]['id'] == lesson_after['course_lesson_id']
    assert client.get(f'/api/live/courses/{course_id}', headers=alice).status_code == 200


def test_course_and_lesson_descriptions_render_safe_markdown(client):
    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': 'Markdown 课程', 'description': '# 课程简介\n\n**重点** [安全链接](https://example.com) [危险](javascript:alert(1)) <script>alert(1)</script>',
        'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': 'Markdown 课时', 'description': '## 课时说明\n\n- 第一项', 'position': 0}).json()
    detail = client.get(f"/api/courses/{course['id']}", headers=admin).json()
    assert '<h1>课程简介</h1>' in detail['description_html']
    assert '<strong>重点</strong>' in detail['description_html']
    assert '<script>' not in detail['description_html']
    assert 'href="javascript:' not in detail['description_html']
    assert detail['description_summary'].startswith('课程简介 重点 安全链接')
    assert '<h2>课时说明</h2>' in detail['sections'][0]['lessons'][0]['description_html']
    assert client.get(f"/api/courses/lessons/{lesson['id']}", headers=learner).status_code == 404


def test_course_cover_upload_is_private_validated_and_persisted(client):
    import io
    from PIL import Image

    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '封面课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    output = io.BytesIO()
    Image.new('RGB', (12, 8), '#9c4a3b').save(output, format='PNG')
    uploaded = client.post(f"/api/courses/{course['id']}/cover", headers=admin,
                           files={'file': ('cover.png', output.getvalue(), 'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()['cover_kind'] == 'upload'
    assert uploaded.json()['cover_url'] == f"/api/courses/{course['id']}/cover"
    assert 'cover_asset_id' not in uploaded.json()
    stored = client.get(f"/api/courses/{course['id']}", headers=admin).json()
    assert stored['cover_kind'] == 'upload'
    assert client.get(f"/api/courses/{course['id']}/cover", headers=admin).headers['content-type'] == 'image/png'
    assert client.get(f"/api/courses/{course['id']}/cover", headers=learner).status_code == 404
    assert client.post(f"/api/courses/{course['id']}/cover", headers=learner,
                       files={'file': ('cover.png', output.getvalue(), 'image/png')}).status_code == 403
    invalid = client.post(f"/api/courses/{course['id']}/cover", headers=admin,
                          files={'file': ('fake.png', b'not an image', 'image/png')})
    assert invalid.status_code == 422


def test_course_cover_preset_can_be_selected_without_upload(client):
    admin = login(client, 'manager')
    course = client.post('/api/courses', headers=admin, json={
        'title': '预设封面课程', 'cover_kind': 'preset', 'cover_value': 'forest',
        'publication_status': 'draft', 'access_mode': 'public'
    })
    assert course.status_code == 201, course.text
    assert course.json()['cover_kind'] == 'preset'
    assert course.json()['cover_value'] == 'forest'


def test_public_course_cover_is_visible_before_enrollment_and_update_preserves_it(client):
    import io
    from PIL import Image

    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '公开封面课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '第一课', 'position': 0}).json()
    assert client.post(f"/api/courses/lessons/{lesson['id']}/assets?kind=document", headers=admin,
                       files={'file': ('lesson.pdf', b'%PDF-test', 'application/pdf')}).status_code == 201
    output = io.BytesIO()
    Image.new('RGB', (8, 8), '#547d67').save(output, format='PNG')
    assert client.post(f"/api/courses/{course['id']}/cover", headers=admin,
                       files={'file': ('cover.png', output.getvalue(), 'image/png')}).status_code == 200
    assert client.get(f"/api/courses/{course['id']}/cover", headers=learner).status_code == 404
    assert client.patch(f"/api/courses/{course['id']}", headers=admin, json={
        'title': '公开封面课程', 'publication_status': 'published', 'access_mode': 'public'
    }).status_code == 200
    assert client.get(f"/api/courses/{course['id']}/cover", headers=learner).status_code == 200
    assert client.patch(f"/api/courses/{course['id']}", headers=admin, json={
        'title': '更新简介', 'description': '**课程介绍**', 'publication_status': 'published', 'access_mode': 'public'
    }).status_code == 200
    detail = client.get(f"/api/courses/{course['id']}", headers=admin).json()
    assert detail['cover_kind'] == 'upload'
    assert detail['description_summary'] == '课程介绍'
    preview = client.get(f"/api/courses/public/{course['id']}", headers=learner).json()
    assert preview['cover_url'] == f"/api/courses/{course['id']}/cover"
    assert 'cover_asset_id' not in preview


def test_public_enrollment_draft_visibility_and_course_history(client):
    admin, alice, bob = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    alice_id = client.get('/api/me', headers=alice).json()['id']
    draft = client.post('/api/courses', headers=admin, json={
        'title': '草稿课程', 'host_id': alice_id, 'publication_status': 'draft', 'access_mode': 'public'
    })
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()['id']
    assert draft_id not in [item['id'] for item in client.get('/api/courses?scope=public', headers=bob).json()['items']]
    assert client.post(f'/api/courses/{draft_id}/enroll', headers=bob).status_code == 404

    created = create_ready_course(client, admin, '公开课程', host_id=alice_id)
    course_id = created['id']
    public_items = client.get('/api/courses?scope=public', headers=bob).json()['items']
    assert course_id in [item['id'] for item in public_items]
    assert draft_id not in [item['id'] for item in public_items]
    public_detail = client.get(f'/api/courses/{course_id}', headers=bob)
    assert public_detail.status_code == 200
    assert not public_detail.json()['is_enrolled']
    enrolled = client.post(f'/api/courses/{course_id}/enroll', headers=bob)
    assert enrolled.status_code == 200
    assert enrolled.json()['sections'][0]['lessons'][0]['items'][0]['asset']['original_name'] == 'handout.pdf'
    assert client.post(f'/api/courses/{course_id}/enroll', headers=bob).status_code == 200
    learner_detail = client.get(f'/api/courses/{course_id}', headers=bob)
    assert learner_detail.status_code == 200
    assert 'member_ids' not in learner_detail.json()
    assert 'member_ids' in client.get(f'/api/courses/{course_id}', headers=admin).json()
    assert client.get(f'/api/live/courses/{course_id}', headers=bob).status_code == 200
    assert client.delete(f'/api/courses/{course_id}/enroll', headers=bob).json() == {'ok': True}
    public_after_unenroll = client.get(f'/api/courses/{course_id}', headers=bob)
    assert public_after_unenroll.status_code == 200
    assert not public_after_unenroll.json()['is_enrolled']


def test_unpublishing_or_archiving_revokes_enrolled_learner_access(client):
    admin, learner = login(client, 'manager'), login(client, 'bob')
    course = create_ready_course(client, admin, '可撤下课程')
    course_id = course['id']
    lesson_id = course['sections'][0]['lessons'][0]['id']
    assert client.post(f'/api/courses/{course_id}/enroll', headers=learner).status_code == 200
    assert client.get(f'/api/courses/lessons/{lesson_id}', headers=learner).status_code == 200

    archived = {key: course[key] for key in ('title', 'description', 'host_id', 'access_mode', 'member_ids')}
    archived['publication_status'] = 'archived'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=archived).status_code == 200

    assert client.get(f'/api/courses/{course_id}', headers=learner).status_code == 404
    assert client.get(f'/api/courses/lessons/{lesson_id}', headers=learner).status_code == 404
    assert client.get(f'/api/live/courses/{course_id}', headers=learner).status_code == 404
    assert client.post(f'/api/courses/{course_id}/enroll', headers=learner).status_code == 404
    assert course_id not in [item['id'] for item in client.get('/api/courses?scope=mine', headers=learner).json()['items']]

    archived['publication_status'] = 'published'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=archived).status_code == 200
    archived['publication_status'] = 'draft'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=archived).status_code == 200
    assert client.get(f'/api/courses/{course_id}', headers=learner).status_code == 404
    assert client.get(f'/api/courses/lessons/{lesson_id}', headers=learner).status_code == 404
    assert client.get(f'/api/live/courses/{course_id}', headers=learner).status_code == 404


def test_course_management_access_does_not_appear_as_learner_enrollment(client):
    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '管理员课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']

    assert course_id not in [item['id'] for item in client.get('/api/courses?scope=mine', headers=admin).json()['items']]
    assert course_id in [item['id'] for item in client.get('/api/courses?scope=managed', headers=admin).json()['items']]

    published = create_ready_course(client, admin, '公开课程状态', host_id=client.get('/api/me', headers=learner).json()['id'])
    preview = client.get(f"/api/courses/public/{published['id']}", headers=learner).json()
    assert preview['is_enrolled'] is False
    assert preview['can_manage'] is False
    assert published['id'] not in [item['id'] for item in client.get('/api/courses?scope=mine', headers=learner).json()['items']]
    assert client.post(f"/api/courses/{published['id']}/enroll", headers=learner).status_code == 200
    preview = client.get(f"/api/courses/public/{published['id']}", headers=learner).json()
    assert preview['is_enrolled'] is True
    assert client.get(f"/api/courses/public/{published['id']}", headers=admin).json()['can_manage'] is True
    assert published['id'] in [item['id'] for item in client.get('/api/courses?scope=mine', headers=learner).json()['items']]


def test_public_outline_retains_chapter_ids_and_only_the_members_own_progress(client):
    admin, alice, bob = (login(client, name) for name in ('manager', 'alice', 'bob'))
    course = create_ready_course(client, admin, '统一课程目录')
    cid = course['id']
    section = course['sections'][0]
    lid = section['lessons'][0]['id']
    preview = client.get(f'/api/courses/public/{cid}', headers=alice).json()
    assert preview['sections'][0]['id'] == section['id']
    assert 'progress' not in preview['sections'][0]['lessons'][0]
    assert 'items' not in preview['sections'][0]['lessons'][0]
    assert client.get(f'/api/courses/lessons/{lid}', headers=alice).status_code == 404
    assert client.post(f'/api/courses/{cid}/enroll', headers=alice).status_code == 200
    assert client.put(f'/api/courses/lessons/{lid}/progress', headers=alice,
                      json={'position_seconds': 0, 'completed': True}).status_code == 200
    enrolled = client.get(f'/api/courses/public/{cid}', headers=alice).json()
    assert enrolled['sections'][0]['lessons'][0]['progress']['completed'] == 1
    assert enrolled['progress_summary']['completed'] == 1
    assert client.post(f'/api/courses/{cid}/enroll', headers=bob).status_code == 200
    other = client.get(f'/api/courses/public/{cid}', headers=bob).json()
    assert other['sections'][0]['lessons'][0]['progress']['completed'] == 0
    assert other['progress_summary']['completed'] == 0


def test_removing_a_course_only_changes_the_current_users_library(client):
    admin, alice, bob = (login(client, name) for name in ('manager', 'alice', 'bob'))
    course = create_ready_course(client, admin, '可移除课程')
    cid, lid = course['id'], course['sections'][0]['lessons'][0]['id']
    for learner in (alice, bob):
        assert client.post(f'/api/courses/{cid}/enroll', headers=learner).status_code == 200
    assert client.put(f'/api/courses/lessons/{lid}/progress', headers=alice,
                      json={'position_seconds': 0, 'completed': True}).status_code == 200
    for _ in range(2):
        assert client.delete(f'/api/courses/{cid}/library', headers=alice).status_code == 200
    assert cid not in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    assert cid in [row['id'] for row in client.get('/api/courses?scope=mine&removed=true', headers=alice).json()['items']]
    assert cid in [row['id'] for row in client.get('/api/courses?scope=mine', headers=bob).json()['items']]
    detail = client.get(f'/api/courses/{cid}', headers=alice).json()
    assert detail['is_removed_from_library'] is True and detail['progress_summary']['completed'] == 1
    assert client.get(f'/api/courses/lessons/{lid}', headers=alice).json()['progress']['completed'] == 1
    for _ in range(2):
        assert client.post(f'/api/courses/{cid}/library', headers=alice).status_code == 200
    assert cid in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    assert not client.get('/api/courses?scope=mine&removed=true', headers=alice).json()['items']


def test_assigned_course_can_be_removed_and_restored_without_altering_roster(client):
    from app.db import connect, initialize

    admin, alice, bob = (login(client, name) for name in ('manager', 'alice', 'bob'))
    uid = client.get('/api/me', headers=alice).json()['id']
    course = create_ready_course(client, admin, '名单课程', access_mode='roster', member_ids=[uid])
    cid = course['id']
    assert client.delete(f'/api/courses/{cid}/library', headers=bob).status_code == 404
    assert client.post(f'/api/courses/{cid}/library', headers=bob).status_code == 404
    assert client.delete(f'/api/courses/{cid}/library', headers=alice).status_code == 200
    initialize()
    with connect() as db:
        assert db.execute('SELECT 1 FROM live_members WHERE course_id=? AND user_id=?', (cid, uid)).fetchone()
    assert cid not in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    assert client.post(f'/api/courses/{cid}/library', headers=alice).status_code == 200
    assert cid in [row['id'] for row in client.get('/api/courses?scope=mine', headers=alice).json()['items']]
    assert client.delete(f'/api/courses/{cid}/library').status_code == 401


def test_learner_can_complete_an_ended_live_only_course_lesson(client):
    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '直播课进度', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']
    created = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/live", headers=admin,
                          json={'title': '第一讲', 'description': '', 'position': 0, 'starts_at': 123})
    assert created.status_code == 201, created.text
    lesson_id = created.json()['sections'][0]['lessons'][0]['id']
    payload = {'title': course['title'], 'description': '', 'publication_status': 'published',
               'access_mode': 'public', 'host_id': course['host_id'], 'member_ids': []}
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=payload).status_code == 200
    assert client.post(f'/api/courses/{course_id}/enroll', headers=learner).status_code == 200
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE live_lessons SET status='ended' WHERE course_lesson_id=?", (lesson_id,))

    complete = client.put(f'/api/courses/lessons/{lesson_id}/progress', headers=learner,
                          json={'position_seconds': 0, 'completed': True})
    assert complete.status_code == 200, complete.text
    assert complete.json()['completed'] == 1
    assert client.get(f'/api/courses/{course_id}', headers=learner).json()['progress_summary'] == {
        'total': 1, 'completed': 1, 'percent': 100}


def test_course_catalog_selects_the_most_recent_unfinished_lesson_for_resume(client):
    from app.db import connect

    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '按进度继续学习', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']
    section_id = course['sections'][0]['id']
    learner_id = client.get('/api/me', headers=learner).json()['id']
    first_lesson = client.post(f'/api/courses/sections/{section_id}/lessons', headers=admin,
                               json={'title': '第一讲', 'position': 0}).json()['id']
    first_doc = client.post(f'/api/courses/lessons/{first_lesson}/assets?kind=document', headers=admin,
                            files={'file': ('notes.pdf', b'%PDF-first', 'application/pdf')})
    assert first_doc.status_code == 201
    second_lesson = client.post(f'/api/courses/sections/{section_id}/lessons', headers=admin,
                                json={'title': '第二讲', 'position': 1}).json()['id']
    video = client.post(f'/api/courses/lessons/{second_lesson}/assets?kind=video', headers=admin,
                        files={'file': ('lesson.mp4', b'video', 'video/mp4')})
    assert video.status_code == 201, video.text
    published = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    published['publication_status'] = 'published'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=published).status_code == 200
    assert client.post(f'/api/courses/{course_id}/enroll', headers=learner).status_code == 200
    with connect() as db:
        db.execute('''INSERT INTO course_progress(lesson_id,user_id,position_seconds,completed,updated)
            VALUES (?,?,20,0,100)''', (first_lesson, learner_id))
        db.execute('''INSERT INTO course_progress(lesson_id,user_id,position_seconds,completed,updated)
            VALUES (?,?,90,0,200)''', (second_lesson, learner_id))

    items = client.get('/api/courses?scope=mine', headers=learner).json()['items']
    selected = next(item for item in items if item['id'] == course_id)
    assert selected['resume_lesson_id'] == second_lesson
    preview = client.get(f'/api/courses/public/{course_id}', headers=learner).json()
    assert preview['resume_lesson_id'] == second_lesson
    assert preview['progress_summary'] == {'total': 2, 'completed': 0, 'percent': 0}

    with connect() as db:
        db.execute('UPDATE course_progress SET completed=1 WHERE lesson_id=? AND user_id=?',
                   (second_lesson, learner_id))
    selected = next(item for item in client.get('/api/courses?scope=mine', headers=learner).json()['items']
                    if item['id'] == course_id)
    assert selected['resume_lesson_id'] == first_lesson
    preview = client.get(f'/api/courses/public/{course_id}', headers=learner).json()
    assert preview['resume_lesson_id'] == first_lesson


def test_course_catalog_orders_courses_by_the_current_users_recent_activity(client):
    from app.db import connect

    admin, learner = login(client, 'manager'), login(client, 'alice')
    older = create_ready_course(client, admin, '先学习的课程')
    newer = create_ready_course(client, admin, '最近学习的课程')
    learner_id = client.get('/api/me', headers=learner).json()['id']
    for course, updated in ((older, 100), (newer, 200)):
        assert client.post(f"/api/courses/{course['id']}/enroll", headers=learner).status_code == 200
        lesson_id = course['sections'][0]['lessons'][0]['id']
        with connect() as db:
            db.execute('''INSERT INTO course_progress(lesson_id,user_id,position_seconds,completed,updated)
                VALUES (?,?,10,0,?)''', (lesson_id, learner_id, updated))

    items = client.get('/api/courses?scope=mine', headers=learner).json()['items']
    ordered_ids = [item['id'] for item in items]
    assert ordered_ids.index(newer['id']) < ordered_ids.index(older['id'])


def test_course_lesson_includes_safe_recording_status_for_its_live_item(client):
    from app.db import connect

    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '直播回放并入课时', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    created = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/live", headers=admin,
                          json={'title': '第一讲', 'starts_at': 123, 'position': 0})
    assert created.status_code == 201, created.text
    lesson = created.json()['sections'][0]['lessons'][0]
    live_id = lesson['items'][0]['live_lesson_id']
    with connect() as db:
        ready_id = db.execute(
            "INSERT INTO live_recordings(lesson_id,status,path) VALUES (?,'ready','private-ready.mp4')",
            (live_id,)).lastrowid
        pending_id = db.execute(
            "INSERT INTO live_recordings(lesson_id,status,path) VALUES (?,'recording','private-pending.mp4')",
            (live_id,)).lastrowid

    published = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    published['publication_status'] = 'published'
    assert client.patch(f"/api/courses/{course['id']}", headers=admin, json=published).status_code == 200
    assert client.post(f"/api/courses/{course['id']}/enroll", headers=learner).status_code == 200

    response = client.get(f"/api/courses/lessons/{lesson['id']}", headers=learner)
    assert response.status_code == 200
    live_item = next(item for item in response.json()['items'] if item['kind'] == 'live')
    assert live_item['recordings'] == [
        {'id': ready_id, 'status': 'ready'}, {'id': pending_id, 'status': 'recording'}]
    assert 'path' not in str(live_item['recordings'])
    assert client.post(f'/api/live/recordings/{ready_id}/playback', headers=learner).status_code == 200
    assert client.post(f'/api/live/recordings/{pending_id}/playback', headers=learner).status_code == 409


def test_markdown_live_preview_matches_lesson_rendering_and_requires_admin(client):
    from app.db import connect
    from app.services.course_learning import render_lesson_markdown

    admin, learner = login(client, 'manager'), login(client, 'alice')
    markdown = '# 标题\n\n**重点**\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n公式：$x^2$\n\n<script>alert(1)</script>\n\n[危险](javascript:alert(1))'
    with connect() as db:
        before = db.execute('SELECT COUNT(*) FROM course_assets').fetchone()[0]
    response = client.post('/api/courses/markdown/preview', headers=admin, json={'markdown': markdown})
    assert response.status_code == 200
    assert response.text == render_lesson_markdown(markdown)
    assert '<h1>标题</h1>' in response.text and '<table>' in response.text
    assert 'class="math inline"' in response.text
    assert '<script>' not in response.text and 'href="javascript:' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/courses/markdown/preview', headers=learner, json={'markdown': markdown}).status_code == 403
    assert client.post('/api/courses/markdown/preview', json={'markdown': markdown}).status_code == 401
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM course_assets').fetchone()[0] == before


def test_course_markdown_document_renders_safe_html_for_enrolled_learners(client):
    admin, learner, outsider = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    course = client.post('/api/courses', headers=admin, json={
        'title': 'Markdown 正文', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '正文课时', 'position': 0}).json()
    uploaded = client.post(f"/api/courses/lessons/{lesson['id']}/assets?kind=document", headers=admin,
                           files={'file': ('lesson.md', '# 本节内容\n\n<script>alert(1)</script>\n\n**重点**\n\n公式：$x^2$\n\n![外部图](https://example.com/image.png)\n\n[危险链接](javascript:alert(1))'.encode(), 'text/markdown')})
    assert uploaded.status_code == 201, uploaded.text
    published = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    published['publication_status'] = 'published'
    assert client.patch(f"/api/courses/{course['id']}", headers=admin, json=published).status_code == 200
    assert client.post(f"/api/courses/{course['id']}/enroll", headers=learner).status_code == 200

    response = client.get(f"/api/courses/assets/{uploaded.json()['id']}/markdown", headers=learner)
    assert response.status_code == 200
    assert '<h1>本节内容</h1>' in response.text
    assert '<strong>重点</strong>' in response.text
    assert 'class="math inline"' in response.text
    assert '<script>' not in response.text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text
    assert '<img' not in response.text
    assert 'href="javascript:' not in response.text
    assert client.get(f"/api/courses/assets/{uploaded.json()['id']}/markdown", headers=outsider).status_code == 404


def test_course_markdown_document_can_be_edited_by_course_managers(client):
    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '可编辑 Markdown', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '正文课时', 'position': 0}).json()
    asset = client.post(f"/api/courses/lessons/{lesson['id']}/assets?kind=document", headers=admin,
                        files={'file': ('lesson.md', b'# Before', 'text/markdown')}).json()

    updated = client.put(f"/api/courses/assets/{asset['id']}/markdown", headers=admin,
                         json={'markdown': '# Updated\n\nNew lesson text.', 'name': '更新后的课程正文'})
    assert updated.status_code == 200, updated.text
    assert updated.json() == {'ok': True, 'size': len('# Updated\n\nNew lesson text.'.encode())}
    assert client.get(f"/api/courses/assets/{asset['id']}/markdown", headers=admin).status_code == 200
    assert client.get(f"/api/courses/assets/{asset['id']}/markdown", headers=admin).text.startswith('<h1>Updated</h1>')
    assert client.get(f"/api/courses/lessons/{lesson['id']}", headers=admin).json()['items'][0]['asset']['original_name'] == '更新后的课程正文.md'
    empty = client.put(f"/api/courses/assets/{asset['id']}/markdown", headers=admin,
                       json={'markdown': '  \n'})
    assert empty.status_code == 422
    assert client.get(f"/api/courses/assets/{asset['id']}/markdown", headers=admin).text.startswith('<h1>Updated</h1>')
    assert client.put(f"/api/courses/assets/{asset['id']}/markdown", headers=learner,
                      json={'markdown': 'not allowed'}).status_code == 403


def test_course_markdown_supports_private_pasted_images(client):
    import io
    from PIL import Image

    admin, learner, outsider = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    course = client.post('/api/courses', headers=admin, json={
        'title': '图片正文课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '图片课时', 'position': 0}).json()
    image = io.BytesIO()
    Image.new('RGB', (24, 16), '#456b58').save(image, format='PNG')

    uploaded = client.post(f"/api/courses/lessons/{lesson['id']}/markdown-images", headers=admin,
                           files={'file': ('pasted.png', image.getvalue(), 'image/png')})
    assert uploaded.status_code == 201, uploaded.text
    image_id = uploaded.json()['id']
    assert uploaded.json()['url'] == f'/api/courses/markdown-images/{image_id}'
    assert client.get(uploaded.json()['url'], headers=outsider).status_code == 404
    assert client.get(uploaded.json()['url'], headers=admin).status_code == 200

    markdown = f'# 图文课时\n\n![流程图]({uploaded.json()["url"]})'
    saved = client.post(f"/api/courses/lessons/{lesson['id']}/markdown", headers=admin,
                        json={'markdown': markdown, 'name': '图文正文'})
    assert saved.status_code == 201, saved.text
    assert saved.json()['kind'] == 'document'
    rendered = client.get(f"/api/courses/assets/{saved.json()['id']}/markdown", headers=admin)
    assert '<img src="/api/courses/markdown-images/' in rendered.text
    assert 'img-src \'self\'' in rendered.headers['content-security-policy']

    wrong_lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                               json={'title': '另一课时', 'position': 1}).json()
    rejected = client.post(f"/api/courses/lessons/{wrong_lesson['id']}/markdown", headers=admin,
                           json={'markdown': f'![越权图片]({uploaded.json()["url"]})', 'name': '越权'})
    assert rejected.status_code == 422
    external = client.post(f"/api/courses/lessons/{lesson['id']}/markdown", headers=admin,
                           json={'markdown': '![外链](https://example.com/image.png)', 'name': '外链'})
    assert external.status_code == 422


def test_course_intro_markdown_supports_course_scoped_pasted_images(client):
    import io
    from PIL import Image

    admin, learner, outsider = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    course = client.post('/api/courses', headers=admin, json={
        'title': '图文简介课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    image = io.BytesIO()
    Image.new('RGB', (24, 16), '#456b58').save(image, format='PNG')

    uploaded = client.post(f"/api/courses/{course['id']}/markdown-images", headers=admin,
                           files={'file': ('pasted.png', image.getvalue(), 'image/png')})
    assert uploaded.status_code == 201, uploaded.text
    image_id = uploaded.json()['id']
    assert uploaded.json()['url'] == f'/api/courses/markdown-images/{image_id}'
    assert client.get(uploaded.json()['url'], headers=outsider).status_code == 404
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                         json={'title': '简介中的示例课时', 'position': 0}).json()
    material = client.post(f"/api/courses/lessons/{lesson['id']}/markdown", headers=admin,
                           json={'markdown': '# 课程内容\n\n正文。'})
    assert material.status_code == 201, material.text
    updated = client.patch(f"/api/courses/{course['id']}", headers=admin, json={
        'title': course['title'], 'description': f"# 课程简介\n\n![架构图]({uploaded.json()['url']})",
        'publication_status': 'published', 'access_mode': 'public', 'host_id': course['host_id'], 'member_ids': []
    })
    assert updated.status_code == 200, updated.text
    assert '<img src="/api/courses/markdown-images/' in updated.json()['description_html']
    assert client.post(f"/api/courses/{course['id']}/enroll", headers=learner).status_code == 200
    assert client.get(uploaded.json()['url'], headers=learner).status_code == 200
    assert client.get(uploaded.json()['url'], headers=outsider).status_code == 200

    other = client.post('/api/courses', headers=admin, json={
        'title': '另一门课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    rejected = client.patch(f"/api/courses/{other['id']}", headers=admin, json={
        'title': other['title'], 'description': f"![越权图片]({uploaded.json()['url']})",
        'publication_status': 'draft', 'access_mode': 'public', 'host_id': other['host_id'], 'member_ids': []
    })
    assert rejected.status_code == 422


def test_course_deletion_requires_admin_and_removes_course_and_live_files(client):
    from app.db import connect
    from app.config import load_config
    from app.routes.live import private_path

    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '待删除课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']
    lesson = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/live", headers=admin,
                         json={'title': '直播课', 'position': 0, 'starts_at': 123})
    assert lesson.status_code == 201, lesson.text
    lesson = lesson.json()['sections'][0]['lessons'][0]
    live_id = lesson['items'][0]['live_lesson_id']
    live_asset = client.post(f'/api/live/lessons/{live_id}/materials', headers=admin,
                             files={'file': ('notes.txt', b'live material', 'text/plain')})
    assert live_asset.status_code == 200, live_asset.text
    course_asset = client.post(f"/api/courses/lessons/{lesson['id']}/assets?kind=document", headers=admin,
                               files={'file': ('handout.pdf', b'%PDF-course', 'application/pdf')})
    assert course_asset.status_code == 201, course_asset.text
    publish = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    publish['publication_status'] = 'published'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=publish).status_code == 200
    assert client.post(f'/api/courses/{course_id}/enroll', headers=learner).status_code == 200
    learner_id = client.get('/api/me', headers=learner).json()['id']
    with connect() as db:
        live_name = db.execute('SELECT path FROM live_materials WHERE lesson_id=?', (live_id,)).fetchone()[0]
        course_name = db.execute('SELECT storage_name FROM course_assets WHERE course_id=?', (course_id,)).fetchone()[0]
        db.execute('INSERT INTO live_recordings(lesson_id,status,path) VALUES (? ,\'ready\',\'replay.mp4\')',
                   (live_id,))
        db.execute('INSERT INTO course_progress(lesson_id,user_id,position_seconds,updated) VALUES (?,?,12,1)',
                   (lesson['id'], learner_id))
    live_path = private_path('materials', live_name)
    recording_path = private_path('recordings', 'replay.mp4')
    recording_path.write_bytes(b'live recording')
    course_path = Path(load_config()['course_media']['directory']) / 'assets' / course_name
    assert live_path.is_file() and recording_path.is_file() and course_path.is_file()

    assert client.delete(f'/api/courses/{course_id}', headers=learner).status_code == 403
    deleted = client.delete(f'/api/courses/{course_id}', headers=admin)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {'ok': True}
    assert not live_path.exists() and not recording_path.exists() and not course_path.exists()
    assert client.get(f'/api/courses/{course_id}', headers=admin).status_code == 404
    with connect() as db:
        assert db.execute('SELECT 1 FROM live_lessons WHERE id=?', (live_id,)).fetchone() is None
        assert db.execute('SELECT 1 FROM course_assets WHERE course_id=?', (course_id,)).fetchone() is None
        assert db.execute('SELECT 1 FROM course_progress WHERE lesson_id=?', (lesson['id'],)).fetchone() is None
        assert db.execute('SELECT 1 FROM course_self_enrollments WHERE course_id=?', (course_id,)).fetchone() is None


def test_course_deletion_rejects_a_course_with_a_live_session(client):
    admin = login(client, 'manager')
    course = client.post('/api/courses', headers=admin, json={
        'title': '直播中课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    live = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/live", headers=admin,
                       json={'title': '正在直播', 'position': 0, 'starts_at': 123})
    assert live.status_code == 201, live.text
    live_id = live.json()['sections'][0]['lessons'][0]['items'][0]['live_lesson_id']
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE live_lessons SET status='live' WHERE id=?", (live_id,))

    response = client.delete(f"/api/courses/{course['id']}", headers=admin)
    assert response.status_code == 409
    assert client.get(f"/api/courses/{course['id']}", headers=admin).status_code == 200


def test_course_deletion_rejects_an_unresolved_live_recording(client):
    admin = login(client, 'manager')
    course = client.post('/api/courses', headers=admin, json={
        'title': '录制状态未确认', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    live = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/live", headers=admin,
                       json={'title': '直播回放', 'position': 0, 'starts_at': 123})
    assert live.status_code == 201, live.text
    live_id = live.json()['sections'][0]['lessons'][0]['items'][0]['live_lesson_id']
    from app.db import connect
    with connect() as db:
        db.execute("INSERT INTO live_recordings(lesson_id,status,path) VALUES (?,'recording','pending.mp4')",
                   (live_id,))

    response = client.delete(f"/api/courses/{course['id']}", headers=admin)
    assert response.status_code == 409
    assert client.get(f"/api/courses/{course['id']}", headers=admin).status_code == 200


def test_public_preview_is_safe_and_publishing_requires_ready_content(client):
    admin, learner = login(client, 'manager'), login(client, 'bob')
    created = client.post('/api/courses', headers=admin, json={
        'title': '数据结构基础', 'publication_status': 'draft', 'access_mode': 'public'
    })
    assert created.status_code == 201, created.text
    course = created.json()
    course_id = course['id']
    manager_detail = client.get(f'/api/courses/{course_id}', headers=admin)
    assert manager_detail.status_code == 200
    assert manager_detail.json()['publish_issues'] == ['至少添加一个课时']
    publish = {
        'title': course['title'], 'description': course['description'],
        'publication_status': 'published', 'access_mode': 'public',
        'host_id': course['host_id'], 'member_ids': []
    }
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=publish).status_code == 422

    section_id = course['sections'][0]['id']
    lesson = client.post(f'/api/courses/sections/{section_id}/lessons', headers=admin, json={
        'title': '第一讲：复杂度分析', 'description': '时间与空间复杂度', 'position': 0
    }).json()
    manager_detail = client.get(f'/api/courses/{course_id}', headers=admin).json()
    assert manager_detail['publish_issues'] == ['为课时“第一讲：复杂度分析”添加可学习内容']
    document = client.post(f"/api/courses/lessons/{lesson['id']}/assets?kind=document", headers=admin,
                           files={'file': ('讲义.pdf', b'%PDF-content', 'application/pdf')})
    assert document.status_code == 201, document.text
    assert client.get(f'/api/courses/{course_id}', headers=admin).json()['publish_issues'] == []
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=publish).status_code == 200

    admin_catalog = client.get('/api/courses?scope=public', headers=admin)
    assert admin_catalog.status_code == 200, admin_catalog.text
    public_card = next(item for item in admin_catalog.json()['items'] if item['id'] == course_id)
    assert 'owner_id' not in public_card and 'member_ids' not in public_card
    preview = client.get(f'/api/courses/public/{course_id}', headers=learner)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body['title'] == '数据结构基础'
    assert body['host_name'] == 'manager'
    assert body['sections'][0]['lessons'][0]['title'] == '第一讲：复杂度分析'
    assert body['sections'][0]['lessons'][0]['content_kinds'] == ['document']
    assert 'member_ids' not in body and 'owner_id' not in body and 'items' not in body['sections'][0]['lessons'][0]
    assert client.get(f"/api/courses/lessons/{lesson['id']}", headers=learner).status_code == 200


def test_roster_course_sections_and_lesson_authorization(client):
    admin, alice, bob = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    alice_id = client.get('/api/me', headers=alice).json()['id']
    created = create_ready_course(client, admin, '名单课程', access_mode='roster', host_id=alice_id,
                                  member_ids=[alice_id])
    course_id = created['id']
    section = client.post(f'/api/courses/{course_id}/sections', headers=admin,
                          json={'title': '第二章', 'position': 1})
    assert section.status_code == 201, section.text
    lesson = client.post(f"/api/courses/sections/{section.json()['id']}/lessons", headers=admin,
                         json={'title': '文档课', 'description': '阅读资料', 'position': 0})
    assert lesson.status_code == 201, lesson.text
    lesson_id = lesson.json()['id']
    assert client.get(f'/api/courses/{course_id}', headers=bob).status_code == 404
    assert client.get(f'/api/courses/lessons/{lesson_id}', headers=bob).status_code == 404
    assert client.patch(f'/api/courses/lessons/{lesson_id}', headers=alice,
                        json={'title': '越权修改', 'position': 0}).status_code == 403
    overview = client.get(f'/api/courses/{course_id}', headers=alice).json()
    assert [chapter['title'] for chapter in overview['sections']] == ['第一章', '第二章']
    assert overview['sections'][1]['lessons'][0]['title'] == '文档课'
    assert client.put(f'/api/courses/lessons/{lesson_id}/progress', headers=alice,
                      json={'position_seconds': 0, 'completed': True}).status_code == 422


def test_course_authoring_requires_explicit_content_cleanup_and_orders_mixed_items(client):
    admin, learner = login(client, 'manager'), login(client, 'alice')
    course = client.post('/api/courses', headers=admin, json={
        'title': '课程编排', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']
    section_id = course['sections'][0]['id']
    lesson = client.post(f'/api/courses/sections/{section_id}/lessons', headers=admin,
                         json={'title': '混合课时', 'position': 0}).json()
    lesson_id = lesson['id']
    assert client.patch(f'/api/courses/sections/{section_id}', headers=admin,
                        json={'title': '基础章节', 'position': 0}).json()['title'] == '基础章节'

    document = client.post(f'/api/courses/lessons/{lesson_id}/assets?kind=document', headers=admin,
                           files={'file': ('notes.pdf', b'%PDF-content', 'application/pdf')}).json()
    video = client.post(f'/api/courses/lessons/{lesson_id}/assets?kind=video', headers=admin,
                        files={'file': ('lesson.mp4', b'video-content', 'video/mp4')}).json()
    assert client.delete(f'/api/courses/sections/{section_id}', headers=admin).status_code == 409
    assert client.delete(f'/api/courses/lessons/{lesson_id}', headers=admin).status_code == 409

    detail = client.get(f'/api/courses/{course_id}', headers=admin).json()
    items = detail['sections'][0]['lessons'][0]['items']
    reordered = client.put(f'/api/courses/lessons/{lesson_id}/items', headers=admin, json={
        'items': [{'id': items[1]['id'], 'kind': items[1]['kind']},
                  {'id': items[0]['id'], 'kind': items[0]['kind']}]
    })
    assert reordered.status_code == 200, reordered.text
    assert [item['kind'] for item in reordered.json()['items']] == ['video', 'document']
    assert client.delete(f"/api/courses/assets/{video['id']}", headers=admin).status_code == 200
    assert client.delete(f"/api/courses/assets/{document['id']}", headers=admin).status_code == 200
    assert client.delete(f'/api/courses/lessons/{lesson_id}', headers=admin).status_code == 200
    assert client.delete(f'/api/courses/sections/{section_id}', headers=admin).status_code == 409

    second = client.post(f'/api/courses/{course_id}/sections', headers=admin,
                         json={'title': '第二章', 'position': 1}).json()
    assert client.delete(f"/api/courses/sections/{second['id']}", headers=learner).status_code == 403
    assert client.delete(f"/api/courses/sections/{second['id']}", headers=admin).status_code == 200


def test_live_class_is_created_as_a_course_unit_in_one_operation(client):
    from app.db import connect

    admin = login(client, 'manager')
    course = client.post('/api/courses', headers=admin, json={
        'title': '直播系列课', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    section = course['sections'][0]
    response = client.post(f"/api/courses/sections/{section['id']}/live", headers=admin, json={
        'title': '第一讲：课程导论', 'description': '直播组成课程课次', 'position': 0, 'starts_at': 1_800_000_000
    })
    assert response.status_code == 201, response.text
    detail = response.json()
    unit = detail['sections'][0]['lessons'][0]
    assert unit['title'] == '第一讲：课程导论'
    assert len(unit['items']) == 1
    assert unit['items'][0]['kind'] == 'live'
    assert unit['items'][0]['live']['title'] == unit['title']
    publish = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    publish['publication_status'] = 'published'
    assert client.patch(f"/api/courses/{course['id']}", headers=admin, json=publish).status_code == 200
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_lessons WHERE course_lesson_id=?',
                          (unit['id'],)).fetchone()[0] == 1


def test_private_course_assets_ticket_range_and_revoked_enrollment(client):
    from app.db import connect
    admin, bob = login(client, 'manager'), login(client, 'bob')
    course = client.post('/api/courses', headers=admin, json={
        'title': '媒体课程', 'publication_status': 'draft', 'access_mode': 'public'
    }).json()
    course_id = course['id']
    lesson_id = client.post(f"/api/courses/sections/{course['sections'][0]['id']}/lessons", headers=admin,
                            json={'title': '录播与资料', 'position': 0}).json()['id']
    url = f'/api/courses/lessons/{lesson_id}/assets'
    assert client.post(url + '?kind=document', headers=admin,
                       files={'file': ('bad.html', b'<script>', 'text/html')}).status_code == 422
    document = client.post(url + '?kind=document', headers=admin,
                           files={'file': ('notes.pdf', b'%PDF-private', 'application/pdf')})
    assert document.status_code == 201, document.text
    publish = {key: course[key] for key in ('title', 'description', 'access_mode', 'host_id', 'member_ids')}
    publish['publication_status'] = 'published'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=publish).status_code == 200
    assert client.post(f'/api/courses/{course_id}/enroll', headers=bob).status_code == 200
    file_url = f"/api/courses/assets/{document.json()['id']}/file"
    assert client.get(file_url).status_code == 401
    assert client.get(file_url, headers=login(client, 'alice')).content == b'%PDF-private'
    assert client.get(file_url, headers=bob).content == b'%PDF-private'

    video = client.post(url + '?kind=video', headers=admin,
                        files={'file': ('lesson.mp4', b'0123456789', 'video/mp4')})
    assert video.status_code == 201, video.text
    playback = client.post(f"/api/courses/assets/{video.json()['id']}/playback", headers=bob)
    assert playback.status_code == 200
    ticket_url = playback.json()['url']
    ranged = client.get(ticket_url, headers={'Range': 'bytes=2-5'})
    assert ranged.status_code == 206
    assert ranged.content == b'2345'
    assert ranged.headers['content-type'].startswith('video/mp4')
    assert client.get(ticket_url).content == b'0123456789'
    publish['publication_status'] = 'archived'
    assert client.patch(f'/api/courses/{course_id}', headers=admin, json=publish).status_code == 200
    assert client.get(ticket_url).status_code == 404
    with connect() as db:
        bob_id = client.get('/api/me', headers=bob).json()['id']
        assert not db.execute('SELECT 1 FROM live_members WHERE course_id=? AND user_id=?',
                              (course_id, bob_id)).fetchone()
