import json
import os
import time
from pathlib import Path
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    config = Path('config.example.toml').read_text().replace('data/app.db', str(tmp_path / 'test.db')).replace('data/audio', str(tmp_path / 'audio')).replace('data/presentations', str(tmp_path / 'presentations'))
    (tmp_path / 'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(tmp_path / 'config.toml'))
    from app.db import initialize, connect
    from app.services.security import hash_password
    initialize()
    with connect() as db:
        for name in ['manager', 'alice', 'bob']:
            db.execute('INSERT INTO users(username,password,is_admin,can_interview,can_exam,can_practice) VALUES (?,?,?,?,?,1)',
                       (name, hash_password('password123'), name == 'manager', 1, 1))
    # Route fixtures use placeholder audio bytes; conversion is covered by provider tests.
    from app.services import ai
    monkeypatch.setattr(ai, 'media_audio', lambda paths: [{'type': 'input_audio', 'input_audio': {'data': 'route-test-audio'}}])
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c: yield c

def login(c, name):
    r=c.post('/api/login', json={'username':name,'password':'password123'})
    assert r.status_code == 200
    return {'Authorization':'Bearer '+r.json()['token']}

def test_interview_permissions_and_ai(client, monkeypatch):
    from app.services import ai
    monkeypatch.setattr(ai, 'chat', lambda prompt, **kwargs: '模型结果')
    a,b=login(client,'alice'),login(client,'bob')
    iid=client.post('/api/interviews',headers=a).json()['id']
    assert client.get(f'/api/interviews/{iid}',headers=b).status_code == 404
    assert client.post(f'/api/interviews/{iid}/teacher-question',headers=a).status_code == 409
    from test_presentations import prepare_intro, draw_questions
    prepare_intro(client, iid, a)
    draw_questions(client, iid, a)
    for n in range(2,5):
        assert client.put(f'/api/interviews/{iid}/answers/{n}',headers=a,json={'transcript':'我的回答'}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/teacher-question',headers=a).json()['question'] == '模型结果'
    assert client.put(f'/api/interviews/{iid}/answers/5',headers=a,json={'transcript':'回答'}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/finish',headers=a).json()['feedback'] == '模型结果'
    assert client.put(f'/api/interviews/{iid}/answers/1',headers=a,json={'transcript':'修改'}).status_code == 409

def test_contest_access_and_hidden_cases(client, monkeypatch):
    from app.services import judge
    monkeypatch.setattr(judge,'judge',lambda language,source,tests: 'Accepted')
    t,a=login(client,'manager'),login(client,'alice')
    now=time.time()
    body={'participant_ids':[3,4],'title':'比赛','starts':now-10,'ends':now+100,'judge_mode':'docker','problems':[
        {'title':'加法','statement':'求和','tests':[{'input':'1 2','output':'3'}]}]}
    assert client.post('/api/admin/contests',headers=a,json=body).status_code == 403
    created=client.post('/api/admin/contests',headers=t,json=body).json()
    cid,pid=created['id'],created['problem_ids'][0]
    assert 'tests' not in client.get(f'/api/contests/{cid}/problems',headers=a).json()[0]
    unsupported=client.post(f'/api/problems/{pid}/submissions',headers=a,json={'source':'int main(){}','language':'cpp11'})
    assert unsupported.status_code == 422
    assert client.get(f'/api/contests/{cid}',headers=a).json()['problems'][0]['attempt_count'] == 0
    r=client.post(f'/api/problems/{pid}/submissions',headers=a,json={'source':'print(3)','language':'python3'})
    assert r.json()['status']=='Accepted'
    expired=client.post('/api/admin/contests',headers=t,json={'participant_ids':[3,4],'title':'过期','starts':now-100,'ends':now-10,'judge_mode':'docker','problems':[
        {'title':'题','statement':'题','tests':[{'input':'','output':''}]}]}).json()['id']
    p=client.get(f'/api/contests/{expired}/problems',headers=a).json()[0]['id']
    assert client.post(f'/api/problems/{p}/submissions',headers=a,json={'source':'pass'}).status_code == 403

def test_luogu_submission_waits_for_browser_bridge_and_accepts_remote_result(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'洛谷赛','starts':now-10,'ends':now+100,
        'problems':[{'title':'加法','statement':'求和','remote_problem_id':'P1000'}]
    })
    cid = contest.json()['id']
    assert contest.status_code == 200, contest.text
    pid = contest.json()['problem_ids'][0]
    assert client.get(f'/api/contests/{cid}/problems', headers=alice).json()[0]['judge_mode'] == 'luogu'
    response = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={
        'source':'print(1)','language':'python3'
    })
    assert response.status_code == 200
    assert response.json()['status'] == 'Waiting for browser extension'
    assert response.json()['remote_problem_id'] == 'P1000'
    sid = response.json()['id']
    assert client.get('/api/submissions', headers=alice).json()['items'][0]['status'] == 'Waiting for browser extension'
    assert client.post(f'/api/submissions/{sid}/remote-result', headers=alice, json={
        'remote_submission_id':'8123456','status':'Judging'
    }).status_code == 200
    result = client.post(f'/api/submissions/{sid}/remote-result', headers=alice, json={
        'remote_submission_id':'8123456','status':'Accepted','detail':'通过'
    })
    assert result.status_code == 200 and result.json()['status'] == 'Accepted'
    assert client.post(f'/api/submissions/{sid}/remote-result', headers=alice, json={
        'remote_submission_id':'different','status':'Wrong Answer'
    }).status_code == 409
    assert client.post(f'/api/submissions/{sid}/remote-result', headers=alice, json={
        'remote_submission_id':'8123456','status':'Wrong Answer'
    }).status_code == 409
    second = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={
        'source':'print(2)','language':'python3'
    }).json()['id']
    limited = client.post(f'/api/submissions/{second}/remote-result', headers=alice, json={
        'remote_submission_id':'8123457','status':'Output Limit Exceeded','detail':'输出超限'
    })
    assert limited.status_code == 200 and limited.json()['status'] == 'Output Limit Exceeded'
    assert client.post(f'/api/submissions/{second}/remote-result', headers=alice, json={
        'remote_submission_id':'8123457','status':'Accepted'
    }).status_code == 409
    assert client.post(f'/api/submissions/{sid}/remote-result', headers=login(client,'bob'), json={
        'remote_submission_id':'8123456','status':'Wrong Answer'
    }).status_code == 404

