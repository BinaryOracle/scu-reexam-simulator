"""Private presentation storage and upload-first interview progression."""
import sqlite3
from pathlib import Path
import pymupdf
import pytest
from test_system import client, login


def deck_bytes():
    with pymupdf.open() as doc:
        for title in ['Self introduction', 'Research project']:
            doc.new_page(width=960, height=540).insert_text((70, 100), title, fontsize=32)
        return doc.tobytes()


def upload(client, iid, headers, content=None, name='intro.pdf'):
    return client.post(f'/api/interviews/{iid}/presentation', headers=headers,
        files={'file': (name, deck_bytes() if content is None else content, 'application/octet-stream')})


def prepare_intro(client, iid, headers):
    assert upload(client, iid, headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/start', headers=headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/answers/1/audio', headers=headers,
        files={'file': ('answer.webm', b'audio', 'audio/webm')}).status_code == 200
    assert client.put(f'/api/interviews/{iid}/answers/1', headers=headers,
        json={'transcript': '我的自我介绍'}).status_code == 200
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 200


def draw_questions(client, iid, headers):
    assert client.post(f'/api/interviews/{iid}/professional-question', headers=headers,
                       json={'subject': 'data_structures'}).status_code == 200
    for stage in (3, 4):
        assert client.post(f'/api/interviews/{iid}/draw-question/{stage}', headers=headers).status_code == 200


def test_new_interview_requires_deck_and_recorded_introduction(client):
    headers = login(client, 'alice')
    item = client.post('/api/interviews', headers=headers).json()
    iid = item['id']
    assert item['workflow_version'] == 5 and not item['intro_completed']
    assert item['presentation'] is None
    assert client.put(f'/api/interviews/{iid}/answers/2', headers=headers,
        json={'transcript': '不能跳过开场'}).status_code == 409
    assert client.post(f'/api/interviews/{iid}/answers/1/audio', headers=headers,
        files={'file': ('a.webm', b'audio', 'audio/webm')}).status_code == 409
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 409
    assert upload(client, iid, headers).status_code == 200
    assert client.post(f'/api/interviews/{iid}/complete-introduction', headers=headers).status_code == 409
    prepare_intro(client, iid, headers)
    assert client.get(f'/api/interviews/{iid}', headers=headers).json()['intro_completed']
    draw_questions(client, iid, headers)
    assert client.put(f'/api/interviews/{iid}/answers/2', headers=headers,
        json={'transcript': 'English introduction'}).status_code == 200
    assert upload(client, iid, headers).status_code == 409


def test_presentation_is_private_and_admin_read_only(client):
    alice, bob, manager = [login(client, x) for x in ['alice', 'bob', 'manager']]
    iid = client.post('/api/interviews', headers=alice).json()['id']
    result = upload(client, iid, alice)
    assert result.status_code == 200
    assert result.json()['presentation'] == {'name': 'intro.pdf', 'pages': 2}
    assert 'directory' not in str(result.json())
    assert client.post(f'/api/interviews/{iid}/start', headers=alice).status_code == 200
    path = f'/api/interviews/{iid}/presentation/pages/1'
    assert client.get(path).status_code == 401
    assert client.get(path, headers=bob).status_code == 404
    assert upload(client, iid, bob).status_code == 404
    response = client.get(path, headers=alice)
    assert response.status_code == 200 and response.headers['content-type'] == 'image/png'
    assert response.headers['cache-control'] == 'private, no-store'
    assert client.get(path.replace('/1', '/99'), headers=alice).status_code == 404
    admin_path = f'/api/admin/interviews/{iid}/presentation/pages/1'
    assert client.get(admin_path, headers=manager).content == response.content
    assert client.get(admin_path, headers=bob).status_code == 403
    assert client.post(f'/api/admin/interviews/{iid}/presentation', headers=manager,
        files={'file': ('intro.pdf', deck_bytes())}).status_code == 404
    from app.db import connect
    with connect() as db:
        db.execute("UPDATE users SET can_interview=0 WHERE username='alice'")
    assert client.get(path, headers=alice).status_code == 200


def test_invalid_or_oversized_replacement_preserves_existing_deck(client):
    a = login(client, 'alice')
    iid = client.post('/api/interviews', headers=a).json()['id']
    assert upload(client, iid, a).status_code == 200
    for name, data in [('bad.pdf', b'bad'), ('bad.pptx', b'bad'), ('bad.html', b'bad'), ('empty.pdf', b'')]:
        assert upload(client, iid, a, data, name).status_code == 400
    from app.config import load_config
    limit = load_config()['presentation']['max_mb'] * 1024 * 1024
    assert upload(client, iid, a, b'x' * (limit + 1)).status_code == 400
    assert client.get(f'/api/interviews/{iid}', headers=a).json()['presentation']['pages'] == 2
    assert client.post(f'/api/interviews/{iid}/start', headers=a).status_code == 200
    assert client.get(f'/api/interviews/{iid}/presentation/pages/2', headers=a).status_code == 200


def test_page_limit_and_converter_failure_leave_no_partial_deck(client, monkeypatch):
    from app.services import presentations
    a = login(client, 'alice')
    iid = client.post('/api/interviews', headers=a).json()['id']
    monkeypatch.setattr(presentations.shutil, 'which', lambda executable: None)
    response = upload(client, iid, a, b'PK\x03\x04fake', 'intro.pptx')
    assert response.status_code == 503
    assert client.get(f'/api/interviews/{iid}', headers=a).json()['presentation'] is None
    from app.config import load_config
    config_path = Path(__import__('os').environ['SCU_CONFIG'])
    config_path.write_text(config_path.read_text().replace('max_pages = 60', 'max_pages = 1'))
    assert upload(client, iid, a).status_code == 400
    assert not list(Path(load_config()['presentation']['directory']).glob('*'))


