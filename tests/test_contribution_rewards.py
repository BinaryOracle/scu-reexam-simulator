from test_system import client, login


def _question(client, headers, index):
    response = client.post('/api/training/questions', headers=headers, json={
        'collection_id': 'data_structures',
        'question': f'用户投稿题目 {index}',
        'answer': '参考答案',
    })
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client, admin, alice, question):
    submitted = client.post(f"/api/training/questions/{question['id']}/submit", headers=alice,
                            json={'version': question['version']})
    assert submitted.status_code == 200, submitted.text
    result = client.post(f"/api/admin/training/questions/{question['id']}/review", headers=admin,
                         json={'version': submitted.json()['version'], 'approve': True, 'reason': ''})
    assert result.status_code == 200, result.text
    return result.json()


def test_approved_contributions_grant_once_at_configured_threshold(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/training/contribution-rewards', headers=alice).status_code == 200
    configured = client.put('/api/admin/training/contribution-rewards', headers=admin,
                            json={'questions_per_reward': 2, 'credits_per_reward': 1})
    assert configured.status_code == 200
    for index in (1, 2):
        question = _question(client, alice, index)
        _approve(client, admin, alice, question)
    progress = client.get('/api/training/contribution-rewards', headers=alice).json()
    assert progress['approved_count'] == 2
    assert progress['credits_earned'] == 1
    from app.db import connect
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE user_id=(SELECT id FROM users WHERE username='alice') AND kind='question_contribution'").fetchone()[0] == 1


def test_rejected_or_withdrawn_questions_do_not_earn_contribution_credit(client):
    admin, alice = login(client, 'manager'), login(client, 'alice')
    question = _question(client, alice, 1)
    submitted = client.post(f"/api/training/questions/{question['id']}/submit", headers=alice,
                            json={'version': question['version']}).json()
    rejected = client.post(f"/api/admin/training/questions/{question['id']}/review", headers=admin,
                           json={'version': submitted['version'], 'approve': False, 'reason': '请补充依据'})
    assert rejected.status_code == 200
    progress = client.get('/api/training/contribution-rewards', headers=alice).json()
    assert progress['approved_count'] == 0
    assert progress['credits_earned'] == 0


def test_regular_user_cannot_change_contribution_policy(client):
    alice = login(client, 'alice')
    response = client.put('/api/admin/training/contribution-rewards', headers=alice,
                          json={'questions_per_reward': 1, 'credits_per_reward': 1})
    assert response.status_code == 403
