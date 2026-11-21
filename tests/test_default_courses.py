"""Default course behavior through startup and the learner's existing course APIs."""
import json
import re
from pathlib import Path

import pytest

from test_system import client, login


def root_login(client):
    response = client.post('/api/login', json={'username': 'root', 'password': 'root'})
    assert response.status_code == 200
    return {'Authorization': 'Bearer ' + response.json()['token']}


def default_course(client, headers):
    courses = client.get('/api/courses?scope=public', headers=headers)
    assert courses.status_code == 200
    return next(item for item in courses.json()['items'] if item['title'] == 'labuladong 算法小抄 · 第一至第四章')


def test_default_course_is_complete_readable_private_until_enrolled_and_tracks_progress(client):
    learner = login(client, 'alice')
    course = default_course(client, learner)
    assert course['lesson_count'] == 58
    cid = course['id']
    preview = client.get(f'/api/courses/public/{cid}', headers=learner).json()
    assert len(preview['sections']) == 4
    assert client.get(f'/api/courses/{cid}', headers=learner).status_code == 404
    joined = client.post(f'/api/courses/{cid}/enroll', headers=learner)
    assert joined.status_code == 200, joined.text
    detail = joined.json()
    lessons = [lesson for section in detail['sections'] for lesson in section['lessons']]
    assert len(lessons) == 58
    assert detail['progress_summary'] == {'total': 58, 'completed': 0, 'percent': 0}
    outsider = login(client, 'bob')
    for lesson in lessons:
        assert len(lesson['items']) == 1
        asset = lesson['items'][0]['asset']
        aid = asset['id']
        assert asset['mime_type'] == 'text/markdown'
        assert client.get(f'/api/courses/assets/{aid}/markdown').status_code == 401
        assert client.get(f'/api/courses/assets/{aid}/markdown', headers=outsider).status_code == 404
        response = client.get(f'/api/courses/assets/{aid}/markdown', headers=learner)
        assert response.status_code == 200
        assert '<h2>正文</h2>' in response.text
        assert '用户提供的《labuladong 的算法小抄官方完整版》' not in response.text
        assert 'PDF 原文摘录' not in response.text
        assert '原书第' not in response.text
        assert 'labuladong.online' not in response.text
        assert '<script' not in response.text
        original = client.get(f'/api/courses/assets/{aid}/file', headers=learner)
        assert original.status_code == 200 and original.content.startswith(b'# ')
    short = client.get(f"/api/courses/assets/{lessons[0]['items'][0]['asset']['id']}/markdown", headers=learner).text
    assert 'PDF 未收录完整正文' not in short
    edit_distance = client.get(f"/api/courses/assets/{lessons[4]['items'][0]['asset']['id']}/markdown", headers=learner).text
    assert 'def minDistance(s1, s2)' in edit_distance
    assert '<details class="course-fold course-fold-code">' in edit_distance
    assert '<details class="course-fold course-fold-practice">' in edit_distance
    assert '<h2>对应原题</h2>' not in edit_distance
    assert 'https://leetcode.cn/problems/edit-distance/' not in edit_distance
    image = re.search(r'src="(/api/courses/markdown-images/[a-f0-9]{32})"', edit_distance)[1]
    assert client.get(image, headers=learner).headers['content-type'] == 'image/webp'
    assert client.get(image, headers=outsider).status_code == 404
    qid = re.search(r'href="/#view=coding/question/(\d+)"', edit_distance)[1]
    question = client.get(f'/api/coding/questions/{qid}', headers=learner).json()
    assert question['remote_platform'] == 'leetcode'
    assert question['remote_problem_id'] == 'edit-distance'
    assert 'minDistance' in question['starter_codes']['cpp11']
    assert '插入' in question['statement_html']
    assert '删除' in question['statement_html']
    assert '替换' in question['statement_html']
    assert 'horse' in question['statement_html']
    assert {'input': '"horse"\n"ros"', 'output': '3'} in question['samples']
    submitted = client.post(f'/api/coding/questions/{qid}/submissions', headers=learner,
                            json={'language': 'cpp11', 'source': 'class Solution {};'})
    assert submitted.status_code == 200
    assert submitted.json()['status'] == 'Waiting for browser extension'
    assert submitted.json()['source_info']['question_id'] == '72'
    first = lessons[0]['id']
    progress = client.put(f'/api/courses/lessons/{first}/progress', headers=learner,
                          json={'position_seconds': 0, 'completed': True})
    assert progress.status_code == 200, progress.text
    assert client.get(f'/api/courses/{cid}', headers=learner).json()['progress_summary']['completed'] == 1


