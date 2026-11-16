from test_system import client, login


def create_course(client):
    admin = login(client, 'manager')
    alice = login(client, 'alice')
    uid = client.get('/api/me', headers=alice).json()['id']
    response = client.post('/api/live/courses', headers=admin, json={
        'title': '直播课程', 'host_id': uid, 'member_ids': [uid]})
    assert response.status_code == 200, response.text
    return admin, alice, response.json()['id']


def test_membership_host_and_unconfigured_media(client):
    admin, alice, cid = create_course(client)
    bob = login(client, 'bob')
    assert client.get(f'/api/live/courses/{cid}', headers=bob).status_code == 404
    lesson = client.post(f'/api/live/courses/{cid}/lessons', headers=admin,
                         json={'title': '第一课', 'starts_at': 1}).json()
    assert client.post(f"/api/live/lessons/{lesson['id']}/start", headers=admin).status_code == 403
    assert client.post(f"/api/live/lessons/{lesson['id']}/start", headers=alice).status_code == 503
    assert client.get('/api/live/courses', headers=alice).json()['items'][0]['id'] == cid


def test_private_material_and_forbidden_types(client):
    admin, alice, cid = create_course(client)
    lesson = client.post(f'/api/live/courses/{cid}/lessons', headers=admin,
                         json={'title': '资料课', 'starts_at': 1}).json()
    url = f"/api/live/lessons/{lesson['id']}/materials"
    assert client.post(url, headers=alice, files={'file': ('bad.html', b'<script>', 'text/html')}).status_code == 422
    response = client.post(url, headers=alice, files={'file': ('notes.txt', b'hello', 'text/plain')})
    assert response.status_code == 200, response.text
    file_url = f"/api/live/materials/{response.json()['id']}/file"
    assert client.get(file_url).status_code == 401
    assert client.get(file_url, headers=login(client, 'bob')).status_code == 404
    assert client.get(file_url, headers=alice).content == b'hello'


def configured(monkeypatch):
    from app.services import live_media as media
    original = media.settings
    monkeypatch.setattr(media, 'settings', lambda: {**original(), 'url': 'wss://live.example.test',
        'api_url': 'https://live.example.test', 'recording_enabled': True})
    monkeypatch.setenv('LIVEKIT_API_KEY', 'test-key')
    monkeypatch.setenv('LIVEKIT_API_SECRET', 'a' * 32)
    calls = []
    async def call(service, method, request):
        from types import SimpleNamespace
        calls.append((service, method, request))
        return SimpleNamespace(egress_id='EG_test')
    monkeypatch.setattr(media, 'call', call)
    return calls


def active_lesson(client, monkeypatch):
    calls = configured(monkeypatch)
    admin, alice, cid = create_course(client)
    lid = client.post(f'/api/live/courses/{cid}/lessons', headers=admin,
                     json={'title': '互动课', 'starts_at': 1}).json()['id']
    assert client.post(f'/api/live/lessons/{lid}/start', headers=alice).status_code == 200
    assert client.post(f'/api/live/lessons/{lid}/join', headers=alice).status_code == 200
    return admin, alice, cid, lid, calls


def test_join_token_room_grants_presence_chat_and_end(client, monkeypatch):
    import jwt
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    token = client.post(f'/api/live/lessons/{lid}/join', headers=alice).json()['token']
    claims = jwt.decode(token, 'a' * 32, algorithms=['HS256'], options={'verify_aud': False})
    assert claims['video']['room'] == f'classroom-{lid}'
    assert claims['video']['canPublishSources'] == ['microphone', 'camera']
    assert claims['video']['canPublishData'] is False
    assert claims['exp'] - claims['nbf'] <= 120
    base = f'/api/live/lessons/{lid}'
    assert client.post(base + '/presence', headers=alice, json={'hand': True}).json()['members'][0]['hand'] is True
    message = client.post(base + '/messages', headers=alice, json={'content': 'hello'})
    assert message.status_code == 200
    assert client.get(base + '/state?after=' + str(message.json()['id']), headers=alice).json()['messages'] == []
    assert client.post(base + '/like', headers=alice).json()['likes'] == 1
    assert client.post(base + '/end', headers=alice).json()['status'] == 'ended'
    assert client.post(base + '/join', headers=alice).status_code == 409
    assert client.post(base + '/start', headers=alice).status_code == 409
    assert calls[-1][1] == 'delete_room'


