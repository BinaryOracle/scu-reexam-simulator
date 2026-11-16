"""Coding practice ownership, moderation, fixed daily assignments and reward atomicity."""
from test_system import client, login


def test_home_requires_auth_and_does_not_assign_daily_question(client):
    alice = login(client, 'alice')
    assert client.get('/api/coding/home').status_code == 401
    response = client.get('/api/coding/home', headers=alice)
    assert response.status_code == 200, response.text
    assert response.json()['daily']['question_id'] is None
    assert response.json()['daily']['checked_in'] is False


def _stage(client, admin, title='练习阶段', position=0):
    result = client.post('/api/admin/coding/stages', headers=admin,
                         json={'title': title, 'description': '按主题学习', 'position': position})
    assert result.status_code == 201, result.text
    return result.json()


def _question(client, actor, stage, *, official=False, **fields):
    result = client.post('/api/' + ('admin/' if official else '') + 'coding/questions', headers=actor, json={
        'stage_id': stage['id'], 'title': '整数求和', 'statement': '输出两个整数的和。',
        'samples': [{'input': '1 2', 'output': '3'}], 'reference_code': 'print(sum(map(int,input().split())))',
        'reference_language': 'python3', 'judge_mode': 'samples', **fields})
    assert result.status_code == 201, result.text
    return result.json()


def _approve(client, owner, admin, question):
    pending = client.post(f"/api/coding/questions/{question['id']}/submit", headers=owner,
                          json={'version': question['version']})
    assert pending.status_code == 200, pending.text
    result = client.post(f"/api/admin/coding/questions/{question['id']}/review", headers=admin,
                         json={'version': pending.json()['version'], 'approve': True})
    assert result.status_code == 200, result.text
    return result.json()


def _judge(monkeypatch):
    from app.services import coding_judge
    monkeypatch.setattr(coding_judge, 'availability', lambda: {'available': True, 'languages': ['cpp11', 'c', 'python3'], 'notice': '公开样例评测'})
    monkeypatch.setattr(coding_judge, 'evaluate', lambda language, source, samples: {
        'status': 'Accepted', 'detail': '全部公开样例通过', 'passed_cases': len(samples), 'total_cases': len(samples)})


def _solve(client, actor, qid):
    result = client.post(f'/api/coding/questions/{qid}/submissions', headers=actor,
                         json={'language': 'python3', 'source': 'print(sum(map(int,input().split())))'})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'Accepted'
    return result.json()


def test_custom_test_cases_run_locally_without_creating_submission(client, monkeypatch):
    from app.services import coding_judge
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, admin, stage, official=True)
    _judge(monkeypatch)
    observed = []
    monkeypatch.setattr(coding_judge, 'evaluate', lambda language, source, samples: (
        observed.extend(samples) or {'status': 'Accepted', 'detail': '通过 2 / 2', 'passed_cases': 2, 'total_cases': 2}))
    response = client.post(f"/api/coding/questions/{item['id']}/run", headers=alice, json={
        'language': 'cpp11', 'source': 'int main() {}', 'cases': [
            {'input': '2 3', 'output': '5'}, {'input': '10 20', 'output': '30'}]})
    assert response.status_code == 200, response.text
    assert response.json()['total_cases'] == 2
    assert observed == [{'input': '2 3', 'output': '5'}, {'input': '10 20', 'output': '30'}]
    assert client.get(f"/api/coding/questions/{item['id']}/submissions", headers=alice).json()['items'] == []


def test_local_run_requires_at_least_one_test_case(client):
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, admin, stage, official=True)
    response = client.post(f"/api/coding/questions/{item['id']}/run", headers=alice, json={
        'language': 'python3', 'source': 'print(1)', 'cases': []})
    assert response.status_code == 422