def test_catalog_matches_the_first_four_printed_chapters_of_the_user_pdf():
    from app.services.coding_test_adapters import validate_cases

    base = Path(__file__).resolve().parents[1]
    directory = base / 'app/assets/courses/algorithm-beginner'
    catalog = json.loads((directory / 'catalog.json').read_text())
    lessons = [lesson for section in catalog['sections'] for lesson in section['lessons']]
    assert catalog['source_file'] == 'labuladong的算法小抄官方完整版.pdf'
    assert [(section['title'], section['pages']) for section in catalog['sections']] == [
        ('第一章 · 动态规划系列', [117, 214]),
        ('第二章 · 数据结构系列', [215, 302]),
        ('第三章 · 算法思维系列', [303, 392]),
        ('第四章 · 高频面试系列', [393, 513]),
    ]
    assert [len(section['lessons']) for section in catalog['sections']] == [14, 11, 14, 19]
    assert len(lessons) == 58
    question_ids = {str(item['id']) for item in catalog['leetcode_questions']}
    referenced_ids = {str(problem_id) for lesson in lessons for problem_id in lesson['question_ids']}
    assert referenced_ids <= question_ids
    public = {str(item['id']): item for item in catalog['leetcode_questions'] if not item.get('paid_only')}
    exercises = json.loads((directory / 'exercises.json').read_text())
    assert exercises.keys() == public.keys()
    for number, exercise in exercises.items():
        assert exercise['statement'].strip()
        ranges = [lesson['pages'] for lesson in lessons if int(number) in lesson['question_ids']]
        assert exercise['pages'] and all(any(first <= page <= last for first, last in ranges)
                                         for page in exercise['pages'])
        runnable = [case for case in exercise.get('examples', []) if case.get('runnable', True)]
        if runnable:
            validate_cases(runnable, public[number]['judge']['metadata'])
    for lesson in lessons:
        assert lesson['pages'][0] >= 117 and lesson['pages'][1] <= 513
        assert lesson['description'].strip()
        assert 'source_url' not in lesson
        assert all(1 <= int(problem_id) <= 5000 for problem_id in lesson['question_ids'])
        assert (directory / lesson['document']).stat().st_size >= 200


def test_reference_folds_escape_html():
    from app.services.course_learning import render_lesson_markdown
    html = render_lesson_markdown('::: code\n<script>alert(1)</script>\n:::\n\n'
                                  '::: practice\n[x](/#view=coding/question/12)\n:::\n')
    assert '<details class="course-fold course-fold-code">' in html
    assert '<script>' not in html
    assert 'href="/#view=coding/question/12" class="course-practice-link"' in html
    assert 'target="_blank"' not in html


def test_generated_lesson_hides_source_prompts_and_duplicate_original_links():
    from app.services.default_courses import remove_learner_prompts, render_lesson

    catalog = {'leetcode_questions': [{'id': '300', 'title': '最长递增子序列', 'slug': 'lis'}]}
    lesson = {'title': '动态规划练习', 'pages': [248, 249], 'description': '掌握状态定义。',
              'key_points': ['明确转移'], 'question_ids': ['300']}
    rendered = render_lesson(catalog, {'title': '数据结构'}, lesson, {'300': 12}, '正文内容')

    assert '用户提供的《' not in rendered
    assert '## 对应原题' not in rendered
    assert 'leetcode.cn/problems/lis' not in rendered
    assert '打开代码工作区' in rendered
    legacy = '''# 课程

> 用户提供的《资料》· 第 248 页。

## 对应原题

- [300. 最长递增子序列](https://leetcode.cn/problems/lis/)

::: practice
- [300. 最长递增子序列 · 打开代码工作区](/#view=coding/question/12)
:::

::: code
第 248 页 · PDF 原文摘录

```text
示例
```
:::
'''
    cleaned = remove_learner_prompts(legacy)
    assert '用户提供的《' not in cleaned
    assert '对应原题' not in cleaned
    assert 'PDF 原文摘录' not in cleaned
    assert '示例' in cleaned
    assert '打开代码工作区' in cleaned