def test_capacity_reconnect_and_permission_revocation(client, monkeypatch):
    from app.db import connect
    from app.services import live_media as media
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    bob = login(client, 'bob')
    bob_id = client.get('/api/me', headers=bob).json()['id']
    alice_id = client.get('/api/me', headers=alice).json()['id']
    with connect() as db:
        db.execute('INSERT INTO live_members VALUES (?,?)', (cid, bob_id))
    original = media.settings
    monkeypatch.setattr(media, 'settings', lambda: {**original(), 'max_participants': 1})
    base = f'/api/live/lessons/{lid}'
    assert client.post(base + '/join', headers=alice).status_code == 200
    assert client.post(base + '/join', headers=bob).status_code == 409
    monkeypatch.setattr(media, 'settings', original)
    assert client.post(base + '/join', headers=bob).json()['can_speak'] is False
    assert client.patch(base + f'/members/{alice_id}', headers=bob, json={'can_share': True}).status_code == 403
    assert client.patch(base + f'/members/{bob_id}', headers=alice, json={'can_speak': True, 'can_share': True}).status_code == 200
    permission = calls[-1][2].permission
    assert permission.can_publish and len(permission.can_publish_sources) == 4
    assert client.patch(base + f'/members/{alice_id}', headers=alice, json={'can_share': True}).status_code == 200
    assert calls[-2][2].identity == str(bob_id)
    assert list(calls[-2][2].permission.can_publish_sources) == [2, 1]
    assert client.patch(base + f'/members/{bob_id}', headers=alice, json={'can_speak': False, 'muted': True}).status_code == 200
    assert not calls[-1][2].permission.can_publish
    assert client.post(base + '/messages', headers=bob, json={'content': 'blocked'}).status_code == 403
    assert client.post(base + '/leave', headers=bob).status_code == 200
    assert calls[-1][1] == 'remove_participant'
    assert len(client.get(base + '/state', headers=alice).json()['members']) == 1


def test_people_admin_isolation_and_live_roster_freeze(client, monkeypatch):
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    people = client.get('/api/live/people', headers=admin).json()
    assert 'root' not in [person['username'] for person in people]
    assert 'manager' in [person['username'] for person in people]
    assert client.get('/api/live/people', headers=alice).status_code == 403
    with __import__('app.db', fromlist=['connect']).connect() as db:
        root = db.execute("SELECT id FROM users WHERE username='root'").fetchone()[0]
    assert client.post('/api/live/courses', headers=admin, json={'title': 'bad', 'host_id': root}).status_code == 404
    assert client.patch(f'/api/live/courses/{cid}', headers=admin,
        json={'title': 'frozen', 'host_id': client.get('/api/me', headers=alice).json()['id']}).status_code == 409
    assert client.delete(f'/api/live/lessons/{lid}', headers=admin).status_code == 409


def test_recording_signed_webhook_ticket_and_membership_recheck(client, monkeypatch):
    import base64
    import hashlib
    import json
    import time
    from livekit import api
    from app.db import connect
    from app.routes.live import private_path
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    base = f'/api/live/lessons/{lid}'
    assert client.post(base + '/recording', headers=alice, json={'action': 'start'}).json()['status'] == 'starting'
    assert client.post(base + '/recording', headers=alice, json={'action': 'start'}).json()['status'] == 'starting'
    assert len([call for call in calls if call[1] == 'start_room_composite_egress']) == 1
    with connect() as db:
        row = dict(db.execute('SELECT * FROM live_recordings').fetchone())
    path = private_path('recordings', row['path'])
    path.write_bytes(b'0123456789')
    body = json.dumps({'event': 'egress_ended', 'id': 'EV_1', 'createdAt': str(int(time.time())),
        'egressInfo': {'egressId': 'EG_test', 'status': 'EGRESS_COMPLETE',
            'fileResults': [{'filename': '/out/' + row['path'], 'size': '10'}]}})
    signature = (api.AccessToken('test-key', 'a' * 32).with_sha256(
        base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()).to_jwt())
    assert client.post('/api/live/webhook', content=body).status_code == 401
    for _ in range(2):
        response = client.post('/api/live/webhook', content=body, headers={'Authorization': signature})
        assert response.status_code == 200, response.text
    rid = row['id']
    ticket = client.post(f'/api/live/recordings/{rid}/playback', headers=alice).json()['url']
    assert client.get(ticket, headers={'Range': 'bytes=2-5'}).content == b'2345'
    assert client.get(f'/api/live/recordings/{rid}/file').status_code == 401
    with connect() as db:
        db.execute('UPDATE users SET is_active=0 WHERE id=?', (client.get('/api/me', headers=alice).json()['id'],))
    assert client.get(ticket).status_code == 401


