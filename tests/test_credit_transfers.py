"""Transfers conserve credits, isolate history and survive retries atomically."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_system import client, login


def send(c, a, **values):
    return c.post('/api/profile/transfers', headers=a, json=dict(recipient='bob', credits=1, idempotency_key='transfer-request-001', **values))


def test_transfer_receipts_retry_and_zero_spending(client):
    a, b, m = [login(client,n) for n in ('alice','bob','manager')]
    payload = {'recipient':'bob','credits':1,'idempotency_key':'receipt-001'}
    for repeat in (False,True):
        r=client.post('/api/profile/transfers',headers=a,json=payload)
        assert r.status_code==201 and r.json()['already_transferred'] is repeat
        assert r.json()['remaining']==0
    assert client.get('/api/profile',headers=b).json()['remaining']==2
    assert client.get('/api/profile',headers=b).json()['redeemed_amount_fen']==0
    outgoing=client.get('/api/profile/transfers',headers=a).json()
    incoming=client.get('/api/profile/transfers',headers=b).json()
    assert outgoing['total']==incoming['total']==1
    assert outgoing['page_size']==incoming['page_size']==5
    assert outgoing['items'][0]['direction']=='out' and outgoing['items'][0]['other_username']=='bob'
    assert incoming['items'][0]['direction']=='in' and incoming['items'][0]['other_username']=='alice'
    assert client.get('/api/profile/transfers',headers=m).json()['total']==0
    assert client.post('/api/profile/transfers',headers=a,json={**payload,'credits':2}).status_code==409


def test_transfer_resolves_username_or_case_insensitive_email_and_retries(client):
    from app.db import connect
    from test_system import login
    sender = login(client, 'alice')
    with connect() as db:
        db.execute("UPDATE users SET email='Bob@Example.com' WHERE username='bob'")
    payload = {'recipient':'  BOB@example.COM  ','credits':1,'idempotency_key':'email-transfer-001'}
    first = client.post('/api/profile/transfers', headers=sender, json=payload)
    repeated = client.post('/api/profile/transfers', headers=sender, json={**payload, 'recipient':'bob@example.com'})
    assert first.status_code == repeated.status_code == 201
    assert first.json()['recipient'] == 'bob'
    assert repeated.json()['already_transferred'] is True
    assert client.get('/api/profile', headers=login(client, 'bob')).json()['remaining'] == 2


def test_transfer_history_pages_five_records_at_a_time(client):
    from app.db import connect
    sender = login(client, 'alice')
    with connect() as db:
        db.execute("UPDATE users SET interview_credits=6 WHERE username='alice'")
    for index in range(6):
        response = client.post('/api/profile/transfers', headers=sender, json={
            'recipient':'bob', 'credits':1, 'idempotency_key':f'page-transfer-{index:03d}'})
        assert response.status_code == 201
    first = client.get('/api/profile/transfers?page=1', headers=sender).json()
    second = client.get('/api/profile/transfers?page=2', headers=sender).json()
    assert first['total'] == second['total'] == 6
    assert first['page_size'] == second['page_size'] == 5
    assert len(first['items']) == 5 and len(second['items']) == 1


def test_concurrent_transfers_cannot_overspend_or_double_receive(client):
    a=login(client,'alice')
    def act(i):
        return client.post('/api/profile/transfers',headers=a,json={'recipient':'bob','credits':1,'idempotency_key':f'concurrent-{i}'})
    with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(act,range(2)))
    assert sorted(x.status_code for x in r)==[201,409]
    assert client.get('/api/profile',headers=login(client,'bob')).json()['remaining']==2


def test_self_invalid_admin_and_inactive_receiver_rejected(client):
    a,m=login(client,'alice'),login(client,'manager')
    base=dict(recipient='bob',credits=1,idempotency_key='invalid-001')
    for change,status in [({'recipient':'alice'},422),({'recipient':'root'},404),({'recipient':'missing'},404),({'credits':0},422),({'credits':True},422),({'credits':1.5},422)]:
        assert client.post('/api/profile/transfers',headers=a,json={**base,**change}).status_code==status
    assert client.post('/api/profile/transfers',headers=m,json=base).status_code==409
    from app.db import connect
    with connect() as db:db.execute("UPDATE users SET is_active=0 WHERE username='bob'")
    assert client.post('/api/profile/transfers',headers=a,json=base).status_code==404


def test_transfer_failure_rolls_back_both_accounts_and_receipt(client,monkeypatch):
    from app.services import credit_transfers
    from app.db import connect
    a=login(client,'alice');original=credit_transfers.adjust;calls=[]
    def fail(*args,**kwargs):
        original(*args,**kwargs);calls.append(1)
        if len(calls)==2:raise RuntimeError('receiver failed')
    monkeypatch.setattr(credit_transfers,'adjust',fail)
    with pytest.raises(RuntimeError):send(client,a)
    with connect() as db:
        assert list(r[0] for r in db.execute("SELECT interview_credits FROM users WHERE username IN ('alice','bob') ORDER BY username"))==[1,1]
        assert db.execute('SELECT COUNT(*) FROM credit_transfers').fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind LIKE 'transfer_%'").fetchone()[0]==0


def test_receiving_user_keeps_receipt_after_sender_account_deleted(client):
    a,b,m=[login(client,n) for n in ('alice','bob','manager')]
    assert send(client,a).status_code==201
    uid=client.get('/api/me',headers=a).json()['id']
    assert client.delete(f'/api/admin/users/{uid}',headers=m).status_code==204
    receipt=client.get('/api/profile/transfers',headers=b).json()['items'][0]
    assert receipt['other_username']=='alice' and receipt['credits']==1
    assert client.get('/api/profile',headers=b).json()['remaining']==2
