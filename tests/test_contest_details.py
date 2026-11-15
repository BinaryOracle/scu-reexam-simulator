"""Contest editing, complete public samples and safe statement presentation."""
import time

from test_system import client, login


def make_contest(client, manager):
    now = time.time()
    payload = {'title': '模拟赛', 'starts': now - 60, 'ends': now + 3600,
               'problems': [{'title': '画画', 'statement': '**题意**：$n \\le 50$',
                             'remote_problem_id': 'P4708',
                             'samples': [{'input': '4', 'output': '3'}, {'input': '5', 'output': '7'}]}]}
    response = client.post('/api/admin/contests', headers=manager, json=payload)
    assert response.status_code == 200, response.text
    return response.json(), payload


def test_edit_contest_retains_existing_problem_and_submission_ids(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    created, payload = make_contest(client, manager)
    cid, pid = created['id'], created['problem_ids'][0]
    sid = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source': 'print(3)'}).json()['id']
    payload.update(title='修改后的比赛', ends=payload['ends'] + 600)
    payload['problems'][0]['id'] = pid
    assert client.put(f'/api/admin/contests/{cid}', headers=alice, json=payload).status_code == 403
    saved = client.put(f'/api/admin/contests/{cid}', headers=manager, json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()['problem_ids'] == [pid]
    assert client.get('/api/contests', headers=alice).json()[0]['title'] == '修改后的比赛'
    assert client.get('/api/submissions', headers=alice).json()['items'][0]['id'] == sid


def test_edit_contest_rejects_empty_invalid_times_and_submitted_problem_removal(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    created, payload = make_contest(client, manager)
    cid, pid = created['id'], created['problem_ids'][0]
    assert client.put(f'/api/admin/contests/{cid}', headers=manager, json={**payload, 'problems': []}).status_code == 422
    assert client.put(f'/api/admin/contests/{cid}', headers=manager, json={**payload, 'ends': payload['starts']}).status_code == 400
    assert client.put('/api/admin/contests/999999', headers=manager, json=payload).status_code == 404
    client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source': 'print(3)'})
    replacement = {**payload, 'title': '不应保存', 'problems': [dict(payload['problems'][0], remote_problem_id='P1000')]}
    assert client.put(f'/api/admin/contests/{cid}', headers=manager, json=replacement).status_code == 409
    assert client.get('/api/contests', headers=alice).json()[0]['title'] == '模拟赛'


def test_all_samples_and_rendered_statement_reach_admin_and_candidate(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    created, _ = make_contest(client, manager)
    for prefix, headers in [('/api/admin', manager), ('/api', alice)]:
        problem = client.get(f'{prefix}/contests/{created["id"]}/problems', headers=headers).json()[0]
        assert problem['samples'] == [{'input': '4', 'output': '3'}, {'input': '5', 'output': '7'}]
        assert '<strong>题意</strong>' in problem['statement_html']
        assert 'class="math inline"' in problem['statement_html']
        assert problem['remote_problem_id'] == 'P4708'
        assert 'tests' not in problem


def test_luogu_current_nested_content_and_all_samples(monkeypatch):
    from app.services import luogu_catalog
    monkeypatch.setattr(luogu_catalog, '_page', lambda *args: {'problem': {
        'pid': 'P4708', 'name': '画画', 'content': {'description': '**图** $n$', 'formatI': '一个整数'},
        'samples': [['4', '3'], ['5', '7']], 'limits': {'time': [1000], 'memory': [131072]}}})
    result = luogu_catalog.problem('p4708')
    assert '**图** $n$' in result['statement']
    assert result['samples'] == [{'input': '4', 'output': '3'}, {'input': '5', 'output': '7'}]
    assert result['sample_input'] == '4' and result['sample_output'] == '3'
    assert '<strong>图</strong>' in result['statement_html']
    assert '时间限制：1000 ms' in result['statement']
    assert '内存限制：128 MiB' in result['statement']


def test_luogu_resource_limits_collapse_repeated_values_and_keep_distinct_limits(monkeypatch):
    from app.services import luogu_catalog
    monkeypatch.setattr(luogu_catalog, '_page', lambda *args: {'problem': {
        'pid': 'P1000', 'name': 'A+B', 'content': {}, 'samples': [],
        'limits': {'time': [1000] * 24, 'memory': [131072] * 24}}})
    result = luogu_catalog.problem('P1000')
    assert '时间限制：1000 ms' in result['statement']
    assert '内存限制：128 MiB' in result['statement']
    assert '1000-1000' not in result['statement']

    monkeypatch.setattr(luogu_catalog, '_page', lambda *args: {'problem': {
        'pid': 'P1000', 'name': 'A+B', 'content': {}, 'samples': [],
        'limits': {'time': [1000, 2000, 1000], 'memory': [131072, 262144, 131072]}}})
    result = luogu_catalog.problem('P1000')
    assert '时间限制：1000-2000 ms' in result['statement']
    assert '内存限制：128-256 MiB' in result['statement']


def test_statement_html_and_math_cannot_execute_remote_markup():
    from app.services.problem_content import render_statement
    rendered = render_statement('## 描述\n\n**加粗**\n\n$n \\le 50$\n\n$$x^2$$\n\n<script>alert(1)</script>\n\n[恶意](javascript:alert(1))\n\n`$literal$`')
    assert '<h2>描述</h2>' in rendered and '<strong>加粗</strong>' in rendered
    assert 'class="math inline"' in rendered and 'class="math block"' in rendered
    assert '<script' not in rendered and 'href="javascript:' not in rendered
    assert '<code>$literal$</code>' in rendered


def test_refresh_existing_problem_repairs_samples_without_touching_submissions(client, monkeypatch):
    from app.services import luogu_catalog
    manager, alice = login(client, 'manager'), login(client, 'alice')
    created, _ = make_contest(client, manager)
    pid = created['problem_ids'][0]
    sid = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source': 'print(3)'}).json()['id']
    monkeypatch.setattr(luogu_catalog, 'problem', lambda value: {
        'title': '画画', 'statement': '更新的描述', 'sample_input': '4', 'sample_output': '3',
        'samples': [{'input': '4', 'output': '3'}, {'input': '5', 'output': '7'}]})
    assert client.post(f'/api/admin/problems/{pid}/refresh', headers=alice).status_code == 403
    response = client.post(f'/api/admin/problems/{pid}/refresh', headers=manager)
    assert response.status_code == 200, response.text
    assert len(response.json()['samples']) == 2
    assert client.get('/api/submissions', headers=alice).json()['items'][0]['id'] == sid


def test_future_contest_overview_is_visible_but_statement_is_not(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    created, payload = make_contest(client, manager)
    payload['starts'] = time.time() + 600
    assert client.put(f'/api/admin/contests/{created["id"]}', headers=manager, json=payload).status_code == 200
    overview = client.get(f'/api/contests/{created["id"]}', headers=alice)
    assert overview.status_code == 200, overview.text
    assert overview.json()['problem_count'] == 1
    assert overview.json()['problems'][0]['title'] == '画画'
    assert 'statement' not in overview.json()['problems'][0]
    assert client.get(f'/api/contests/{created["id"]}/problems', headers=alice).status_code == 403


def test_existing_luogu_problem_displays_deduplicated_resource_limits():
    from app.services.problem_content import public_problem
    row = {'id': 1, 'title': 'A', 'statement': '## 资源限制：\n- 时间限制：1000-2000-1000 ms\n- 内存限制：128-128 MiB',
           'sample_input': '', 'sample_output': '', 'remote_problem_id': 'P1000', 'samples': '[]'}
    result = public_problem(row)
    assert '时间限制：1000-2000 ms' in result['statement_html']
    assert '内存限制：128 MiB' in result['statement_html']
    assert row['statement'].endswith('128-128 MiB')
