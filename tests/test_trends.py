"""Current AI trend reports are refreshed in place without historical archives."""
import time
from datetime import date, datetime, timedelta

from test_system import client, login


def test_period_windows_use_local_calendar_and_reject_invalid_keys():
    from fastapi import HTTPException
    from app.services.trends import period_window

    assert period_window('week', today=date(2026, 11, 16)) == ('2026-W47', '2026-11-16', '2026-11-17')
    assert period_window('month', today=date(2026, 11, 16)) == ('2026-11', '2026-11-01', '2026-11-17')
    try:
        period_window('day', '2026-13-90', today=date(2026, 11, 16))
    except HTTPException as error:
        assert error.status_code == 422
    else:
        raise AssertionError('invalid date was accepted')


def test_trends_require_login_and_admin_access_for_generation(client):
    assert client.get('/api/trends/current').status_code == 401
    assert client.get('/api/trends/daily').status_code == 404
    alice = login(client, 'alice')
    assert client.get('/api/trends/current', headers=alice).status_code == 200
    assert client.post('/api/admin/trends/generate', headers=alice,
                       json={'period': 'week'}).status_code == 403


def test_daily_trends_are_not_available(client):
    admin = login(client, 'manager')
    assert client.get('/api/trends/current?period=day', headers=admin).status_code == 422
    assert client.post('/api/admin/trends/generate', headers=admin,
                       json={'period': 'day'}).status_code == 422


def test_admin_generates_editable_markdown_with_retrieval_sources(client, monkeypatch):
    from app.services import trends, ai

    admin = login(client, 'manager')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [
        {'title': 'Agent paper', 'url': 'https://arxiv.org/abs/2601.12345',
         'published_at': '2026-11-16T10:00:00Z', 'source': 'arXiv', 'summary': 'Agent planning'}])
    captured = {}

    def generate(prompt, **kwargs):
        captured.update(prompt=prompt, **kwargs)
        return '# 本周趋势\n\nAgent planning.'

    monkeypatch.setattr(ai, 'chat', generate)
    response = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'week'})

    assert response.status_code == 201
    trend = response.json()
    assert trend['period'] == 'week'
    assert trend['period_key'] == trends.period_window('week')[0]
    assert trend['body_markdown'] == '# 本周趋势\n\nAgent planning.'
    assert trend['body_html'].startswith('<h1>本周趋势</h1>')
    assert trend['sources'][0]['url'] == 'https://arxiv.org/abs/2601.12345'
    assert trend['generated_at'] <= time.time()
    assert captured['model'] == 'qwen3.7-plus'
    assert captured['request_timeout_seconds'] == 300
    assert 'https://arxiv.org/abs/2601.12345' in captured['prompt']
    assert '最具影响力的前沿科技进展' in captured['prompt']
    assert '突破性或里程碑式论文' in captured['prompt']
    assert '普通维护' in captured['prompt']
    assert '不是硬性筛选条件' in captured['prompt']


def test_trend_generation_uses_admin_model_settings(client, monkeypatch):
    from app.services import trends, ai

    admin = login(client, 'manager')
    updated = client.patch('/api/admin/model-settings', headers=admin, json={
        'trends': {'base_url': 'https://relay.example.test/v1', 'model': 'gpt-6.1-sol'},
    })
    assert updated.status_code == 200
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [
        {'title': 'Evidence', 'url': 'https://example.test/source', 'published_at': '',
         'source': 'Example', 'summary': 'Evidence summary'}])
    captured = {}

    def generate(prompt, **kwargs):
        captured.update(kwargs)
        return 'Generated report'

    monkeypatch.setattr(ai, 'chat', generate)
    response = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'week'})

    assert response.status_code == 201
    assert captured['model'] == 'gpt-6.1-sol'
    assert captured['request_timeout_seconds'] == 300


def test_trend_generation_normalizes_llm_emphasis_for_commonmark(client, monkeypatch):
    from app.services import trends, ai

    admin = login(client, 'manager')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [
        {'title': 'Evidence', 'url': 'https://example.test/source', 'published_at': '',
         'source': 'Example', 'summary': 'Evidence summary'}])
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs:
                        '**进展与价值：**内容\n\n```text\n**保留：**原样\n```')

    response = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'week'})

    assert response.status_code == 201
    trend = response.json()
    assert '**进展与价值：** 内容' in trend['body_markdown']
    assert '<strong>进展与价值：</strong> 内容' in trend['body_html']
    assert '**保留：**原样' in trend['body_markdown']


def test_regeneration_replaces_old_report_for_the_same_period(client, monkeypatch):
    from app.db import connect
    from app.services import trends, ai
    from app.services.trends import SHANGHAI

    admin, alice = login(client, 'manager'), login(client, 'alice')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [])
    bodies = iter(['First report', 'Replacement report'])
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: next(bodies))

    first = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'week'}).json()
    second = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'week'}).json()
    current = client.get('/api/trends/current?period=week', headers=alice).json()['item']

    assert second['id'] != first['id']
    assert current['id'] == second['id']
    assert current['body_markdown'] == 'Replacement report'
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM ai_trends WHERE period='week'").fetchone()[0] == 1


