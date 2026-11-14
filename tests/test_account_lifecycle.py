"""In-flight presentation preparation cannot outlive its authenticated session."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest
from test_system import client, login
from test_presentations import deck_bytes


@pytest.mark.parametrize('invalidation', ['logout', 'password', 'expired', 'disabled', 'delete'])
def test_start_rechecks_session_after_presentation_preparation(client, monkeypatch, invalidation):
    from app.db import connect
    from app.services import presentations

    headers = login(client, 'alice')
    uid = client.get('/api/me', headers=headers).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET interview_credits=3 WHERE id=?', (uid,))

    prepared_ready, release = threading.Event(), threading.Event()
    directories = []
    prepare = presentations.prepare

    def paused_prepare(content, name):
        prepared = prepare(content, name)
        directories.append(Path(prepared['directory']))
        prepared_ready.set()
        assert release.wait(timeout=10)
        return prepared

    monkeypatch.setattr(presentations, 'prepare', paused_prepare)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, '/api/interviews/start', headers=headers,
                              files={'file': ('intro.pdf', deck_bytes(), 'application/pdf')})
        try:
            assert prepared_ready.wait(timeout=10)
            assert directories[0].is_dir()
            if invalidation == 'logout':
                assert client.post('/api/logout', headers=headers).status_code == 204
            elif invalidation == 'password':
                assert client.post('/api/profile/password', headers=headers,
                    json={'current_password': 'password123', 'password': 'changed'}).status_code == 200
            elif invalidation == 'delete':
                assert client.request('DELETE', '/api/profile/account', headers=headers,
                    json={'current_password': 'password123'}).status_code == 204
            else:
                with connect() as db:
                    if invalidation == 'expired':
                        db.execute('UPDATE sessions SET expires=? WHERE token=?',
                                   (time.time() - 1, headers['Authorization'][7:]))
                    else:
                        db.execute('UPDATE users SET is_active=0 WHERE id=?', (uid,))
        finally:
            release.set()
        response = pending.result(timeout=10)

    assert response.status_code == 401, response.text
    assert '重新登录' in response.json()['detail']
    assert not directories[0].exists()
    with connect() as db:
        for table in ('interviews', 'answers', 'presentations'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert not db.execute("SELECT 1 FROM credit_ledger WHERE kind='interview'").fetchone()
        account = db.execute('SELECT interview_credits FROM users WHERE id=?', (uid,)).fetchone()
        assert account is None if invalidation == 'delete' else account['interview_credits'] == 3
