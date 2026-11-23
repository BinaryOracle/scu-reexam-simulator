"""Package snapshots, reversible catalog visibility, and inviter-only purchase details."""
from test_system import client, login


def setup_accounts(client):
    from app.db import connect
    manager, alice, bob = (login(client, name) for name in ('manager', 'alice', 'bob'))
    aid = client.get('/api/me', headers=alice).json()['id']
    bid = client.get('/api/me', headers=bob).json()['id']
    with connect() as db:
        db.execute('UPDATE users SET referrer_id=? WHERE id=?', (aid, bid))
    return manager, alice, bob, bid


def create_package(client, manager, **changes):
    payload = {'name': '复试辅导', 'description': '## 课程说明\n\n**重点训练**', 'price_yuan': '99.99', **changes}
    response = client.post('/api/admin/service-packages', headers=manager, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_package_catalog_requires_admin_and_validates_money(client):
    manager, alice, _, _ = setup_accounts(client)
    assert client.get('/api/admin/service-packages', headers=alice).status_code == 403
    package = create_package(client, manager)
    assert package['price_fen'] == 9999 and package['rebate_basis_points'] == 500
    assert '<strong>重点训练</strong>' in package['description_html']
    for changes in ({'price_yuan': '-1'}, {'price_yuan': '1.001'}, {'rebate_percent': '101'},
                    {'name': '   '}, {'enabled': 'yes'}, {'price_yuan': True}):
        response = client.post('/api/admin/service-packages', headers=manager, json={
            'name': 'invalid', 'price_yuan': '10', **changes})
        assert response.status_code == 422, response.text
    escaped = create_package(client, manager, name='安全描述', description='<script>alert(1)</script>')
    assert '<script>' not in escaped['description_html']


def test_purchase_snapshot_totals_and_referrer_privacy(client):
    manager, alice, bob, bid = setup_accounts(client)
    package = create_package(client, manager)
    path = f'/api/admin/users/{bid}/package-purchases'
    assert client.post(path, headers=alice, json={'package_id': package['id']}).status_code == 403
    bought = client.post(path, headers=manager, json={'package_id': package['id']})
    assert bought.status_code == 201, bought.text
    assert client.post(path, headers=manager, json={'package_id': package['id']}).status_code == 409
    response = client.patch(f'/api/admin/service-packages/{package["id"]}', headers=manager,
                           json={'price_yuan': '1000', 'rebate_percent': '20'})
    assert response.status_code == 200
    details = client.get(path, headers=manager).json()
    assert details['purchase_total_fen'] == 9999 and details['rebate_total_fen'] == 500
    assert details['rebate_status'] == 'pending'
    assert details['items'][0]['rebate_basis_points'] == 500
    invited = client.get('/api/profile/referrals', headers=alice).json()['items'][0]
    assert invited['id'] == bid
    assert invited['purchase_total_fen'] == details['purchase_total_fen']
    assert client.get(f'/api/profile/referrals/{bid}/package-purchases', headers=alice).json() == details
    assert client.get(f'/api/profile/referrals/{bid}/package-purchases', headers=bob).status_code == 404
    listed = next(row for row in client.get('/api/admin/users', headers=manager).json() if row['id'] == bid)
    assert listed['rebate_total_fen'] == 500 and listed['rebate_status'] == 'pending'


def test_catalog_disable_hides_then_restores_purchases_and_settlement(client):
    manager, alice, _, bid = setup_accounts(client)
    package = create_package(client, manager)
    path = f'/api/admin/users/{bid}/package-purchases'
    client.post(path, headers=manager, json={'package_id': package['id']})
    assert client.patch(f'/api/admin/users/{bid}/rebate', headers=manager, json={'redeemed': True}).json()['rebate_status'] == 'redeemed'
    update = f'/api/admin/service-packages/{package["id"]}'
    assert client.patch(update, headers=manager, json={'enabled': False}).status_code == 200
    hidden = client.get(path, headers=manager).json()
    assert hidden['items'] == [] and hidden['rebate_total_fen'] == 0 and hidden['rebate_status'] == 'unset'
    assert client.post(path, headers=manager, json={'package_id': package['id']}).status_code == 409
    assert client.patch(f'/api/admin/users/{bid}/rebate', headers=manager, json={'redeemed': True}).status_code == 409
    client.patch(update, headers=manager, json={'enabled': True})
    restored = client.get(path, headers=manager).json()
    assert restored['rebate_status'] == 'redeemed' and restored['rebate_total_fen'] == 500
    second = create_package(client, manager, name='项目辅导', price_yuan='10')
    client.post(path, headers=manager, json={'package_id': second['id']})
    mixed = client.get(path, headers=manager).json()
    assert mixed['rebate_status'] == 'pending'
    assert mixed['pending_rebate_fen'] == 50 and mixed['redeemed_rebate_fen'] == 500
    pid = restored['items'][0]['id']
    assert client.delete(f'{path}/{pid}', headers=manager).status_code == 204
    assert client.get(path, headers=manager).json()['purchase_total_fen'] == 1000
    client.patch(update, headers=manager, json={'enabled': False})
    client.patch(update, headers=manager, json={'enabled': True})
    assert len(client.get(path, headers=manager).json()['items']) == 1


def test_no_inviter_has_unset_rebate_and_legacy_text_is_not_a_purchase(client):
    manager = login(client, 'manager')
    from app.db import connect
    with connect() as db:
        uid = db.execute("SELECT id FROM users WHERE username='bob'").fetchone()[0]
        db.execute("UPDATE users SET purchase_service='不明金额的旧记录',rebate_redeemed=1 WHERE id=?", (uid,))
    package = create_package(client, manager)
    path = f'/api/admin/users/{uid}/package-purchases'
    assert client.get(path, headers=manager).json()['purchase_total_fen'] == 0
    client.post(path, headers=manager, json={'package_id': package['id']})
    data = client.get(path, headers=manager).json()
    assert data['purchase_total_fen'] == 9999 and data['rebate_total_fen'] == 0 and data['rebate_status'] == 'unset'
    assert client.patch(f'/api/admin/users/{uid}/rebate', headers=manager, json={'redeemed': True}).status_code == 409
    admin_id = client.get('/api/me', headers=manager).json()['id']
    assert client.get(f'/api/admin/users/{admin_id}/package-purchases', headers=manager).status_code == 404


def test_package_purchases_survive_account_credit_backup_restore(client):
    from test_backups import export, restore, root
    manager, _, _, bid = setup_accounts(client)
    package = create_package(client, manager)
    path = f'/api/admin/users/{bid}/package-purchases'
    client.post(path, headers=manager, json={'package_id': package['id']})
    client.patch(f'/api/admin/users/{bid}/rebate', headers=manager, json={'redeemed': True})
    owner = root(client)
    archive = export(client, owner, ['credits'])
    client.patch(f'/api/admin/service-packages/{package["id"]}', headers=manager, json={'enabled': False})
    result = restore(client, owner, archive)
    assert result.status_code == 200, result.text
    data = client.get(path, headers=login(client, 'manager')).json()
    assert data['purchase_total_fen'] == 9999 and data['rebate_total_fen'] == 500
    assert data['rebate_status'] == 'redeemed'