def test_question_comments_support_nested_replies_likes_sorting_and_admin_pin(client):
    alice, bob, admin = login(client, 'alice'), login(client, 'bob'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, admin, stage, official=True)
    root = client.post(f"/api/coding/questions/{item['id']}/comments", headers=alice,
                       json={'body': '根评论内容'})
    assert root.status_code == 201, root.text
    reply = client.post(f"/api/coding/questions/{item['id']}/comments", headers=bob,
                        json={'body': '回复内容', 'parent_id': root.json()['id']})
    assert reply.status_code == 201, reply.text
    assert client.put(f"/api/coding/comments/{root.json()['id']}/like", headers=bob).json()['liked'] is True
    listing = client.get(f"/api/coding/questions/{item['id']}/comments?sort=hot", headers=alice).json()
    assert listing['items'][0]['id'] == root.json()['id']
    assert listing['items'][0]['like_count'] == 1
    assert listing['items'][1]['parent_id'] == root.json()['id']
    assert client.post(f"/api/coding/comments/{reply.json()['id']}/pin", headers=alice).status_code == 403
    assert client.post(f"/api/coding/comments/{reply.json()['id']}/pin", headers=admin).json()['pinned'] is True
    newest = client.get(f"/api/coding/questions/{item['id']}/comments?sort=new", headers=alice).json()
    assert newest['items'][0]['id'] == reply.json()['id']
    assert client.delete(f"/api/coding/comments/{root.json()['id']}/like", headers=bob).json()['liked'] is False


def test_private_visibility_admin_hierarchy_and_versioned_review(client):
    from test_admin_permissions import login as root_login
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    root = root_login(client, 'root', 'root')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    assert client.get(f"/api/coding/questions/{item['id']}", headers=bob).status_code == 404
    assert client.get('/api/coding/questions?mine=true', headers=bob).json()['total'] == 0
    assert client.get('/api/admin/coding/questions?q=整数求和', headers=admin).json()['total'] == 0
    assert client.patch(f"/api/coding/questions/{item['id']}", headers=bob,
                        json={'version': 1, 'stars': 5}).status_code == 404
    pending = client.post(f"/api/coding/questions/{item['id']}/submit", headers=alice, json={'version': 1}).json()
    assert client.post(f"/api/admin/coding/questions/{item['id']}/review", headers=admin,
                       json={'version': 1, 'approve': True}).status_code == 409
    rejected = client.post(f"/api/admin/coding/questions/{item['id']}/review", headers=admin,
                           json={'version': pending['version'], 'approve': False, 'reason': '补充范围说明'}).json()
    assert rejected['review_status'] == 'rejected' and rejected['review_reason'] == '补充范围说明'
    approved = _approve(client, alice, admin, rejected)
    assert client.get(f"/api/coding/questions/{item['id']}", headers=bob).status_code == 200
    edited = client.patch(f"/api/coding/questions/{item['id']}", headers=alice,
                          json={'version': approved['version'], 'statement': '新题面'}).json()
    assert edited['visibility'] == 'private' and edited['review_status'] == 'draft'
    assert client.get(f"/api/coding/questions/{item['id']}", headers=bob).status_code == 404
    admin_item = _question(client, admin, stage, title='管理账号投稿')
    pending = client.post(f"/api/coding/questions/{admin_item['id']}/submit", headers=admin, json={'version': 1}).json()
    assert client.get('/api/admin/coding/questions?status=pending', headers=admin).json()['total'] == 0
    assert client.post(f"/api/admin/coding/questions/{admin_item['id']}/review", headers=admin,
                       json={'version': pending['version'], 'approve': True}).status_code == 404
    assert client.post(f"/api/admin/coding/questions/{admin_item['id']}/review", headers=root,
                       json={'version': pending['version'], 'approve': True}).status_code == 200
    assert client.get('/api/coding/home', headers=admin).json()['contribution']['credits_earned'] == 0