def test_submissions_are_paginated_have_private_details_and_feed_contest_ranking(client):
    manager, alice, bob = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'成绩赛','starts':now-10,'ends':now+100,'show_ranking':True,
        'ranking_rule':'score','problems':[{'title':'A题','statement':'题面','remote_problem_id':'P1000','points':250}]
    }).json()
    pid = contest['problem_ids'][0]
    admin_attempt = client.post(f'/api/problems/{pid}/submissions', headers=manager,
                                json={'source':'int main(){return 0;}','language':'cpp11'})
    assert admin_attempt.status_code == 200
    assert client.get(f'/api/contests/{contest["id"]}', headers=alice).json()['problems'][0]['attempt_count'] == 0
    first = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source':'int main(){}','language':'cpp11'}).json()['id']
    client.post(f'/api/submissions/{first}/remote-result', headers=alice, json={
        'remote_submission_id':'8123456','status':'Wrong Answer','detail':'测试点 2 答案错误'
    })
    overview = client.get(f'/api/contests/{contest["id"]}', headers=alice).json()
    assert overview['problems'][0]['attempt_count'] == 1
    assert overview['problems'][0]['accepted_count'] == 0
    second = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source':'int main(){return 0;}','language':'cpp11'}).json()['id']
    client.post(f'/api/submissions/{second}/remote-result', headers=alice, json={
        'remote_submission_id':'8123457','status':'Accepted'
    })

    page = client.get('/api/submissions?page=1&page_size=1', headers=alice)
    assert page.status_code == 200
    assert page.json()['total'] == 2 and page.json()['pages'] == 2
    assert 'remote_submission_id' not in page.json()['items'][0]
    detail = client.get(f'/api/submissions/{first}', headers=alice)
    assert detail.status_code == 200
    assert detail.json()['source'] == 'int main(){}'
    assert detail.json()['detail'] == '测试点 2 答案错误'
    assert 'remote_submission_id' not in detail.json()
    assert client.get(f'/api/submissions/{first}', headers=bob).status_code == 404

    overview = client.get(f'/api/contests/{contest["id"]}', headers=alice).json()
    assert overview['problems'][0]['attempt_count'] == 2
    assert overview['problems'][0]['accepted_count'] == 1
    ranking = client.get(f'/api/contests/{contest["id"]}/ranking', headers=alice)
    assert ranking.status_code == 200
    assert ranking.json()['rows'][0]['username'] == 'alice'
    assert ranking.json()['rows'][0]['score'] == 250
    assert ranking.json()['rows'][0]['problems'][0]['attempts'] == 2

    client.post(f'/api/problems/{pid}/submissions', headers=bob, json={'source':'print(1)','language':'python3'})
    client.post(f'/api/problems/{pid}/submissions', headers=bob, json={'source':'print(2)','language':'python3'})
    admin_first = client.get('/api/admin/submissions?page=1&page_size=2', headers=manager).json()
    admin_second = client.get('/api/admin/submissions?page=2&page_size=2', headers=manager).json()
    assert admin_first['total']==admin_second['total']==4
    assert [row['username'] for row in admin_first['items']]==['bob','bob']
    assert [row['username'] for row in admin_second['items']]==['alice','alice']
    all_ids = [row['id'] for row in admin_first['items'] + admin_second['items']]
    assert all_ids == sorted(all_ids, reverse=True)

