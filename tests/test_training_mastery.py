"""Personal mastery changes future sampling without changing round uniqueness or privacy."""
import random
import pytest
from test_system import client, login
from test_training import start, post, create


def end(c, auth, session):
    assert post(c, f"/training/sessions/{session['id']}/end", auth).status_code == 204


def test_custom_count_whole_collection_and_private_default_pool(client):
    a, b = login(client, 'alice'), login(client, 'bob')
    own = create(client, a)
    other = create(client, b, '别人的私人题')
    session = start(client, a, question_count=2)
    assert session['total'] == 2
    end(client, a, session)
    session = start(client, a, question_count='all')
    ids = {card['question_id'] for card in session['cards']}
    assert session['total'] == 34 and len(ids) == 34
    assert own['id'] in ids and other['id'] not in ids
    end(client, a, session)
    session = start(client, a, question_count=500)
    assert session['total'] == 34


@pytest.mark.parametrize('count', [0, -1, True, 1.5, '5', 'invalid'])
def test_invalid_question_count_rejected(client, count):
    a = login(client, 'alice')
    response = post(client, '/training/sessions', a, {'question_count': count})
    assert response.status_code == 422


def test_whole_collection_sequential_wraps_once_from_current_position(client):
    a = login(client, 'alice')
    first = start(client, a, question_count=2)
    for card in first['cards']:
        assert post(client, f"/training/sessions/{first['id']}/cards/{card['id']}/complete", a).status_code == 200
    all_cards = start(client, a, question_count='all')['cards']
    assert len(all_cards) == 33 and len({c['question_id'] for c in all_cards}) == 33
    assert [c['question_id'] for c in all_cards[-2:]] == [c['question_id'] for c in first['cards']]


def test_mastery_is_persistent_personal_and_repeated_completion_is_idempotent(client):
    a, b = login(client, 'alice'), login(client, 'bob')
    session = start(client, a, question_count=1)
    card = session['cards'][0]
    path = f"/training/sessions/{session['id']}/cards/{card['id']}/complete"
    result = post(client, path, a, {'rating': 'again'})
    assert result.status_code == 200
    assert result.json()['cards'][0]['mastery']['status'] == 'again'
    post(client, path, a, {'rating': 'known'})
    from app.db import connect
    with connect() as db:
        uid = db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        m = db.execute('SELECT * FROM training_mastery WHERE user_id=? AND question_id=?', (uid, card['question_id'])).fetchone()
        assert (m['status'], m['review_count'], m['again_count'], m['known_count']) == ('again', 1, 1, 0)
    assert client.get('/api/training/home', headers=a).json()['mastery']['again'] == 1
    assert client.get('/api/training/home', headers=b).json()['mastery']['again'] == 0
    assert client.put(f"/api/training/questions/{card['question_id']}/favorite", headers=a, json={'favorite': True}).status_code == 200
    session = start(client, a, source='favorites', question_count=1)
    assert session['cards'][0]['mastery']['status'] == 'again'
    c = session['cards'][0]
    post(client, f"/training/sessions/{session['id']}/cards/{c['id']}/complete", a, {'rating': 'known'})
    home = client.get('/api/training/home', headers=a).json()
    assert home['mastery']['again'] == 0 and home['mastery']['known'] == 1
    assert home['completed'] == 1
    # A generic completion is not evidence that the answer was learned.
    session = start(client, a, source='favorites', question_count=1)
    c = session['cards'][0]
    result = post(client, f"/training/sessions/{session['id']}/cards/{c['id']}/complete", a).json()
    assert result['cards'][0]['mastery']['status'] == 'known'


def test_weighted_sampling_favors_again_and_does_not_repeat():
    from app.services.training_mastery import weighted_sample
    rows = [{'id': 1}, {'id': 2}, {'id': 3}]
    weights = {1: 4, 2: 2, 3: 1}
    counts = {key: 0 for key in weights}
    for seed in range(1200):
        selected = weighted_sample(rows, 1, weights, rng=random.Random(seed))
        counts[selected[0]['id']] += 1
    assert counts[1] > counts[2] > counts[3]
    assert counts[1] > 3 * counts[3]
    assert len({row['id'] for row in weighted_sample(rows, 100, weights)}) == 3