def test_stage_order_stars_pagination_disable_and_delete_protection(client):
    alice, admin = login(client, 'alice'), login(client, 'manager')
    first, second = _stage(client, admin, '先学', 200), _stage(client, admin, '后学', 201)
    one = _question(client, admin, first, official=True, position=5, title='专项排序一')
    two = _question(client, admin, first, official=True, position=2, title='专项排序二')
    assert client.post('/api/admin/coding/stages', headers=alice, json={'title': '盗建'}).status_code == 403
    result = client.get(f"/api/coding/questions?stage_id={first['id']}&page_size=1", headers=alice).json()
    assert result['items'][0]['id'] == two['id'] and result['pages'] == 2
    edited = client.patch(f"/api/admin/coding/questions/{one['id']}", headers=admin,
                          json={'version': 1, 'position': 1, 'stars': 5}).json()
    result = client.get(f"/api/coding/questions?stage_id={first['id']}", headers=alice).json()
    assert result['items'][0]['id'] == one['id'] and result['items'][0]['stars'] == 5
    assert client.delete(f"/api/admin/coding/stages/{first['id']}", headers=admin).status_code == 409
    assert client.patch(f"/api/admin/coding/stages/{second['id']}", headers=admin,
                        json={'position': 199}).status_code == 200
    stages = client.get('/api/coding/home', headers=alice).json()['stages']
    assert [s['id'] for s in stages].index(second['id']) < [s['id'] for s in stages].index(first['id'])
    assert client.patch(f"/api/admin/coding/questions/{one['id']}", headers=admin,
                        json={'version': edited['version'], 'active': False}).status_code == 200
    assert client.get(f"/api/coding/questions/{one['id']}", headers=alice).status_code == 404
    assert client.patch(f"/api/admin/coding/stages/{first['id']}", headers=admin, json={'active': False}).status_code == 200
    assert client.get(f"/api/coding/questions?stage_id={first['id']}", headers=alice).json()['total'] == 0
    assert client.delete(f"/api/admin/coding/stages/{second['id']}", headers=admin).status_code == 204


def test_solved_failed_and_favorite_views_are_user_scoped_and_persist(client, monkeypatch):
    from app.services import coding_judge
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    stage = _stage(client, admin)
    solved = _question(client, admin, stage, official=True, title='已完成题目')
    failed = _question(client, admin, stage, official=True, title='尝试未通过题目')
    _judge(monkeypatch)
    monkeypatch.setattr(coding_judge, 'evaluate', lambda language, source, samples: {
        'status': 'Accepted' if 'accepted' in source else 'Wrong Answer',
        'detail': '评测完成', 'passed_cases': 1 if 'accepted' in source else 0, 'total_cases': 1})
    for qid, code in ((solved['id'], 'accepted'), (failed['id'], 'failed')):
        response = client.post(f'/api/coding/questions/{qid}/submissions', headers=alice,
                               json={'language': 'cpp11', 'source': f'// {code}'})
        assert response.status_code == 200, response.text

    assert [item['id'] for item in client.get('/api/coding/questions?view=solved', headers=alice).json()['items']] == [solved['id']]
    assert [item['id'] for item in client.get('/api/coding/questions?view=failed', headers=alice).json()['items']] == [failed['id']]
    assert client.get('/api/coding/questions?view=failed', headers=bob).json()['items'] == []

    favorite = client.put(f"/api/coding/questions/{failed['id']}/favorite", headers=alice)
    assert favorite.status_code == 200 and favorite.json()['favorited'] is True
    assert client.get('/api/coding/questions?view=favorites', headers=alice).json()['items'][0]['id'] == failed['id']
    assert client.get('/api/coding/questions?view=favorites', headers=bob).json()['items'] == []
    assert client.get(f"/api/coding/questions/{failed['id']}", headers=alice).json()['favorited'] is True
    assert client.delete(f"/api/coding/questions/{failed['id']}/favorite", headers=alice).json()['favorited'] is False
    assert client.get('/api/coding/questions?view=favorites', headers=alice).json()['items'] == []


def test_daily_assignment_is_concurrent_fixed_private_and_requires_todays_pass(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import connect
    from app.services import coding_practice
    from datetime import date, timedelta
    _judge(monkeypatch)
    day = date(2026, 11, 15)
    monkeypatch.setattr(coding_practice, 'today', lambda: day)
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    stage = _stage(client, admin)
    own = _question(client, alice, stage)
    _question(client, bob, stage, title='他人私人题目')
    with connect() as db:
        db.execute("UPDATE coding_questions SET active=0 WHERE visibility='public'")
    _solve(client, alice, own['id'])
    day += timedelta(days=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post('/api/coding/daily', headers=alice), range(4)))
    assert all(result.status_code == 200 and result.json()['question_id'] == own['id'] for result in responses)
    assert client.post('/api/coding/checkin', headers=alice).status_code == 409
    _solve(client, alice, own['id'])
    assert client.post('/api/coding/checkin', headers=alice).json()['streak'] == 1
    assert client.get('/api/coding/home', headers=bob).json()['daily']['question_id'] is None
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM coding_daily').fetchone()[0] == 1