def test_contest_ranking_awards_ceiling_proportional_score_for_partial_luogu_results(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'部分分赛','starts':now-10,'ends':now+100,'show_ranking':True,
        'ranking_rule':'score','problems':[{'title':'A题','statement':'题面','remote_problem_id':'P1000','points':100}]
    }).json()
    pid = contest['problem_ids'][0]
    first = client.post(f'/api/problems/{pid}/submissions', headers=alice, json={
        'source':'int main(){}','language':'cpp11'
    }).json()['id']
    assert client.post(f'/api/submissions/{first}/remote-result', headers=alice, json={
        'remote_submission_id':'8123456','status':'Wrong Answer',
        'detail':'通过测试用例数：7 / 12\n测试点 #1：AC\n测试点 #2：WA'
    }).status_code == 200
    ranking = client.get(f'/api/contests/{contest["id"]}/ranking', headers=alice).json()
    assert ranking['rows'][0]['score'] == 59
    assert ranking['rows'][0]['problems'][0]['score'] == 59
    assert ranking['rows'][0]['problems'][0]['solved'] is False
    assert ranking['rows'][0]['problems'][0]['passed_cases'] == 7
    assert ranking['rows'][0]['problems'][0]['total_cases'] == 12

def test_admin_submission_directory_and_each_users_submissions_are_paginated_separately(client):
    manager, alice, bob = login(client, 'manager'), login(client, 'alice'), login(client, 'bob')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'分层分页赛','starts':now-10,'ends':now+100,
        'problems':[{'title':'A题','statement':'题面','remote_problem_id':'P1000'}]
    }).json()
    pid = contest['problem_ids'][0]
    for source in ('print(1)', 'print(2)', 'print(3)'):
        assert client.post(f'/api/problems/{pid}/submissions', headers=alice,
                           json={'source':source,'language':'python3'}).status_code == 200
    assert client.post(f'/api/problems/{pid}/submissions', headers=bob,
                       json={'source':'print(4)','language':'python3'}).status_code == 200
    assert client.post(f'/api/problems/{pid}/submissions', headers=manager,
                       json={'source':'print(5)','language':'python3'}).status_code == 200

    first_users = client.get('/api/admin/submissions/users?page=1&page_size=1', headers=manager)
    second_users = client.get('/api/admin/submissions/users?page=2&page_size=1', headers=manager)
    assert first_users.status_code == second_users.status_code == 200
    assert (first_users.json()['total'], first_users.json()['pages']) == (2, 2)
    assert first_users.json()['items'][0]['username'] == 'alice'
    assert first_users.json()['items'][0]['submission_count'] == 3
    assert second_users.json()['items'][0]['username'] == 'bob'

    alice_id = first_users.json()['items'][0]['user_id']
    first_submissions = client.get(f'/api/admin/submissions/users/{alice_id}?page=1&page_size=2', headers=manager)
    second_submissions = client.get(f'/api/admin/submissions/users/{alice_id}?page=2&page_size=2', headers=manager)
    assert first_submissions.status_code == second_submissions.status_code == 200
    assert (first_submissions.json()['total'], first_submissions.json()['pages']) == (3, 2)
    assert len(first_submissions.json()['items']) == 2
    assert len(second_submissions.json()['items']) == 1
    assert all(row['username'] == 'alice' for row in first_submissions.json()['items'] + second_submissions.json()['items'])