def test_recording_failure_is_visible_not_fake_success(client, monkeypatch):
    from fastapi import HTTPException
    from app.services import live_media as media
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    async def fail(*args):
        raise HTTPException(502, 'Egress unavailable')
    monkeypatch.setattr(media, 'call', fail)
    assert client.post(f'/api/live/lessons/{lid}/recording', headers=alice, json={'action': 'start'}).status_code == 502
    lesson = client.get(f'/api/live/lessons/{lid}', headers=alice).json()
    assert lesson['recording_status'] == 'unknown'
    assert lesson['recordings'][0]['error']
    assert client.post(f"/api/live/recordings/{lesson['recordings'][0]['id']}/playback", headers=alice).status_code == 409


def test_permission_failure_does_not_publish_grant(client, monkeypatch):
    from fastapi import HTTPException
    from app.services import live_media as media
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    uid = client.get('/api/me', headers=alice).json()['id']
    async def fail(*args):
        raise HTTPException(502, 'SFU unavailable')
    monkeypatch.setattr(media, 'permission', fail)
    assert client.patch(f'/api/live/lessons/{lid}/members/{uid}', headers=alice,
                        json={'can_share': True}).status_code == 502
    assert not client.get(f'/api/live/lessons/{lid}/state', headers=alice).json()['members'][0]['can_share']


def test_config_rejects_inline_credentials_and_unbounded_limits():
    import pytest
    from app.config import _live_config
    for value in ({'api_key': 'secret'}, {'max_participants': 51}, {'token_seconds': 301}, {'presence_seconds': 14},
                  {'url': 'https://wrong'}, {'api_url': 'https://user:secret@example.test'}):
        with pytest.raises(ValueError):
            _live_config({'live': value})


def test_screen_sharing_defaults_are_bounded_and_overridable():
    import pytest
    from app.config import _live_config
    config = {'live': {}}
    _live_config(config)
    assert config['live']['screen_share_frame_rate'] == 15
    assert config['live']['screen_share_width'] == 1280
    for value in ({'screen_share_width': 4000}, {'screen_share_height': 2160},
                  {'screen_share_frame_rate': 60}, {'screen_share_max_bitrate': 0}):
        with pytest.raises(ValueError):
            _live_config({'live': value})


def test_presence_expiry_evicts_before_readmission(client, monkeypatch):
    from app.db import connect
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    with connect() as db:
        db.execute('UPDATE live_presence SET seen=0 WHERE lesson_id=?', (lid,))
    assert client.post(f'/api/live/lessons/{lid}/presence', headers=alice, json={}).status_code == 409
    assert client.post(f'/api/live/lessons/{lid}/join', headers=alice).status_code == 200
    assert calls[-1][1] == 'remove_participant'


def test_failed_webhook_file_missing_remains_unplayable(client, monkeypatch):
    import base64, hashlib, json, time
    from livekit import api
    from app.db import connect
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    client.post(f'/api/live/lessons/{lid}/recording', headers=alice, json={'action': 'start'})
    with connect() as db:
        row = dict(db.execute('SELECT * FROM live_recordings').fetchone())
    body = json.dumps({'event': 'egress_ended', 'id': 'EV_missing', 'createdAt': str(int(time.time())),
        'egressInfo': {'egressId': 'EG_test', 'status': 'EGRESS_COMPLETE',
        'fileResults': [{'filename': '/out/' + row['path'], 'size': '10'}]}})
    token = api.AccessToken('test-key', 'a' * 32).with_sha256(base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()).to_jwt()
    assert client.post('/api/live/webhook', content=body, headers={'Authorization': token}).status_code == 200
    lesson = client.get(f'/api/live/lessons/{lid}', headers=alice).json()
    assert lesson['recording_status'] == 'failed'
    assert '私有视频文件' in lesson['recordings'][0]['error']