def test_seven_fourteen_day_rewards_concurrent_checkin_and_broken_streak(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import connect
    from app.services import coding_practice
    from datetime import date, timedelta
    _judge(monkeypatch)
    day = date(2026, 11, 1)
    monkeypatch.setattr(coding_practice, 'today', lambda: day)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    with connect() as db:
        db.execute("UPDATE coding_questions SET active=0 WHERE visibility='public'")
    for streak in range(1, 15):
        assert client.post('/api/coding/daily', headers=alice).json()['question_id'] == item['id']
        _solve(client, alice, item['id'])
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: client.post('/api/coding/checkin', headers=alice), range(3)))
        assert all(result.status_code == 200 for result in results)
        assert sum(not result.json()['already_checked'] for result in results) == 1
        assert all(result.json()['streak'] == streak for result in results)
        assert results[0].json()['credits'] == (streak // 7 if streak % 7 == 0 else 0)
        day += timedelta(days=1)
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 4
    with connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(delta) FROM credit_ledger WHERE kind='coding_checkin'").fetchone()[:] == (2, 3)
    day += timedelta(days=1)
    client.post('/api/coding/daily', headers=alice)
    _solve(client, alice, item['id'])
    assert client.post('/api/coding/checkin', headers=alice).json()['streak'] == 1


def test_contribution_first_five_reward_and_policy_version_isolation(client):
    from app.db import connect
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    approved = []
    for index in range(5):
        approved.append(_approve(client, alice, admin, _question(client, alice, stage, title=f'投稿 {index}')))
    home = client.get('/api/coding/home', headers=alice).json()
    assert home['contribution']['approved_count'] == 5 and home['contribution']['credits_earned'] == 1
    settings = client.put('/api/admin/coding/settings', headers=admin, json={'questions_per_reward': 2, 'credits_per_reward': 3}).json()
    assert client.put('/api/admin/coding/settings', headers=admin,
                      json={'questions_per_reward': 2, 'credits_per_reward': 3}).json()['id'] == settings['id']
    edit = client.patch(f"/api/coding/questions/{approved[0]['id']}", headers=alice,
                        json={'version': approved[0]['version'], 'statement': '改进说明'}).json()
    _approve(client, alice, admin, edit)
    assert client.get('/api/coding/home', headers=alice).json()['contribution']['approved_count'] == 0
    for index in range(2):
        _approve(client, alice, admin, _question(client, alice, stage, title=f'新规则 {index}'))
    progress = client.get('/api/coding/home', headers=alice).json()['contribution']
    assert progress['approved_count'] == 2 and progress['credits_earned'] == 4
    with connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(delta) FROM credit_ledger WHERE kind='coding_contribution'").fetchone()[:] == (2, 4)
        assert db.execute('SELECT COUNT(*) FROM coding_contribution_approvals').fetchone()[0] == 7


def test_concurrent_review_grants_one_approval(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import connect
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    client.put('/api/admin/coding/settings', headers=admin, json={'questions_per_reward': 1, 'credits_per_reward': 2})
    question = _question(client, alice, stage)
    pending = client.post(f"/api/coding/questions/{question['id']}/submit", headers=alice, json={'version': 1}).json()
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(f"/api/admin/coding/questions/{question['id']}/review", headers=admin,
                                                       json={'version': pending['version'], 'approve': True}), range(3)))
    assert sorted(response.status_code for response in responses) == [200, 409, 409]
    with connect() as db:
        assert db.execute("SELECT COUNT(*),SUM(delta) FROM credit_ledger WHERE kind='coding_contribution'").fetchone()[:] == (1, 2)