def test_public_current_period_does_not_label_a_past_report_as_today(client, monkeypatch):
    from app.db import connect
    from app.services import trends, ai
    from app.services.trends import SHANGHAI

    admin, alice = login(client, 'manager'), login(client, 'alice')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [])
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: 'Past report')
    today = datetime.now(SHANGHAI).date()
    yesterday = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    with connect() as db:
        _, start, end = trends.period_window('month', yesterday, today=today)
        db.execute('''INSERT INTO ai_trends(period,period_key,period_start,period_end,title,body_markdown,sources,
            generated_at,updated_at,updated_by) VALUES ('month',?,?,?,?,?,?,?,?,?)''',
            (yesterday, start, end, 'Past', 'Past report', '[]', time.time(), time.time(), 1))
    assert client.get('/api/trends/current?period=month', headers=alice).json()['item'] is None
    refreshed = client.post('/api/admin/trends/generate', headers=admin, json={'period': 'month'}).json()
    assert refreshed['period_key'] == trends.period_window('month')[0]
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM ai_trends WHERE period='month'").fetchone()[0] == 1


def test_admin_can_edit_markdown_without_changing_generated_evidence(client, monkeypatch):
    from app.services import trends, ai

    admin, alice = login(client, 'manager'), login(client, 'alice')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [
        {'title': 'Repo', 'url': 'https://github.com/example/repo', 'published_at': '',
         'source': 'GitHub', 'summary': 'An open source project'}])
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: 'Generated')
    generated = client.post('/api/admin/trends/generate', headers=admin,
                            json={'period': 'week'}).json()

    edited = client.patch(f"/api/admin/trends/{generated['id']}", headers=admin,
                          json={'body_markdown': '# Reviewed\n\n[Source](javascript:alert(1))'})
    assert edited.status_code == 422
    edited = client.patch(f"/api/admin/trends/{generated['id']}", headers=admin,
                          json={'body_markdown': '# Reviewed\n\nUpdated by editor.'})
    assert edited.status_code == 200
    assert edited.json()['sources'][0]['title'] == 'Repo'
    assert edited.json()['body_html'].startswith('<h1>Reviewed</h1>')
    assert client.patch(f"/api/admin/trends/{generated['id']}", headers=alice,
                        json={'body_markdown': 'forbidden'}).status_code == 403


def test_admin_can_generate_and_edit_each_trend_period(client, monkeypatch):
    from app.services import trends, ai

    admin, alice = login(client, 'manager'), login(client, 'alice')
    monkeypatch.setattr(trends, 'collect_sources', lambda period, start, end: [])
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '# Generated report')

    for period in ('week', 'month', 'year'):
        generated = client.post('/api/admin/trends/generate', headers=admin,
                                json={'period': period})
        assert generated.status_code == 201
        item = generated.json()
        assert item['period'] == period

        edited = client.patch(f"/api/admin/trends/{item['id']}", headers=admin,
                              json={'body_markdown': f'# Reviewed {period}'})
        assert edited.status_code == 200
        assert edited.json()['body_markdown'] == f'# Reviewed {period}'
        assert client.get('/api/trends/current', params={'period': period},
                          headers=alice).json()['item']['id'] == item['id']


def test_daily_refresh_schedule_uses_shanghai_time():
    from datetime import datetime
    from app.services.trend_scheduler import next_refresh
    from app.services.trends import SHANGHAI

    before = datetime(2026, 11, 16, 5, 59, tzinfo=SHANGHAI)
    after = datetime(2026, 11, 16, 6, 0, tzinfo=SHANGHAI)
    assert next_refresh(before, '06:00') == datetime(2026, 11, 16, 6, 0, tzinfo=SHANGHAI)
    assert next_refresh(after, '06:00') == datetime(2026, 11, 17, 6, 0, tzinfo=SHANGHAI)


def test_refresh_worker_attempts_each_period_even_when_one_fails(client, monkeypatch):
    from app.services import trend_scheduler, trends

    attempted = []

    def generate(db, actor_id, *, period):
        attempted.append(period)
        if period == 'week':
            raise RuntimeError('temporary failure')
        return {'period_key': period}

    monkeypatch.setattr(trends, 'generate', generate)
    failed = trend_scheduler.refresh_all()
    assert attempted == ['week', 'month', 'year']
    assert failed == ['week']


def test_trend_initialization_cleans_old_records_and_keeps_latest_per_period(client):
    import time as time_module
    from app.db import connect
    from app.services.trends import initialize

    with connect() as db:
        for key, title in [('2026-11-14', 'Older'), ('2026-11-15', 'Newer')]:
            db.execute('''INSERT INTO ai_trends(period,period_key,period_start,period_end,title,body_markdown,sources,
                generated_at,updated_at) VALUES ('day',?,?,?,?,?,?,?,?)''',
                (key, key, key, title, title, '[]', time_module.time(), time_module.time()))
        initialize(db)
        rows = list(db.execute("SELECT title FROM ai_trends WHERE period='day'"))
    assert [row['title'] for row in rows] == ['Newer']