def test_leave_after_sdk_disconnect_clears_reservation(client, monkeypatch):
    from app.services import live_media as media
    from livekit import api
    from fastapi import HTTPException
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    async def gone(*args):
        try:
            raise api.TwirpError('not_found', 'participant gone', status=404)
        except api.TwirpError as error:
            raise HTTPException(502, 'gone') from error
    monkeypatch.setattr(media, 'call', gone)
    assert client.post(f'/api/live/lessons/{lid}/leave', headers=alice).status_code == 200
    assert client.get(f'/api/live/lessons/{lid}/state', headers=alice).json()['members'] == []


def test_likes_are_rate_limited_per_user(client, monkeypatch):
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    url = f'/api/live/lessons/{lid}/like'
    assert client.post(url, headers=alice).status_code == 200
    assert client.post(url, headers=alice).status_code == 429
    assert client.get(f'/api/live/lessons/{lid}/state', headers=alice).json()['likes'] == 1


def test_deleted_course_removes_committed_private_files(client):
    from app.db import connect
    from app.routes.live import private_path
    admin, alice, cid = create_course(client)
    lid = client.post(f'/api/live/courses/{cid}/lessons', headers=admin, json={'title': 'delete', 'starts_at': 1}).json()['id']
    client.post(f'/api/live/lessons/{lid}/materials', headers=alice, files={'file': ('notes.txt', b'private', 'text/plain')})
    with connect() as db:
        name = db.execute('SELECT path FROM live_materials').fetchone()[0]
    path = private_path('materials', name)
    assert path.is_file()
    assert client.delete(f'/api/live/courses/{cid}', headers=admin).status_code == 200
    assert not path.exists()