def test_local_judge_unavailable_and_private_history_survives_tombstone(client, monkeypatch):
    from app.services import coding_judge
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    stage = _stage(client, admin)
    item = _question(client, alice, stage, statement='<script>alert(1)</script>')
    assert '<script>' not in item['statement_html']
    monkeypatch.setattr(coding_judge, 'availability', lambda: {'available': False, 'languages': [], 'notice': '容器不可用'})
    failed = client.post(f"/api/coding/questions/{item['id']}/submissions", headers=alice,
                         json={'language': 'python3', 'source': 'print(3)'})
    assert failed.status_code == 503 and failed.json()['detail'] == '容器不可用'
    _judge(monkeypatch)
    result = _solve(client, alice, item['id'])
    assert client.get(f"/api/coding/submissions/{result['id']}", headers=bob).status_code == 404
    assert client.get(f"/api/coding/submissions/{result['id']}", headers=admin).status_code == 200
    assert client.delete(f"/api/coding/questions/{item['id']}", headers=alice).status_code == 204
    assert client.get(f"/api/coding/questions/{item['id']}", headers=alice).status_code == 404
    assert client.get(f"/api/coding/questions/{item['id']}/submissions", headers=alice).json()['items'][0]['source'] == result['source']
    assert client.delete(f"/api/admin/coding/stages/{stage['id']}", headers=admin).status_code == 409


def test_remote_result_owner_problem_id_terminal_and_replay_guards(client):
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    stage = _stage(client, admin)
    item = _question(client, admin, stage, official=True, judge_mode='luogu', remote_problem_id='P1001')
    def start():
        return client.post(f"/api/coding/questions/{item['id']}/submissions", headers=alice,
                           json={'source': 'int main() {}', 'language': 'cpp11'}).json()
    first, second = start(), start()
    assert first['remote_problem_id'] == 'P1001' and first['status'] == 'Waiting for browser extension'
    path = f"/api/coding/submissions/{first['id']}/remote-result"
    payload = {'remote_submission_id': '998877', 'remote_problem_id': 'P1001', 'status': 'Judging'}
    assert client.post(path, headers=bob, json=payload).status_code == 404
    assert client.post(path, headers=admin, json=payload).status_code == 404
    assert client.post(path, headers=alice, json=payload | {'remote_problem_id': 'P1000'}).status_code == 409
    assert client.post(path, headers=alice, json=payload | {'remote_submission_id': ''}).status_code == 422
    assert client.post(path, headers=alice, json=payload).status_code == 200
    assert client.post(path, headers=alice, json=payload | {'status': 'Submitted'}).status_code == 409
    assert client.post(path, headers=alice, json=payload | {'status': 'Accepted'}).status_code == 200
    assert client.post(path, headers=alice, json=payload | {'status': 'Accepted'}).status_code == 200
    assert client.post(path, headers=alice, json=payload | {'status': 'Wrong Answer'}).status_code == 409
    assert client.post(path, headers=alice, json=payload | {'remote_submission_id': '998878', 'status': 'Accepted'}).status_code == 409
    assert client.post(f"/api/coding/submissions/{second['id']}/remote-result", headers=alice,
                       json=payload | {'status': 'Accepted'}).status_code == 409


def test_import_is_explicit_safe_and_reports_upstream_failure(client, monkeypatch):
    from app.services import luogu_catalog
    alice, admin = login(client, 'alice'), login(client, 'manager')
    assert client.post('/api/admin/coding/import-luogu', headers=alice, json={'problem_id': 'P1001'}).status_code == 403
    monkeypatch.setattr(luogu_catalog, 'problem', lambda pid: {'problem_id': pid.upper(), 'title': '求和',
                        'statement': '相加', 'samples': [{'input': '1 2', 'output': '3'}]})
    result = client.post('/api/admin/coding/import-luogu', headers=admin, json={'problem_id': 'p1001'})
    assert result.status_code == 200
    assert result.json()['remote_problem_id'] == 'P1001' and result.json()['judge_mode'] == 'luogu'
    def unavailable(pid):
        raise luogu_catalog.LuoguCatalogError('暂时无法连接洛谷题库，请稍后重试')
    monkeypatch.setattr(luogu_catalog, 'problem', unavailable)
    assert client.post('/api/admin/coding/import-luogu', headers=admin, json={'problem_id': 'P1001'}).status_code == 502
    assert client.post('/api/admin/coding/import-luogu', headers=admin, json={'problem_id': '../bad'}).status_code == 422


