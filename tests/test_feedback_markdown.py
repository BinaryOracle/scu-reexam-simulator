"""Feedback formatting preserves Markdown while keeping model HTML inert."""
from test_system import client, login


def test_existing_feedback_renders_headings_lists_tables_and_emphasis(client):
    from app.db import connect
    headers = login(client, 'alice')
    iid = client.post('/api/interviews', headers=headers).json()['id']
    text = '### 整体表现\n\n表达**清晰**。\n\n---\n\n1. 项目细节\n2. 技术取舍\n\n| 环节 | 建议 |\n| --- | --- |\n| 英文 | 练习 |'
    with connect() as db:
        db.execute('UPDATE interviews SET feedback=? WHERE id=?', (text, iid))
    detail = client.get(f'/api/interviews/{iid}', headers=headers).json()
    assert detail['feedback'] == text
    html = detail['feedback_html']
    for token in ('<h3>整体表现</h3>', '<strong>清晰</strong>', '<hr', '<ol>', '<table>', '<td>英文</td>'):
        assert token in html
    assert 'feedback_html' not in client.get('/api/interviews', headers=headers).json()[0]


def test_model_html_scripts_unsafe_links_and_remote_images_are_inert(client):
    from app.services.feedback import render_feedback
    html = render_feedback('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1))\n\n![track](https://example.com/track.png)\n\n[官网](https://cs.scu.edu.cn)')
    assert '<script' not in html and '<img' not in html
    assert 'href="javascript:' not in html
    assert '&lt;script&gt;' in html
    assert 'href="https://cs.scu.edu.cn"' in html