def test_pdf_question_upgrade_keeps_question_ids_submissions_and_admin_edits(client):
    from app.db import initialize, connect
    from app.services.default_courses import PRACTICE_CONTENT_KEY

    learner = login(client, 'alice')
    with connect() as db:
        db.execute('DELETE FROM app_settings WHERE key=?', (PRACTICE_CONTENT_KEY,))
        for slug in ('edit-distance', 'target-sum', 'burst-balloons'):
            db.execute("""UPDATE coding_questions SET statement='### ' || title || char(10,10) ||
                '[查看力扣中国区原题](' || source_url || ')',samples='[]',version=1
                WHERE source_key=?""", (f'algorithm-book:leetcode:{slug}',))
        db.execute("UPDATE coding_questions SET statement='管理员提供的题面',version=2 WHERE remote_problem_id='target-sum'")
        db.execute("UPDATE coding_questions SET deleted=1,active=0 WHERE source_key='algorithm-book:leetcode:burst-balloons'")
        qid = db.execute("SELECT id FROM coding_questions WHERE source_key='algorithm-book:leetcode:edit-distance'").fetchone()[0]
    response = client.post(f'/api/coding/questions/{qid}/submissions', headers=learner,
                           json={'language': 'cpp11', 'source': 'class Solution {};'})
    assert response.status_code == 200
    with connect() as db:
        sid = response.json()['id']
        db.execute("UPDATE coding_submissions SET status='Accepted' WHERE id=?", (sid,))
    initialize()
    initialize()
    question = client.get(f'/api/coding/questions/{qid}', headers=learner).json()
    assert question['solved']
    assert '插入' in question['statement_html']
    assert {'input': '"horse"\n"ros"', 'output': '3'} in question['samples']
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 1
        assert db.execute("SELECT statement FROM coding_questions WHERE remote_problem_id='target-sum'").fetchone()[0] == '管理员提供的题面'
        assert db.execute("SELECT deleted FROM coding_questions WHERE source_key='algorithm-book:leetcode:burst-balloons'").fetchone()[0] == 1


def test_pdf_upgrade_updates_only_untouched_placeholders_and_keeps_progress(client):
    from app.config import load_config
    from app.db import initialize, connect
    from app.services.default_courses import SEED_KEY

    preview = '''# 经典动态规划：编辑距离

> 用户提供的《labuladong 的算法小抄官方完整版》· 第一章 · 动态规划系列 · 第 127–139 页。

## 学习目标

以两个字符串前缀为状态，比较插入、删除、替换三种操作。

## 对应 LeetCode 练习

- [72. 编辑距离](https://leetcode.cn/problems/edit-distance/)

## 本节代码

练习题的题面、代码编辑器和浏览器桥接评测在“算法带刷”中提供。书中代码摘录只在 PDF 明确包含且可核对时展示；未收录的代码不会用新写实现冒充原文。

## 阅读范围

本课只对应该文章在所提供 PDF 中的第 127–139 页。'''
    learner, root = login(client, 'alice'), root_login(client)
    cid = default_course(client, learner)['id']
    detail = client.post(f'/api/courses/{cid}/enroll', headers=learner).json()
    edited_lesson, untouched_lesson = (detail['sections'][0]['lessons'][i] for i in (0, 4))
    aid = untouched_lesson['items'][0]['asset']['id']
    edited = edited_lesson['items'][0]['asset']['id']
    assert client.put(f'/api/courses/assets/{edited}/markdown', headers=root,
                      json={'markdown': '保留手动修改'}).status_code == 200
    assert client.put(f"/api/courses/lessons/{untouched_lesson['id']}/progress", headers=learner,
                      json={'position_seconds': 0, 'completed': True}).status_code == 200
    with connect() as db:
        db.execute('UPDATE app_settings SET value=? WHERE key=?', (json.dumps({'version': 2, 'course_id': cid}), SEED_KEY))
        name = db.execute('SELECT storage_name FROM course_assets WHERE id=?', (aid,)).fetchone()[0]
    (Path(load_config()['course_media']['directory']) / 'assets' / name).write_text(preview, encoding='utf-8')
    initialize()
    assert default_course(client, learner)['id'] == cid
    upgraded = client.get(f'/api/courses/assets/{aid}/markdown', headers=learner).text
    assert '用户提供的《' not in upgraded
    assert '对应 LeetCode 练习' not in upgraded
    assert 'https://leetcode.cn/problems/edit-distance/' not in upgraded
    assert '插入、删除、替换三种操作。' in upgraded
    assert '阅读范围' not in upgraded
    assert '保留手动修改' in client.get(f'/api/courses/assets/{edited}/markdown', headers=learner).text
    assert client.get(f'/api/courses/{cid}', headers=learner).json()['progress_summary']['completed'] == 1


