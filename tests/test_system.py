import json
import os
import time
from pathlib import Path
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    config = Path('config.example.toml').read_text().replace('data/app.db', str(tmp_path / 'test.db')).replace('data/audio', str(tmp_path / 'audio'))
    (tmp_path / 'config.toml').write_text(config)
    monkeypatch.setenv('SCU_CONFIG', str(tmp_path / 'config.toml'))
    from app.db import initialize, connect
    from app.services.security import hash_password
    initialize()
    with connect() as db:
        for name, role in [('teacher', 'teacher'), ('alice', 'student'), ('bob', 'student')]:
            db.execute('INSERT INTO users(username,password,role) VALUES (?,?,?)', (name,hash_password('password123'),role))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c: yield c

def login(c, name):
    r=c.post('/api/login', json={'username':name,'password':'password123'})
    assert r.status_code == 200
    return {'Authorization':'Bearer '+r.json()['token']}

def test_interview_permissions_and_ai(client, monkeypatch):
    from app.services import ai
    monkeypatch.setattr(ai, 'chat', lambda prompt: '模型结果')
    a,b=login(client,'alice'),login(client,'bob')
    iid=client.post('/api/interviews',headers=a).json()['id']
    assert client.get(f'/api/interviews/{iid}',headers=b).status_code == 404
    assert client.post(f'/api/interviews/{iid}/teacher-question',headers=a).status_code == 400
    for n in range(1,5):
        assert client.put(f'/api/interviews/{iid}/answers/{n}',headers=a,json={'transcript':'我的回答'}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/teacher-question',headers=a).json()['question'] == '模型结果'
    assert client.put(f'/api/interviews/{iid}/answers/5',headers=a,json={'transcript':'回答'}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/finish',headers=a).json()['feedback'] == '模型结果'
    assert client.put(f'/api/interviews/{iid}/answers/1',headers=a,json={'transcript':'修改'}).status_code == 409

def test_contest_access_and_hidden_cases(client, monkeypatch):
    from app.services import judge
    monkeypatch.setattr(judge,'judge',lambda language,source,tests: 'Accepted')
    t,a=login(client,'teacher'),login(client,'alice')
    now=time.time()
    body={'title':'比赛','starts':now-10,'ends':now+100}
    assert client.post('/api/contests',headers=a,json=body).status_code == 403
    cid=client.post('/api/contests',headers=t,json=body).json()['id']
    pid=client.post(f'/api/contests/{cid}/problems',headers=t,json={'title':'加法','statement':'求和','tests':[{'input':'1 2','output':'3'}]}).json()['id']
    assert 'tests' not in client.get(f'/api/contests/{cid}/problems',headers=a).json()[0]
    r=client.post(f'/api/problems/{pid}/submissions',headers=a,json={'source':'print(3)'})
    assert r.json()['status']=='Accepted'
    expired=client.post('/api/contests',headers=t,json={'title':'过期','starts':now-100,'ends':now-10}).json()['id']
    p=client.post(f'/api/contests/{expired}/problems',headers=t,json={'title':'题','statement':'题','tests':[{'input':'','output':''}]}).json()['id']
    assert client.post(f'/api/problems/{p}/submissions',headers=a,json={'source':'pass'}).status_code == 403

def test_audio_saved_when_asr_unconfigured(client):
    a=login(client,'alice'); iid=client.post('/api/interviews',headers=a).json()['id']
    assert client.post(f'/api/interviews/{iid}/answers/1/audio',headers=a,files={'file':('a.webm',b'audio','audio/webm')}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/answers/1/transcribe',headers=a).status_code == 503
    assert client.get(f'/api/interviews/{iid}/answers/1/audio',headers=a).content == b'audio'
