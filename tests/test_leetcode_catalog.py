import pytest


def test_problem_import_returns_safe_markdown_and_platform_starter_codes(monkeypatch):
    from app.services import leetcode_catalog

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'data': {'question': {
                'questionId': '1', 'title': 'Two Sum', 'titleSlug': 'two-sum', 'difficulty': 'Easy',
                'content': '<p>Find a <strong>pair</strong>.</p><script>alert(1)</script>',
                'sampleTestCase': '[2,7]\n9', 'metaData': '{"name":"twoSum"}',
                'codeSnippets': [
                    {'langSlug': 'cpp', 'code': 'class Solution {};'},
                    {'langSlug': 'python3', 'code': 'class Solution: pass'},
                ],
            }}}

    monkeypatch.setattr(leetcode_catalog.httpx, 'post', lambda *args, **kwargs: calls.append((args, kwargs)) or Response())
    result = leetcode_catalog.problem('two-sum')

    assert result['title'] == 'Two Sum'
    assert result['source_url'] == 'https://leetcode.cn/problems/two-sum/'
    assert 'Find a **pair**.' in result['statement']
    assert 'alert(1)' not in result['statement']
    assert result['starter_codes'] == {'cpp11': 'class Solution {};', 'python3': 'class Solution: pass'}
    assert result['samples'] == []
    assert result['source_info']['leetcode_metadata'] == '{"name":"twoSum"}'
    assert 'metaData' in calls[0][1]['json']['query']
    assert calls[0][0][0] == 'https://leetcode.cn/graphql/'
    assert calls[0][1]['json']['variables'] == {'titleSlug': 'two-sum'}


def test_problem_import_rejects_invalid_slug_without_network(monkeypatch):
    from app.services import leetcode_catalog

    monkeypatch.setattr(leetcode_catalog.httpx, 'post', lambda *_args, **_kwargs: pytest.fail('unexpected request'))
    with pytest.raises(leetcode_catalog.LeetCodeCatalogError, match='题目 slug'):
        leetcode_catalog.problem('../two-sum')


def test_search_returns_normalized_leetcode_problem_suggestions(monkeypatch):
    from app.services import leetcode_catalog

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'data': {'problemsetQuestionList': {'questions': [
                {'frontendQuestionId': '1', 'title': 'Two Sum', 'titleCn': '两数之和',
                 'titleSlug': 'two-sum', 'difficulty': 'Easy', 'paidOnly': False},
                {'frontendQuestionId': '15', 'title': '3Sum', 'titleCn': '三数之和',
                 'titleSlug': '3sum', 'difficulty': 'Medium', 'paidOnly': False},
                {'frontendQuestionId': '999', 'title': 'Locked', 'titleCn': '会员题',
                 'titleSlug': 'locked', 'difficulty': 'Hard', 'paidOnly': True},
            ]}}}

    observed = []
    monkeypatch.setattr(leetcode_catalog.httpx, 'post', lambda *args, **kwargs: observed.append((args, kwargs)) or Response())
    assert leetcode_catalog.search('two') == [
        {'problem_id': 'two-sum', 'title': '两数之和', 'number': '1', 'difficulty': 'Easy'},
        {'problem_id': '3sum', 'title': '三数之和', 'number': '15', 'difficulty': 'Medium'},
    ]
    assert observed[0][0][0] == 'https://leetcode.cn/graphql/'
    assert observed[0][1]['json']['variables']['filters']['searchKeywords'] == 'two'


def test_leetcode_links_are_china_only():
    from app.services import coding_platforms

    assert coding_platforms.normalize_identifier('leetcode', 'https://leetcode.cn/problems/two-sum/') == 'two-sum'
    assert coding_platforms.problem_url('leetcode', 'two-sum') == 'https://leetcode.cn/problems/two-sum/'
    assert coding_platforms.normalize_identifier('leetcode', '1fGaJU') == '1fGaJU'
    assert coding_platforms.problem_url('leetcode', '1fGaJU') == 'https://leetcode.cn/problems/1fGaJU/'
    with pytest.raises(ValueError, match='正确的平台'):
        coding_platforms.normalize_identifier('leetcode', 'https://leetcode.com/problems/two-sum/')


def test_empty_leetcode_statements_report_the_selected_platform(monkeypatch):
    from app.services import coding_platforms, leetcode_catalog

    monkeypatch.setattr(leetcode_catalog, 'problem', lambda _slug: {
        'title': 'Two Sum', 'statement': '  ', 'remote_problem_id': 'two-sum',
    })
    with pytest.raises(leetcode_catalog.LeetCodeCatalogError, match='LeetCode 中国区没有返回完整题面'):
        coding_platforms.problem('leetcode', 'two-sum')