def test_seed_idempotency_preserves_admin_edits(client, tmp_path, monkeypatch):
    import json
    from app.db import connect
    from app.services import coding_schema
    from app.services.coding_schema import initialize_coding
    (tmp_path / 'catalog.json').write_text(json.dumps({
        'stages': [{'id': 'seed-fixture', 'title': '初始阶段', 'position': 1000}],
        'questions': [{'source_key': 'seed-fixture-q1', 'stage_id': 'seed-fixture', 'title': '种子题目',
                       'samples': [{'input': '1 2', 'output': '3'}]}]}))
    monkeypatch.setattr(coding_schema, 'ASSETS', tmp_path)
    with connect() as db:
        initialize_coding(db)
        row = db.execute("SELECT * FROM coding_questions WHERE source_key='seed-fixture-q1'").fetchone()
        count = db.execute('SELECT COUNT(*) FROM coding_questions').fetchone()[0]
        db.execute("UPDATE coding_questions SET title='管理员修订',stars=5 WHERE id=?", (row['id'],))
        db.execute("UPDATE coding_stages SET title='阶段修订',position=50 WHERE id='seed-fixture'")
        initialize_coding(db)
        assert db.execute('SELECT COUNT(*) FROM coding_questions').fetchone()[0] == count
        changed = db.execute('SELECT title,stars FROM coding_questions WHERE id=?', (row['id'],)).fetchone()
        assert tuple(changed) == ('管理员修订', 5)
        assert tuple(db.execute("SELECT title,position FROM coding_stages WHERE id='seed-fixture'").fetchone()) == ('阶段修订', 50)


def test_beijing_calendar_and_invalid_update_inputs(client, monkeypatch):
    from app.services import coding_practice
    from datetime import datetime, timezone, date
    from types import SimpleNamespace
    monkeypatch.setattr(coding_practice, 'time', SimpleNamespace(time=lambda: datetime(2026, 11, 14, 16, 1, tzinfo=timezone.utc).timestamp()))
    assert coding_practice.today() == date(2026, 11, 15)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    for patch in ({'stars': 0}, {'stars': True}, {'statement': None}, {'source_url': 'javascript:alert(1)'}, {'judge_mode': 'luogu'}):
        response = client.patch(f"/api/coding/questions/{item['id']}", headers=alice, json={'version': 1, **patch})
        assert response.status_code == 422, response.text
    assert client.patch(f"/api/coding/questions/{item['id']}", headers=alice, json={'stars': 5}).status_code == 422
    assert client.patch(f"/api/admin/coding/stages/{stage['id']}", headers=admin, json={'title': '   '}).status_code == 422


def test_judge_unavailable_after_submission_records_failure(client, monkeypatch):
    from app.services import coding_judge
    _judge(monkeypatch)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    def stopped(language, source, samples):
        raise coding_judge.JudgeUnavailable('Docker 已停止，请稍后重试')
    monkeypatch.setattr(coding_judge, 'evaluate', stopped)
    response = client.post(f"/api/coding/questions/{item['id']}/submissions", headers=alice,
                           json={'source': 'print(3)', 'language': 'python3'})
    assert response.status_code == 503
    history = client.get(f"/api/coding/questions/{item['id']}/submissions", headers=alice).json()['items']
    assert len(history) == 1 and history[0]['status'] == 'System Error'
    assert history[0]['completed'] is not None and history[0]['detail'] == 'Docker 已停止，请稍后重试'


def test_account_deletion_removes_private_code_and_anonymizes_public_contributions(client, monkeypatch):
    from app.db import connect
    _judge(monkeypatch)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    private = _question(client, alice, stage)
    public = _approve(client, alice, admin, _question(client, alice, stage, title='公开投稿'))
    submission = _solve(client, alice, private['id'])
    client.post('/api/coding/daily', headers=alice)
    uid = client.get('/api/me', headers=alice).json()['id']
    assert client.delete(f'/api/admin/users/{uid}', headers=admin).status_code == 204
    with connect() as db:
        for table in ('coding_submissions', 'coding_daily', 'coding_checkins'):
            assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=?', (uid,)).fetchone()[0] == 0
        hidden = db.execute('SELECT * FROM coding_questions WHERE id=?', (private['id'],)).fetchone()
        assert hidden['deleted'] and hidden['statement'] == '' and hidden['reference_code'] == '' and hidden['owner_user_id'] is None
        retained = db.execute('SELECT * FROM coding_questions WHERE id=?', (public['id'],)).fetchone()
        assert retained['visibility'] == 'public' and retained['owner_user_id'] is None and not retained['deleted']
        assert db.execute('SELECT user_id FROM coding_contribution_approvals WHERE question_id=?', (public['id'],)).fetchone()[0] is None
    assert client.get(f"/api/coding/submissions/{submission['id']}", headers=admin).status_code == 404


