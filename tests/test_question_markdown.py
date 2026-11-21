"""Question Markdown previews, image ownership and publication access."""
import io
from PIL import Image
from test_system import client, login
from test_coding import _stage, _question, _approve


def upload(client, actor, content=None, filename='diagram.png'):
    if content is None:
        output = io.BytesIO()
        Image.new('RGB', (24, 16), 'green').save(output, format='PNG')
        content = output.getvalue()
    return client.post('/api/question-markdown/images', headers=actor,
                       files={'file': (filename, content, 'image/png')})


def test_question_markdown_preview_is_safe_and_supports_images_tables_math(client):
    actor = login(client, 'alice')
    result = client.post('/api/question-markdown/preview', headers=actor, json={
        'markdown': '# 标题\n\n| A | B |\n|---|---|\n|1|2|\n\n$x^2$\n<script>alert(1)</script>\n![图](/api/question-markdown/images/' + 'a' * 32 + ')'})
    assert result.status_code == 200, result.text
    html = result.json()['html']
    assert '<h1>' in html and '<table>' in html and 'math inline' in html
    assert '<script>' not in html and '/api/question-markdown/images/' in html
    assert client.post('/api/question-markdown/preview', json={'markdown': 'x'}).status_code == 401


def test_private_training_markdown_images_follow_publication_and_review_permissions(client):
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    image = upload(client, alice)
    assert image.status_code == 201, image.text
    url = image.json()['url']
    assert client.get(url, headers=alice).status_code == 200
    assert client.get(url, headers=bob).status_code == 404
    assert client.get(url, headers=admin).status_code == 404
    source = f'# 栈与队列\n\n![结构图]({url})'
    result = client.post('/api/training/questions', headers=alice,
                         json={'collection_id': 'data_structures', 'question': source, 'answer': '**先入先出**'})
    assert result.status_code == 201, result.text
    item = result.json()
    assert '<h1>' in item['question_html'] and '<strong>' in item['answer_html']
    qid = item['id']
    stolen = client.post('/api/training/questions', headers=bob,
                         json={'collection_id': 'data_structures', 'question': source})
    assert stolen.status_code == 422
    pending = client.post(f'/api/training/questions/{qid}/submit', headers=alice,
                          json={'version': item['version']}).json()
    assert client.get(url, headers=admin).status_code == 200
    assert client.get(url, headers=bob).status_code == 404
    approved = client.post(f'/api/admin/training/questions/{qid}/review', headers=admin,
                           json={'version': pending['version'], 'approve': True}).json()
    assert client.get(url, headers=bob).status_code == 200
    client.patch(f'/api/training/questions/{qid}', headers=alice, json={
        'collection_id': 'data_structures', 'question': source, 'version': approved['version']})
    assert client.get(url, headers=bob).status_code == 404
    assert client.get(url).status_code == 401


def test_coding_markdown_images_are_private_until_approved(client):
    alice, bob, admin = (login(client, name) for name in ('alice', 'bob', 'manager'))
    stage = _stage(client, admin)
    result = upload(client, alice)
    assert result.status_code == 201, result.text
    url = result.json()['url']
    question = _question(client, alice, stage, statement=f'# 算法说明\n\n![示意图]({url})')
    assert url in question['statement_html']
    assert client.get(url, headers=bob).status_code == 404
    approved = _approve(client, alice, admin, question)
    assert client.get(url, headers=bob).status_code == 200
    response = client.delete(f"/api/coding/questions/{approved['id']}", headers=alice)
    assert response.status_code == 204
    assert client.get(url, headers=bob).status_code == 404


def test_question_images_reject_fake_images_and_unknown_image_references(client):
    actor = login(client, 'alice')
    assert upload(client, actor, b'<svg onload="alert(1)"></svg>', 'bad.png').status_code == 422
    response = client.post('/api/training/questions', headers=actor, json={
        'collection_id': 'data_structures', 'question': '![未知图片](/api/question-markdown/images/'+'f'*32+')'})
    assert response.status_code == 422