def test_restarts_preserve_admin_edits_enrollment_and_do_not_duplicate_files(client):
    from app.config import load_config
    from app.db import initialize, connect
    learner = login(client, 'alice')
    root = root_login(client)
    course = default_course(client, learner)
    cid = course['id']
    detail = client.post(f'/api/courses/{cid}/enroll', headers=learner).json()
    lesson = detail['sections'][0]['lessons'][0]
    asset = lesson['items'][0]['asset']['id']
    update = client.put(f'/api/courses/assets/{asset}/markdown', headers=root,
                        json={'markdown': '# 管理员自己的讲义\n\n保留修改。'})
    assert update.status_code == 200, update.text
    with connect() as db:
        db.execute('UPDATE live_courses SET title=? WHERE id=?', ('管理员改名的课程', cid))
    files = set((Path(load_config()['course_media']['directory']) / 'assets').iterdir())
    initialize()
    initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 1
        assert db.execute('SELECT title FROM live_courses WHERE id=?', (cid,)).fetchone()[0] == '管理员改名的课程'
        assert db.execute('SELECT COUNT(*) FROM course_lessons WHERE course_id=?', (cid,)).fetchone()[0] == 58
    assert set((Path(load_config()['course_media']['directory']) / 'assets').iterdir()) == files
    assert '管理员自己的讲义' in client.get(f'/api/courses/assets/{asset}/markdown', headers=learner).text


def test_deleted_default_course_is_not_recreated(client):
    from app.db import initialize, connect
    cid = default_course(client, login(client, 'alice'))['id']
    assert client.delete(f'/api/courses/{cid}', headers=root_login(client)).status_code == 200
    initialize()
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 0


def test_existing_install_keeps_courses_and_gets_default_once(client):
    from app.db import initialize, connect
    from app.services.default_courses import SEED_KEY
    cid = default_course(client, login(client, 'alice'))['id']
    root = root_login(client)
    assert client.delete(f'/api/courses/{cid}', headers=root).status_code == 200
    existing = client.post('/api/courses', headers=login(client, 'manager'), json={
        'title': '已有课程', 'description': '保留原始资料', 'access_mode': 'roster'}).json()
    with connect() as db:
        db.execute('DELETE FROM app_settings WHERE key=?', (SEED_KEY,))
    initialize()
    initialize()
    assert default_course(client, login(client, 'alice'))['lesson_count'] == 58
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 2
        assert db.execute('SELECT description FROM live_courses WHERE id=?', (existing['id'],)).fetchone()[0] == '保留原始资料'


def test_failed_import_rolls_back_records_marker_and_created_files(client, monkeypatch):
    from app.config import load_config
    from app.db import initialize, connect
    from app.services import default_courses as seed
    cid = default_course(client, login(client, 'alice'))['id']
    assert client.delete(f'/api/courses/{cid}', headers=root_login(client)).status_code == 200
    with connect() as db:
        db.execute('DELETE FROM app_settings WHERE key=?', (seed.SEED_KEY,))
    assets = Path(load_config()['course_media']['directory']) / 'assets'
    before = set(assets.iterdir())
    original = seed.store_document
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('test disk failure')
        return original(*args)

    monkeypatch.setattr(seed, 'store_document', fail_second)
    with pytest.raises(OSError, match='test disk failure'):
        initialize()
    assert set(assets.iterdir()) == before
    with connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 0
        assert not db.execute('SELECT 1 FROM app_settings WHERE key=?', (seed.SEED_KEY,)).fetchone()
    monkeypatch.setattr(seed, 'store_document', original)
    initialize()
    assert default_course(client, login(client, 'alice'))['lesson_count'] == 58


def test_database_commit_failure_also_cleans_up_imported_documents(client, monkeypatch):
    from contextlib import contextmanager
    from app.config import load_config
    from app import db as database
    from app.services.default_courses import SEED_KEY

    cid = default_course(client, login(client, 'alice'))['id']
    assert client.delete(f'/api/courses/{cid}', headers=root_login(client)).status_code == 200
    original_connect = database.connect
    with original_connect() as db:
        db.execute('DELETE FROM app_settings WHERE key=?', (SEED_KEY,))
    assets = Path(load_config()['course_media']['directory']) / 'assets'
    before = set(assets.iterdir())

    @contextmanager
    def failed_commit():
        with original_connect() as db:
            yield db
            raise OSError('test commit failure')

    monkeypatch.setattr(database, 'connect', failed_commit)
    with pytest.raises(OSError, match='test commit failure'):
        database.initialize()
    assert set(assets.iterdir()) == before
    with original_connect() as db:
        assert db.execute('SELECT COUNT(*) FROM live_courses').fetchone()[0] == 0
        assert not db.execute('SELECT 1 FROM app_settings WHERE key=?', (SEED_KEY,)).fetchone()