def test_contest_ranking_can_be_hidden_and_invalid_language_is_rejected(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'不公开榜单','starts':now-10,'ends':now+100,'show_ranking':False,
        'problems':[{'title':'A题','statement':'题面','remote_problem_id':'P1000'}]
    }).json()
    response = client.get(f'/api/contests/{contest["id"]}/ranking', headers=alice)
    assert response.status_code == 200 and response.json()['visible'] is False
    invalid = client.post(f'/api/problems/{contest["problem_ids"][0]}/submissions', headers=alice,
                          json={'source':'x','language':'brainfuck'})
    assert invalid.status_code == 422

def test_old_oj_schema_migrates_without_changing_local_judge_defaults(tmp_path, monkeypatch):
    config = Path('config.example.toml').read_text()
    config = config.replace('data/app.db', str(tmp_path / 'legacy.db')).replace('data/audio', str(tmp_path / 'audio'))
    config = config.replace('data/presentations', str(tmp_path / 'presentations'))
    config_path = tmp_path / 'config.toml'
    config_path.write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(config_path))
    import sqlite3
    db = sqlite3.connect(tmp_path / 'legacy.db')
    db.executescript('''CREATE TABLE contests(id INTEGER PRIMARY KEY,title TEXT NOT NULL,starts REAL NOT NULL,ends REAL NOT NULL);
        CREATE TABLE problems(id INTEGER PRIMARY KEY,contest_id INTEGER NOT NULL,title TEXT NOT NULL,statement TEXT NOT NULL,sample_input TEXT NOT NULL,sample_output TEXT NOT NULL,tests TEXT NOT NULL);
        CREATE TABLE submissions(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,problem_id INTEGER NOT NULL,language TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,created REAL NOT NULL);
        INSERT INTO contests VALUES(1,'Legacy',1,99);
        INSERT INTO problems VALUES(2,1,'Old','Old problem','','','[]');
        INSERT INTO submissions VALUES(3,1,2,'python3','print(1)','Accepted',5);
        PRAGMA user_version=11;''')
    db.close()
    from app.db import initialize, connect
    initialize(); initialize()
    with connect() as migrated:
        assert tuple(migrated.execute('SELECT judge_mode FROM contests WHERE id=1').fetchone()) == ('docker',)
        assert tuple(migrated.execute('SELECT remote_problem_id FROM problems WHERE id=2').fetchone()) == ('',)
        assert tuple(migrated.execute('SELECT samples FROM problems WHERE id=2').fetchone()) == ('[]',)
        assert tuple(migrated.execute('SELECT status,remote_submission_id,detail FROM submissions WHERE id=3').fetchone()) == ('Accepted','','')

def test_luogu_plugin_download_is_a_valid_bundle(client):
    import io, zipfile
    response = client.get('/api/luogu-extension')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert {'browser-extension/manifest.json','browser-extension/background.js','browser-extension/options.html'} <= set(bundle.namelist())
        manifest = json.loads(bundle.read('browser-extension/manifest.json'))
        assert 'cookies' not in manifest['permissions']
        assert manifest['host_permissions'] == ['https://www.luogu.com.cn/*', 'http://127.0.0.1:8000/*']
        assert 'browser-extension/extension-config.js' in bundle.namelist()
        assert 'APP_ORIGIN = "http://127.0.0.1:8000"' in bundle.read('browser-extension/extension-config.js').decode()
        assert 'type="url"' not in bundle.read('browser-extension/options.html').decode()


