"""Behavioral tests for courses and a real WebM -> live HLS -> replay round-trip."""
import subprocess
import time
import imageio_ffmpeg
import pytest
from starlette.websockets import WebSocketDisconnect
from test_system import client, login


def create(client, admin, *, published=False, live=False, access='all'):
    response = client.post('/api/admin/courses', headers=admin,
                           json={'title': '数据结构精讲', 'published': published})
    assert response.status_code == 201, response.text
    cid = response.json()['id']
    if access == 'all':
        assert client.put(f'/api/admin/courses/{cid}/access', headers=admin, json={'mode': 'all'}).status_code == 204
    data = {'title': '线性表', 'position': 2}
    if live:
        data.update(live_start=time.time() - 30, live_end=time.time() + 150)
    response = client.post(f'/api/admin/courses/{cid}/lessons', headers=admin, json=data)
    assert response.status_code == 201, response.text
    return cid, response.json()['id']


def media_cookie(client, auth):
    assert client.post('/api/courses/media-access', headers=auth).status_code == 204


def test_catalog_permissions_and_publish_lifecycle(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/courses').status_code == 401
    assert client.post('/api/admin/courses', headers=alice, json={'title': 'bad'}).status_code == 403
    cid, lid = create(client, admin)
    url = f'/api/admin/courses/{cid}'
    assert client.get('/api/courses', headers=alice).json() == []
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 404
    assert client.put(url, headers=admin, json={'title': '新课程名', 'published': True}).status_code == 200
    assert client.get('/api/courses', headers=alice).json()[0]['lesson_count'] == 1
    assert client.get(f'/api/courses/{cid}', headers=alice).json()['title'] == '新课程名'
    assert client.post('/api/admin/courses', headers=admin, json={'title': '  '}).status_code == 422
    assert client.delete(url, headers=admin).status_code == 204
    assert client.get(f'/api/courses/{cid}', headers=alice).status_code == 404


def test_restricted_course_checks_grant_on_every_media_request(client):
    admin, alice, bob = [login(client, name) for name in ('manager', 'alice', 'bob')]
    alice_id = client.get('/api/me', headers=alice).json()['id']
    admin_id = client.get('/api/me', headers=admin).json()['id']
    cid, lid = create(client, admin, published=True, live=True, access='restricted')
    access = f'/api/admin/courses/{cid}/access'
    detail = f'/api/courses/{cid}'
    assert client.get(detail, headers=alice).status_code == 404
    response = client.get(access, headers=admin).json()
    assert response['mode'] == 'restricted'
    assert {user['username'] for user in response['learners']} == {'alice', 'bob'}
    assert client.get(access, headers=alice).status_code == 403
    assert client.put(access, headers=bob, json={'mode': 'all'}).status_code == 403
    assert client.put(access, headers=admin, json={'mode': 'restricted', 'learner_ids': [alice_id]}).status_code == 204
    assert client.put(access, headers=admin, json={'mode': 'restricted', 'learner_ids': [admin_id]}).status_code == 409
    assert client.put(access, headers=admin, json={'mode': 'restricted', 'learner_ids': [True]}).status_code == 422
    assert client.get(detail, headers=alice).status_code == 200
    assert 'access_mode' not in client.get(detail, headers=alice).json()
    assert client.get('/api/courses', headers=alice).json()[0]['id'] == cid
    assert client.get('/api/courses', headers=bob).json() == []
    assert client.get(detail, headers=bob).status_code == 404

    upload = f'/api/admin/courses/{cid}/lessons/{lid}/files'
    material = client.put(f'{upload}/material?name=notes.pdf', headers=admin, content=b'notes').json()['id']
    video = client.put(f'{upload}/video?name=lesson.mp4', headers=admin, content=b'1234ftypmp42').json()['id']
    from app.db import connect
    from app.services.courses import file_root
    media_paths = [(f'files/{material}', b'notes'), (f'files/{video}', b'1234ftypmp42')]
    with connect() as db:
        for status, bid in [('recording', '1' * 32), ('ready', '2' * 32)]:
            db.execute('INSERT INTO course_broadcasts VALUES (?,?,?,?,?)', (bid, lid, time.time(), time.time() + 300, status))
            path = file_root() / 'live' / bid
            path.mkdir(parents=True)
            manifest = b'#EXTM3U\n#EXTINF:2.0,\nsegment-000000.ts\n'
            if status == 'ready':
                manifest += b'#EXT-X-ENDLIST\n'
            (path / 'index.m3u8').write_bytes(manifest)
            (path / 'segment-000000.ts').write_bytes(b'video segment')
            media_paths.extend([(f'live/{bid}/index.m3u8', manifest),
                                (f'live/{bid}/segment-000000.ts', b'video segment')])
    for viewer, expected in [(alice, 200), (bob, 404), (admin, 200)]:
        media_cookie(client, viewer)
        for path, body in media_paths:
            response = client.get(f'/api/course-media/{cid}/{path}')
            assert response.status_code == expected
            if expected == 200:
                assert response.content == body
    media_cookie(client, alice)
    # The existing session and media cookie stop working as soon as the grant is removed.
    assert client.put(access, headers=admin, json={'mode': 'restricted', 'learner_ids': []}).status_code == 204
    assert client.get(detail, headers=alice).status_code == 404
    for path, _ in media_paths:
        assert client.get(f'/api/course-media/{cid}/{path}').status_code == 404


def test_visibility_modes_survive_metadata_changes_and_v26_upgrade(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    from app.db import connect, initialize, SCHEMA_VERSION
    cid, _ = create(client, admin, published=True, access='restricted')
    with connect() as db:
        db.execute('DROP TABLE course_learners')
        db.execute('ALTER TABLE courses DROP COLUMN access_mode')
        db.execute('PRAGMA user_version=26')
    initialize()
    detail = f'/api/courses/{cid}'
    url = f'/api/admin/courses/{cid}'
    assert client.get(detail, headers=alice).status_code == 200
    assert client.get(f'{url}/access', headers=admin).json()['mode'] == 'all'
    aid = client.get('/api/me', headers=alice).json()['id']
    data = {'mode': 'restricted', 'learner_ids': [aid]}
    assert client.put(f'{url}/access', headers=admin, json=data).status_code == 204
    assert client.put(url, headers=admin, json={'title': '修改标题', 'published': False}).status_code == 200
    assert client.get(detail, headers=alice).status_code == 404
    assert client.put(url, headers=admin, json={'title': '修改标题', 'published': True}).status_code == 200
    initialize()
    assert client.get(detail, headers=alice).status_code == 200
    assert client.get(f'{url}/access', headers=admin).json()['mode'] == 'restricted'
    with connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
    assert client.delete(f'/api/admin/users/{aid}', headers=admin).status_code == 204
    with connect() as db:
        assert not db.execute('SELECT 1 FROM course_learners WHERE user_id=?', (aid,)).fetchone()


def test_lesson_order_schedule_validation_and_retention(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    cid, lid = create(client, admin, published=True)
    url = f'/api/admin/courses/{cid}/lessons'
    second = client.post(url, headers=admin, json={'title': '第一课', 'position': 1})
    assert second.status_code == 201
    result = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons']
    assert [row['title'] for row in result] == ['第一课', '线性表']
    start = time.time() + 100
    for payload in ({'live_start': start}, {'live_start': start, 'live_end': start - 1},
                    {'live_start': start, 'live_end': start + 999999}):
        assert client.put(f'{url}/{lid}', headers=admin, json={'title': 'invalid', **payload}).status_code == 422
    response = client.put(f'{url}/{lid}', headers=admin,
                          json={'title': '栈', 'position': 1, 'live_start': start, 'live_end': start + 600})
    assert response.status_code == 200
    lesson = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]
    assert lesson['live_state'] == 'scheduled'
    from app.db import initialize
    initialize()
    assert client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]['title'] == '栈'
    assert client.delete(f'{url}/{lid}', headers=admin).status_code == 204


def test_upload_download_range_and_private_drafts(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    cid, lid = create(client, admin)
    url = f'/api/admin/courses/{cid}/lessons/{lid}/files'
    assert client.put(f'{url}/material?name=a.pdf', headers=alice, content=b'pdf').status_code == 403
    assert client.put(f'{url}/video?name=a.mp4', headers=admin, content=b'not video').status_code == 415
    assert client.put(f'{url}/video?name=a.html', headers=admin, content=b'x').status_code == 415
    assert client.put(f'{url}/material?name=a.pdf', headers=admin, content=b'').status_code == 400
    uploaded = client.put(f'{url}/material', params={'name': '../课件.pdf'}, headers=admin, content=b'%PDF-lesson')
    assert uploaded.status_code == 201, uploaded.text
    fid = uploaded.json()['id']
    path = f'/api/course-media/{cid}/files/{fid}'
    assert client.get(path).status_code == 401
    media_cookie(client, alice)
    assert client.get(path).status_code == 404
    media_cookie(client, admin)
    download = client.get(path)
    assert download.content == b'%PDF-lesson'
    assert "attachment;" in download.headers['content-disposition']
    assert 'nosniff' == download.headers['x-content-type-options']
    video = b'\x00\x00\x00\x18ftypmp42' + bytes(100)
    saved = client.put(f'{url}/video?name=a.mp4', headers=admin, content=video)
    assert saved.status_code == 201, saved.text
    response = client.get(f"/api/course-media/{cid}/files/{saved.json()['id']}", headers={'Range': 'bytes=0-11'})
    assert response.status_code == 206 and len(response.content) == 12
    client.put(f'/api/admin/courses/{cid}', headers=admin, json={'title': '发布课程', 'published': True})
    media_cookie(client, alice)
    assert client.get(path).status_code == 200
    client.post('/api/logout', headers=alice)
    assert client.get(path).status_code == 401
    assert client.delete(f'{url}/{fid}', headers=admin).status_code == 204
    from app.services.courses import file_root
    assert not (file_root() / 'files' / fid).exists()


def test_upload_limit_cleans_up_and_cross_course_files_hidden(client, monkeypatch):
    admin = login(client, 'manager')
    cid, lid = create(client, admin, published=True)
    other, _ = create(client, admin, published=True)
    from app.routes import courses
    original = courses.load_config
    monkeypatch.setattr(courses, 'load_config', lambda: {**original(), 'courses': {
        **original()['courses'], 'max_material_mb': 1}})
    url = f'/api/admin/courses/{cid}/lessons/{lid}/files/material?name=notes.pdf'
    assert client.put(url, headers=admin, content=b'X' * (1048576 + 1)).status_code == 413
    fid = client.put(url, headers=admin, content=b'X').json()['id']
    media_cookie(client, admin)
    assert client.get(f'/api/course-media/{other}/files/{fid}').status_code == 404
    from app.services.courses import file_root
    assert len(list((file_root() / 'files').iterdir())) == 1
    assert client.delete(f'/api/admin/courses/{cid}', headers=admin).status_code == 204
    assert not list((file_root() / 'files').iterdir())


def test_live_time_authorization_and_single_broadcast_lock(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    cid, lid = create(client, admin, published=True, live=True)
    from app.services.courses import reserve_broadcast, file_root, finish_broadcast
    from fastapi import HTTPException
    token = admin['Authorization'][7:]
    with pytest.raises(HTTPException) as failure:
        reserve_broadcast(cid, lid, alice['Authorization'][7:])
    assert failure.value.status_code == 403
    bid, *_ = reserve_broadcast(cid, lid, token)
    with pytest.raises(HTTPException) as failure:
        reserve_broadcast(cid, lid, token)
    assert failure.value.status_code == 409
    assert client.delete(f'/api/admin/courses/{cid}', headers=admin).status_code == 409
    assert client.put(f'/api/admin/courses/{cid}', headers=admin, json={'title': '下架'}).status_code == 409
    finish_broadcast(bid, file_root())
    assert client.delete(f'/api/admin/courses/{cid}', headers=admin).status_code == 204
    cid, lid = create(client, admin, published=True)
    with pytest.raises(HTTPException) as failure:
        reserve_broadcast(cid, lid, token)
    assert failure.value.status_code == 409


@pytest.mark.parametrize('disconnect', [False, True])
def test_actual_live_stream_is_readable_before_ending_and_becomes_replay(client, tmp_path, disconnect):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    cid, lid = create(client, admin, published=True, live=True)
    source = tmp_path / 'broadcast.webm'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '9', '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '5',
                    '-g', '24', '-c:a', 'libopus', str(source)], check=True, timeout=30)
    media_cookie(client, admin)
    url = f'/api/course-media/{cid}/lessons/{lid}/publish'
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url, headers={'Origin': 'https://evil.example'}):
            pass
    with client.websocket_connect(url, headers={'Origin': 'http://testserver'}) as socket:
        assert socket.receive_json()['ready']
        data = source.read_bytes()
        for start in range(0, len(data), 32000):
            socket.send_bytes(data[start:start + 32000])
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            detail = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]
            if detail['live_state'] == 'live':
                break
            time.sleep(0.1)
        assert detail['live_state'] == 'live', detail
        bid = detail['live_id']
        playlist = client.get(f'/api/course-media/{cid}/live/{bid}/index.m3u8')
        assert playlist.status_code == 200 and '#EXTINF:' in playlist.text
        assert '#EXT-X-ENDLIST' not in playlist.text
        if not disconnect:
            socket.send_text('finish')
            assert socket.receive_json() == {'finished': True, 'replay_saved': True}
        else:
            socket.close()
        deadline = time.monotonic() + 12
        while True:
            detail = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]
            if detail['replays'] or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    assert detail['replays'], detail
    assert detail['replays'][0]['id'] == bid
    media_cookie(client, alice)
    playlist = client.get(f'/api/course-media/{cid}/live/{bid}/index.m3u8')
    assert '#EXT-X-ENDLIST' in playlist.text
    segment = next(line for line in playlist.text.splitlines() if line.endswith('.ts'))
    assert client.get(f'/api/course-media/{cid}/live/{bid}/{segment}').content
    assert client.get(f'/api/course-media/{cid}/live/{bid}/raw.webm').status_code == 404
    assert client.delete(f'/api/admin/courses/{cid}/lessons/{lid}/replays/{bid}', headers=admin).status_code == 204
    assert client.get(f'/api/course-media/{cid}/live/{bid}/index.m3u8').status_code == 404


def test_orphaned_broadcast_recovers_and_failed_stream_is_not_replay(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    cid, lid = create(client, admin, published=True, live=True)
    from app.db import connect
    from app.services.courses import file_root
    with connect() as db:
        db.execute("INSERT INTO course_broadcasts VALUES (?,?,?,?,'recording')", ('a' * 32, lid, time.time()-60, 0))
    directory = file_root() / 'live' / ('a' * 32)
    directory.mkdir(parents=True)
    (directory / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:2.0,\nsegment-000000.ts\n')
    row = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]
    assert len(row['replays']) == 1
    with connect() as db:
        db.execute("INSERT INTO course_broadcasts VALUES (?,?,?,?,'recording')", ('b' * 32, lid, time.time(), 0))
    row = client.get(f'/api/courses/{cid}', headers=alice).json()['lessons'][0]
    assert len(row['replays']) == 1 and row['last_live_failed']