def test_sample_questions_need_cases_and_daily_skips_incomplete_legacy_content(client, monkeypatch):
    from app.db import connect
    from app.services import coding_practice
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    invalid = client.post('/api/coding/questions', headers=alice,
                          json={'stage_id': stage['id'], 'title': '无样例题', 'judge_mode': 'samples'})
    assert invalid.status_code == 422
    valid = _question(client, alice, stage)
    broken = _question(client, alice, stage, title='旧数据缺失样例')
    with connect() as db:
        db.execute("UPDATE coding_questions SET active=0 WHERE visibility='public'")
        db.execute("UPDATE coding_questions SET samples='[]' WHERE id=?", (broken['id'],))
    monkeypatch.setattr(coding_practice.secrets, 'choice', lambda rows: rows[-1])
    daily = client.post('/api/coding/daily', headers=alice)
    assert daily.status_code == 200 and daily.json()['question_id'] == valid['id']


def test_malformed_source_url_is_rejected_without_internal_error(client):
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    result = client.post('/api/coding/questions', headers=alice, json={
        'stage_id': stage['id'], 'title': '来源链接', 'judge_mode': 'samples',
        'samples': [{'input': '', 'output': ''}], 'source_url': 'https://[invalid'})
    assert result.status_code == 422


def test_failed_ledger_write_rolls_back_review_and_reward(client, monkeypatch):
    import pytest
    from app.db import connect
    from app.services import credits
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    client.put('/api/admin/coding/settings', headers=admin, json={'questions_per_reward': 1, 'credits_per_reward': 1})
    item = _question(client, alice, stage)
    pending = client.post(f"/api/coding/questions/{item['id']}/submit", headers=alice, json={'version': 1}).json()
    original_adjust = credits.adjust
    def unavailable(*args, **kwargs):
        raise RuntimeError('模拟账本写入故障')
    monkeypatch.setattr(credits, 'adjust', unavailable)
    with pytest.raises(RuntimeError, match='模拟账本写入故障'):
        client.post(f"/api/admin/coding/questions/{item['id']}/review", headers=admin,
                    json={'version': pending['version'], 'approve': True})
    with connect() as db:
        assert db.execute('SELECT review_status FROM coding_questions WHERE id=?', (item['id'],)).fetchone()[0] == 'pending'
        assert db.execute('SELECT COUNT(*) FROM coding_contribution_approvals').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM coding_contribution_grants').fetchone()[0] == 0
    monkeypatch.setattr(credits, 'adjust', original_adjust)
    assert client.post(f"/api/admin/coding/questions/{item['id']}/review", headers=admin,
                       json={'version': pending['version'], 'approve': True}).status_code == 200
    assert client.get('/api/profile', headers=alice).json()['remaining'] == 2