def test_unknown_recording_reconcile_known_failed_allows_retry(client, monkeypatch):
    from types import SimpleNamespace
    from livekit import api
    from app.db import connect
    from app.services import live_media as media
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    client.post(f'/api/live/lessons/{lid}/recording', headers=alice, json={'action': 'start'})
    with connect() as db:
        row = dict(db.execute('SELECT * FROM live_recordings').fetchone())
        db.execute("UPDATE live_recordings SET status='unknown',egress_id=NULL")
    async def reconcile(service, method, request):
        return SimpleNamespace(items=[api.EgressInfo(egress_id='EG_recovered', status=api.EgressStatus.EGRESS_FAILED,
            error='renderer failed', room_composite=api.RoomCompositeEgressRequest(
                file_outputs=[api.EncodedFileOutput(filepath='/out/' + row['path'])]))])
    monkeypatch.setattr(media, 'call', reconcile)
    response = client.post(f'/api/live/lessons/{lid}/recording', headers=alice, json={'action': 'reconcile'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'failed'
    with connect() as db:
        assert db.execute('SELECT egress_id FROM live_recordings').fetchone()[0] == 'EG_recovered'


def test_share_transfer_failure_preserves_revocation_and_unique_index(client, monkeypatch):
    import sqlite3
    from app.db import connect
    from app.services import live_media as media
    from fastapi import HTTPException
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    uid = client.get('/api/me', headers=alice).json()['id']
    bob = login(client, 'bob')
    bid = client.get('/api/me', headers=bob).json()['id']
    with connect() as db:
        db.execute('INSERT INTO live_members VALUES (?,?)', (cid, bid))
    client.post(f'/api/live/lessons/{lid}/join', headers=bob)
    assert client.patch(f'/api/live/lessons/{lid}/members/{uid}', headers=alice, json={'can_share': True}).status_code == 200
    count = 0
    async def partial(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise HTTPException(502, 'grant failed')
    monkeypatch.setattr(media, 'permission', partial)
    assert client.patch(f'/api/live/lessons/{lid}/members/{bid}', headers=alice, json={'can_share': True}).status_code == 502
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_presence WHERE can_share=1').fetchone()[0] == 0
        db.execute('UPDATE live_presence SET can_share=1 WHERE user_id=?', (uid,))
        with __import__('pytest').raises(sqlite3.IntegrityError):
            db.execute('UPDATE live_presence SET can_share=1 WHERE user_id=?', (bid,))


def test_playback_expiry_and_fresh_membership_rejection(client, monkeypatch):
    import time
    from app.db import connect
    from app.routes.live import private_path
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    bob = login(client, 'bob')
    bid = client.get('/api/me', headers=bob).json()['id']
    private_path('recordings', 'ticket-test.mp4').write_bytes(b'video')
    with connect() as db:
        db.execute('INSERT INTO live_members VALUES (?,?)', (cid, bid))
        rid = db.execute("INSERT INTO live_recordings(lesson_id,status,path) VALUES (?,'ready','ticket-test.mp4')", (lid,)).lastrowid
    result = client.post(f'/api/live/recordings/{rid}/playback', headers=bob).json()
    assert result['expires_in'] == 14400
    assert result['expires_at'] > time.time() + 14390
    assert client.get(result['url']).status_code == 200
    with connect() as db:
        db.execute('DELETE FROM live_members WHERE course_id=? AND user_id=?', (cid, bid))
    assert client.get(result['url']).status_code == 404
    with connect() as db:
        db.execute('INSERT INTO live_members VALUES (?,?)', (cid, bid))
        db.execute('UPDATE live_playback SET expires=0')
    assert client.get(result['url']).status_code == 401
    assert client.post(f'/api/live/recordings/{rid}/playback', headers=bob).status_code == 200


def test_ended_lesson_host_can_reconcile_but_not_start_stop(client, monkeypatch):
    from types import SimpleNamespace
    from livekit import api
    from app.db import connect
    from app.services import live_media as media
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    client.post(f'/api/live/lessons/{lid}/recording', headers=alice, json={'action': 'start'})
    assert client.post(f'/api/live/lessons/{lid}/end', headers=alice).status_code == 200
    with connect() as db:
        db.execute("UPDATE live_recordings SET status='unknown'")
    async def list_tasks(*args):
        return SimpleNamespace(items=[api.EgressInfo(egress_id='EG_test', status=api.EgressStatus.EGRESS_FAILED)])
    monkeypatch.setattr(media, 'call', list_tasks)
    url = f'/api/live/lessons/{lid}/recording'
    assert client.post(url, headers=alice, json={'action': 'reconcile'}).json()['status'] == 'failed'
    assert client.post(url, headers=alice, json={'action': 'start'}).status_code == 409
    assert client.post(url, headers=alice, json={'action': 'stop'}).status_code == 409
    assert client.post(url, headers=admin, json={'action': 'reconcile'}).status_code == 403


def test_mute_survives_leave_and_expired_rejoin(client, monkeypatch):
    from app.db import connect
    admin, alice, cid, lid, calls = active_lesson(client, monkeypatch)
    bob = login(client, 'bob')
    bid = client.get('/api/me', headers=bob).json()['id']
    with connect() as db:
        db.execute('INSERT INTO live_members VALUES (?,?)', (cid, bid))
    base = f'/api/live/lessons/{lid}'
    client.post(base + '/join', headers=bob)
    assert client.patch(base + f'/members/{bid}', headers=alice, json={'muted': True}).status_code == 200
    assert client.post(base + '/leave', headers=bob).status_code == 200
    assert client.post(base + '/join', headers=bob).status_code == 200
    assert client.get(base + '/state', headers=bob).json()['muted'] is True
    assert client.post(base + '/messages', headers=bob, json={'content': 'bypass'}).status_code == 403
    with connect() as db:
        db.execute('UPDATE live_presence SET seen=0 WHERE lesson_id=? AND user_id=?', (lid, bid))
    assert client.post(base + '/join', headers=bob).status_code == 200
    assert client.post(base + '/messages', headers=bob, json={'content': 'still muted'}).status_code == 403
    assert client.patch(base + f'/members/{bid}', headers=alice, json={'muted': False}).status_code == 200
    assert client.post(base + '/messages', headers=bob, json={'content': 'allowed'}).status_code == 200