def test_admin_manages_luogu_extension_origin_and_rejects_unsafe_urls(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/admin/luogu-settings', headers=alice).status_code == 403
    current = client.get('/api/admin/luogu-settings', headers=manager)
    assert current.status_code == 200 and current.json()['app_origin'] == 'http://127.0.0.1:8000'
    saved = client.patch('/api/admin/luogu-settings', headers=manager,
                         json={'app_origin': 'https://exam.example.edu/'})
    assert saved.status_code == 200 and saved.json()['app_origin'] == 'https://exam.example.edu'
    assert client.patch('/api/admin/luogu-settings', headers=manager,
                        json={'app_origin': 'http://exam.example.edu'}).status_code == 422
    assert client.patch('/api/admin/luogu-settings', headers=manager,
                        json={'app_origin': 'https://exam.example.edu/admin'}).status_code == 422
    import io, zipfile
    with zipfile.ZipFile(io.BytesIO(client.get('/api/luogu-extension').content)) as bundle:
        manifest = json.loads(bundle.read('browser-extension/manifest.json'))
        assert manifest['host_permissions'] == ['https://www.luogu.com.cn/*', 'https://exam.example.edu/*']
        config = bundle.read('browser-extension/extension-config.js').decode()
        assert 'APP_ORIGIN = "https://exam.example.edu"' in config

def test_luogu_contest_requires_a_problem_and_creates_it_atomically(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    base = {'participant_ids':[3,4], 'title':'洛谷模拟赛','starts':now-10,'ends':now+100}
    assert client.post('/api/admin/contests', headers=manager, json=base).status_code == 422
    created = client.post('/api/admin/contests', headers=manager, json={
        **base,
        'problems':[{
            'title':'超级玛丽游戏','statement':'题目描述\n\n输入格式：无','sample_input':'','sample_output':'输出样例',
            'remote_problem_id':'P1000'
        }]
    })
    assert created.status_code == 200, created.text
    cid = created.json()['id']
    problems = client.get(f'/api/contests/{cid}/problems', headers=alice)
    assert problems.status_code == 200 and len(problems.json()) == 1
    assert problems.json()[0]['remote_problem_id'] == 'P1000'
    assert problems.json()[0]['sample_output'] == '输出样例'

def test_luogu_problem_lookup_is_admin_only_and_returns_public_metadata(client, monkeypatch):
    from app.services import luogu_catalog

    list_page = '<script id="lentille-context" type="application/json">' + json.dumps({
        'status':200,'data':{'problems':{'result':[{'pid':'P1000','name':'超级玛丽游戏','difficulty':1,'totalSubmit':20,'totalAccepted':10}]}}
    }, ensure_ascii=False) + '</script>'
    detail_page = '<script id="lentille-context" type="application/json">' + json.dumps({
        'status':200,'data':{
            'problem':{'pid':'P1000','name':'超级玛丽游戏','contenu':{'description':'输出超级玛丽','formatI':'无','formatO':'输出图案'},'samples':[['样例输入','图案结果'],['第二组','第二输出']]},
            'content':{'description':'输出超级玛丽','formatI':'无','formatO':'输出图案'},
        }
    }, ensure_ascii=False) + '</script>'

    class Response:
        status_code = 200
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass

    monkeypatch.setattr(luogu_catalog.httpx, 'get', lambda url, **kwargs: Response(list_page if url.endswith('/problem/list') else detail_page))
    manager, alice = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/admin/luogu/problem-suggestions?q=1000', headers=alice).status_code == 403
    suggestions = client.get('/api/admin/luogu/problem-suggestions?q=1000', headers=manager)
    assert suggestions.status_code == 200 and suggestions.json()[0]['problem_id'] == 'P1000'
    detail = client.get('/api/admin/luogu/problems/P1000', headers=manager)
    assert detail.status_code == 200
    assert detail.json()['title'] == '超级玛丽游戏'
    assert detail.json()['sample_input'] == '样例输入'
    assert detail.json()['sample_output'] == '图案结果'
    assert len(detail.json()['samples']) == 2
    assert '## 输入格式：\n无' in detail.json()['statement']

def test_admin_can_delete_contest_and_its_problem_submissions(client):
    manager, alice = login(client, 'manager'), login(client, 'alice')
    now = time.time()
    contest = client.post('/api/admin/contests', headers=manager, json={
        'participant_ids':[3,4], 'title':'待删除比赛','starts':now-10,'ends':now+100,
        'problems':[{'title':'题目','statement':'描述','remote_problem_id':'P1000'}]
    }).json()
    cid = contest['id']
    pid = client.get(f'/api/contests/{cid}/problems', headers=alice).json()[0]['id']
    assert client.post(f'/api/problems/{pid}/submissions', headers=alice, json={'source':'print(1)'}).status_code == 200
    assert client.delete(f'/api/admin/contests/{cid}', headers=alice).status_code == 403
    assert client.delete(f'/api/admin/contests/{cid}', headers=manager).status_code == 204
    assert all(row['id'] != cid for row in client.get('/api/contests', headers=alice).json())
    assert client.get('/api/submissions', headers=alice).json()['items'] == []
    assert client.get(f'/api/contests/{cid}/problems', headers=alice).status_code == 404

def test_audio_saved_when_asr_unconfigured(client):
    a=login(client,'alice'); iid=client.post('/api/interviews',headers=a).json()['id']
    from test_presentations import upload
    assert upload(client, iid, a).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=a).status_code == 200
    assert client.post(f'/api/interviews/{iid}/answers/1/audio',headers=a,files={'file':('a.webm',b'audio','audio/webm')}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/answers/1/transcribe',headers=a).status_code == 503
    assert client.get(f'/api/interviews/{iid}/answers/1/audio',headers=a).content == b'audio'

def test_interview_record_can_be_renamed_and_deleted_with_its_files(client, tmp_path):
    from app.db import connect
    alice, bob = login(client, 'alice'), login(client, 'bob')
    iid = client.post('/api/interviews', headers=alice).json()['id']
    assert client.get('/api/interviews', headers=alice).json()[0]['title'] == ''
    renamed = client.patch(f'/api/interviews/{iid}', headers=alice, json={'title': '复试项目问答'})
    assert renamed.status_code == 200
    assert renamed.json()['title'] == '复试项目问答'
    assert client.get('/api/interviews', headers=alice).json()[0]['title'] == '复试项目问答'
    assert client.patch(f'/api/interviews/{iid}', headers=bob, json={'title': '越权'}).status_code == 404
    assert client.delete(f'/api/interviews/{iid}', headers=bob).status_code == 404
    assert client.patch(f'/api/interviews/{iid}', headers=alice, json={'title': '   '}).status_code == 422

    audio = tmp_path / 'session.webm'
    deck = tmp_path / 'deck'
    deck.mkdir()
    (deck / '1.png').write_bytes(b'slide')
    audio.write_bytes(b'recording')
    with connect() as db:
        db.execute('UPDATE answers SET audio_path=? WHERE interview_id=? AND stage=1', (str(audio), iid))
        db.execute('INSERT INTO interview_recordings(id,interview_id,created,audio_path) VALUES (?,?,?,?)',
                   ('recording-id', iid, time.time(), str(audio)))
        db.execute('INSERT INTO presentations(interview_id,directory,name,pages) VALUES (?,?,?,?)',
                   (iid, str(deck), 'deck.pdf', 1))
    deleted = client.delete(f'/api/interviews/{iid}', headers=alice)
    assert deleted.status_code == 204
    assert client.get(f'/api/interviews/{iid}', headers=alice).status_code == 404
    assert not audio.exists() and not deck.exists()
    with connect() as db:
        assert db.execute('SELECT 1 FROM answers WHERE interview_id=?', (iid,)).fetchone() is None
        assert db.execute('SELECT 1 FROM interview_recordings WHERE interview_id=?', (iid,)).fetchone() is None
        assert db.execute('SELECT 1 FROM presentations WHERE interview_id=?', (iid,)).fetchone() is None

def test_active_interview_can_be_renamed_and_deleted(client):
    alice = login(client, 'alice')
    iid = client.post('/api/interviews', headers=alice).json()['id']
    from test_presentations import upload
    assert upload(client, iid, alice).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 200
    renamed = client.patch(f'/api/interviews/{iid}', headers=alice, json={'title': '进行中改名'})
    assert renamed.status_code == 200 and renamed.json()['title'] == '进行中改名'
    assert client.delete(f'/api/interviews/{iid}', headers=alice).status_code == 204
    assert client.get(f'/api/interviews/{iid}', headers=alice).status_code == 404
    assert client.post(f'/api/interviews/{iid}/stop', headers=alice).status_code == 404