def test_changing_judged_content_requires_a_new_pass_but_sorting_and_review_do_not(client, monkeypatch):
    from app.db import connect
    _judge(monkeypatch)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, admin, stage, official=True)
    with connect() as db:
        db.execute('UPDATE coding_questions SET active=0 WHERE id<>?', (item['id'],))
    client.post('/api/coding/daily', headers=alice)
    original = _solve(client, alice, item['id'])
    changed = client.patch(f"/api/admin/coding/questions/{item['id']}", headers=admin,
                           json={'version': item['version'], 'samples': [{'input': '1 2', 'output': '4'}]}).json()
    assert changed['solved'] is False
    assert client.get(f"/api/coding/questions/{item['id']}", headers=alice).json()['solved'] is False
    assert client.get('/api/coding/home', headers=alice).json()['progress']['solved'] == 0
    assert client.get('/api/coding/home', headers=alice).json()['daily']['solved'] is False
    assert client.post('/api/coding/checkin', headers=alice).status_code == 409
    assert client.get(f"/api/coding/submissions/{original['id']}", headers=alice).json()['status'] == 'Accepted'
    _solve(client, alice, item['id'])
    changed = client.patch(f"/api/admin/coding/questions/{item['id']}", headers=admin,
                           json={'version': changed['version'], 'stars': 5, 'position': 1}).json()
    assert client.get(f"/api/coding/questions/{item['id']}", headers=alice).json()['solved'] is True
    assert client.post('/api/coding/checkin', headers=alice).status_code == 200
    private = _question(client, alice, stage)
    _solve(client, alice, private['id'])
    approved = _approve(client, alice, admin, private)
    assert client.get(f"/api/coding/questions/{approved['id']}", headers=alice).json()['solved'] is True


def test_delayed_remote_callback_only_solves_the_original_content(client):
    from app.db import connect
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    question = _question(client, admin, stage, official=True, judge_mode='luogu', remote_problem_id='P1001')
    with connect() as db:
        db.execute('UPDATE coding_questions SET active=0 WHERE id<>?', (question['id'],))
    client.post('/api/coding/daily', headers=alice)
    started = client.post(f"/api/coding/questions/{question['id']}/submissions", headers=alice,
                          json={'source': 'int main() {}', 'language': 'cpp11'}).json()
    updated = client.patch(f"/api/admin/coding/questions/{question['id']}", headers=admin,
                           json={'version': question['version'], 'remote_problem_id': 'P1002'})
    assert updated.status_code == 200
    response = client.post(f"/api/coding/submissions/{started['id']}/remote-result", headers=alice,
                           json={'remote_submission_id': '767676', 'remote_problem_id': 'P1001', 'status': 'Accepted'})
    assert response.status_code == 200 and response.json()['status'] == 'Accepted'
    home = client.get('/api/coding/home', headers=alice).json()
    assert home['daily']['solved'] is False and home['progress']['solved'] == 0
    assert client.post('/api/coding/checkin', headers=alice).status_code == 409


def test_admin_edit_keeps_pending_submission_in_review_queue(client):
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    pending = client.post(f"/api/coding/questions/{item['id']}/submit", headers=alice, json={'version': 1}).json()
    edited = client.patch(f"/api/admin/coding/questions/{item['id']}", headers=admin,
                          json={'version': pending['version'], 'active': False, 'stars': 5})
    assert edited.status_code == 200
    assert edited.json()['review_status'] == 'pending' and edited.json()['visibility'] == 'private'
    queue = client.get('/api/admin/coding/questions?status=pending', headers=admin).json()['items']
    assert any(question['id'] == item['id'] for question in queue)
    assert client.post(f"/api/admin/coding/questions/{item['id']}/review", headers=admin,
                       json={'version': edited.json()['version'], 'approve': True}).status_code == 200


def test_content_revision_upgrade_does_not_assume_unknown_preview_results_are_current(client, monkeypatch):
    from app.db import connect
    from app.services.coding_schema import initialize_coding
    _judge(monkeypatch)
    alice, admin = login(client, 'alice'), login(client, 'manager')
    stage = _stage(client, admin)
    item = _question(client, alice, stage)
    record = _solve(client, alice, item['id'])
    with connect() as db:
        db.execute('ALTER TABLE coding_questions DROP COLUMN content_version')
        db.execute('ALTER TABLE coding_submissions DROP COLUMN question_content_version')
        initialize_coding(db)
        initialize_coding(db)
        assert db.execute('SELECT content_version FROM coding_questions WHERE id=?', (item['id'],)).fetchone()[0] == 1
        assert db.execute('SELECT question_content_version FROM coding_submissions WHERE id=?', (record['id'],)).fetchone()[0] == 0
    assert client.get(f"/api/coding/questions/{item['id']}", headers=alice).json()['solved'] is False
    assert client.get(f"/api/coding/submissions/{record['id']}", headers=alice).json()['status'] == 'Accepted'