def test_local_office_conversion_produces_private_slide_images(client):
    import shutil
    from app.config import load_config
    if not shutil.which(load_config()['presentation']['converter']):
        pytest.skip('LibreOffice not installed; PDF route tests still run')
    a = login(client, 'alice')
    iid = client.post('/api/interviews', headers=a).json()['id']
    response = upload(client, iid, a, Path('tests/fixtures/introduction.pptx').read_bytes(), '我的复试.pptx')
    assert response.status_code == 200, response.text
    assert response.json()['presentation'] == {'name': '我的复试.pptx', 'pages': 2}
    assert client.post(f'/api/interviews/{iid}/start', headers=a).status_code == 200
    for page in [1, 2]:
        image = client.get(f'/api/interviews/{iid}/presentation/pages/{page}', headers=a)
        assert image.content.startswith(b'\x89PNG')


def test_replacing_ppt_clears_previous_introduction_and_finished_deck_is_immutable(client):
    from app.db import connect
    a = login(client, 'alice')
    iid = client.post('/api/interviews', headers=a).json()['id']
    with connect() as db:
        db.execute('UPDATE interviews SET workflow_version=2 WHERE id=?', (iid,))
    assert upload(client, iid, a).status_code == 200
    client.post(f'/api/interviews/{iid}/answers/1/audio', headers=a,
        files={'file': ('answer.webm', b'audio')})
    client.put(f'/api/interviews/{iid}/answers/1', headers=a, json={'transcript': 'old deck'})
    response = upload(client, iid, a)
    assert response.json()['answers'][0]['transcript'] == ''
    assert response.json()['answers'][0]['has_audio'] == 0
    with connect() as db:
        db.execute("UPDATE interviews SET status='finished' WHERE id=?", (iid,))
    assert upload(client, iid, a).status_code == 409
    assert client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=a).status_code == 200


def test_default_template_download_preview_and_upload_requirement(client):
    """The shared template is a reference, never a candidate's submitted PPT."""
    import hashlib
    response = client.get('/api/presentation-template')
    assert response.status_code == 200
    template = response.json()
    assert template['year'] == 2026
    assert template['pages'] == 6
    assert template['source_url'] == 'https://cs.scu.edu.cn/info/1266/19768.htm'
    assert '最新版请从复试官网下载' in template['notice']
    download = client.get(template['download_url'])
    assert download.status_code == 200
    assert 'attachment;' in download.headers['content-disposition']
    original = Path('app/assets/reexam-2026/template.pptx').read_bytes()
    assert hashlib.sha256(download.content).digest() == hashlib.sha256(original).digest()
    for page in [1, template['pages']]:
        preview = client.get(f"{template['pages_url']}/{page}")
        assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')
    assert client.get(f"{template['pages_url']}/0").status_code == 404
    assert client.get(f"{template['pages_url']}/7").status_code == 404
    a = login(client, 'alice')
    item = client.post('/api/interviews', headers=a).json()
    assert item['default_presentation'] == template
    assert item['presentation'] is None
    assert client.post(f"/api/interviews/{item['id']}/complete-introduction", headers=a).status_code == 409
    assert upload(client, item['id'], a).json()['presentation']['name'] == 'intro.pdf'
    assert client.get(template['download_url']).content == original


def test_uploaded_chinese_ppt_keeps_readable_chinese_glyphs(client):
    import shutil
    from app.config import load_config
    from app.db import connect
    if not shutil.which(load_config()['presentation']['converter']):
        pytest.skip('LibreOffice not installed')
    a = login(client, 'alice')
    iid = client.post('/api/interviews', headers=a).json()['id']
    response = upload(client, iid, a, Path('app/assets/reexam-2026/template.pptx').read_bytes(), '中文复试.pptx')
    assert response.status_code == 200
    with connect() as db:
        directory = Path(db.execute('SELECT directory FROM presentations WHERE interview_id=?', (iid,)).fetchone()[0])
    with pymupdf.open(directory / 'source.pdf') as document:
        text = document[0].get_text().replace(' ', '').replace('\n', '')
        assert '注意事项' in text and '提交时请使用PDF格式' in text
        assert all('\ufffd' not in page.get_text() for page in document)
        chinese = [char for page in document for span in page.get_texttrace()
                   for char in span['chars'] if 0x4e00 <= char[0] <= 0x9fff]
        assert chinese and all(char[1] != 0 for char in chinese), 'Chinese characters must have real font glyphs'
    preview = client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=a)
    assert preview.status_code == 409
    assert client.post(f'/api/interviews/{iid}/start', headers=a).status_code == 200
    preview = client.get(f'/api/interviews/{iid}/presentation/pages/1', headers=a)
    assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')


def test_missing_font_config_reports_configuration_error_before_conversion(client):
    import os
    path = Path(os.environ['SCU_CONFIG'])
    path.write_text(path.read_text().replace('fontconfig_file = "config/fonts.conf"', 'fontconfig_file = "missing-fonts.conf"'))
    from app.config import load_config
    with pytest.raises(ValueError, match='fontconfig_file'):
        load_config()