def test_next_random_round_uses_latest_mastery_weights(client, monkeypatch):
    from app.services import training_mastery
    a = login(client, 'alice')
    qids = []
    for rating in ('again', 'known'):
        session = start(client, a, question_count=1)
        card = session['cards'][0]; qids.append(card['question_id'])
        post(client, f"/training/sessions/{session['id']}/cards/{card['id']}/complete", a, {'rating': rating})
    observed = []
    original = training_mastery.weighted_sample
    def sample(rows, size, weights, **kwargs):
        observed.append(weights)
        return original(rows, size, weights, rng=random.Random(4))
    monkeypatch.setattr(training_mastery, 'weighted_sample', sample)
    start(client, a, mode='random', question_count=3)
    assert observed and observed[0][qids[0]] > observed[0][qids[1]]
    assert set(observed[0].values()) == {1, 2, 4}


def test_history_backfill_keeps_latest_self_rating_and_never_duplicates(client):
    from app.db import connect, initialize
    a = login(client, 'alice')
    session = start(client, a, question_count=1)
    c = session['cards'][0]
    post(client, f"/training/sessions/{session['id']}/cards/{c['id']}/complete", a, {'rating': 'again'})
    client.put(f"/api/training/questions/{c['question_id']}/favorite", headers=a,json={'favorite':True})
    session = start(client, a, source='favorites', question_count=1)
    c = session['cards'][0]
    post(client, f"/training/sessions/{session['id']}/cards/{c['id']}/complete", a, {'rating': 'known'})
    with connect() as db:
        db.execute('DELETE FROM training_mastery')
        db.execute('PRAGMA user_version=18')
    initialize(); initialize()
    with connect() as db:
        row = db.execute('SELECT * FROM training_mastery').fetchone()
        assert (row['status'],row['review_count'],row['again_count'],row['known_count']) == ('known',2,1,1)
        assert db.execute('SELECT COUNT(*) FROM training_mastery').fetchone()[0] == 1


def test_concurrent_self_rating_counts_once_and_deleted_account_clears_mastery(client):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import connect
    a, manager = login(client, 'alice'), login(client, 'manager')
    session = start(client, a, question_count=1)
    card = session['cards'][0]
    path = f"/training/sessions/{session['id']}/cards/{card['id']}/complete"
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: post(client,path,a,{'rating':'again'}), range(4)))
    assert all(r.status_code == 200 for r in responses)
    with connect() as db:
        row = db.execute('SELECT * FROM training_mastery').fetchone()
        assert row['review_count'] == row['again_count'] == 1
        uid = row['user_id']
    assert client.delete(f'/api/admin/users/{uid}',headers=manager).status_code == 204
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_mastery WHERE user_id=?',(uid,)).fetchone()[0] == 0


def test_withdrawn_question_cannot_change_mastery_or_daily_count(client):
    from app.db import connect
    a = login(client,'alice')
    own = create(client,a)
    client.put(f"/api/training/questions/{own['id']}/favorite",headers=a,json={'favorite':True})
    session = start(client,a,source='favorites',question_count='all')
    assert client.delete(f"/api/training/questions/{own['id']}?version=1",headers=a).status_code == 204
    card = session['cards'][0]
    result = post(client,f"/training/sessions/{session['id']}/cards/{card['id']}/complete",a,{'rating':'again'})
    assert result.status_code == 200
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM training_mastery').fetchone()[0] == 0
    assert client.get('/api/training/home',headers=a).json()['completed'] == 0


def test_configured_count_limit_and_whole_collection_are_distinct(client, monkeypatch):
    from app.services import training
    from app.config import load_config
    config = load_config()
    config['training']['max_round_questions'] = 3
    monkeypatch.setattr(training,'load_config',lambda: config)
    a = login(client,'alice')
    response = post(client,'/training/sessions',a,{'question_count':4})
    assert response.status_code == 422
    session = start(client,a,question_count='all',mode='random')
    assert session['total'] == 33 and len({c['question_id'] for c in session['cards']}) == 33
