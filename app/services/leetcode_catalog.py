"""Read public LeetCode problem statements and starter templates."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import httpx

GRAPHQL_URL = 'https://leetcode.cn/graphql/'
PROBLEM_SLUG = re.compile(r'^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$')
QUESTION_QUERY = '''query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId title translatedTitle titleSlug difficulty content translatedContent sampleTestCase isPaidOnly metaData
    codeSnippets { langSlug code }
  }
}'''
SEARCH_QUERY = '''query problemsetQuestionList($filters: QuestionListFilterInput, $limit: Int!, $skip: Int!) {
  problemsetQuestionList(categorySlug: "", limit: $limit, skip: $skip, filters: $filters) {
    questions { frontendQuestionId title titleCn titleSlug difficulty paidOnly }
  }
}'''


class LeetCodeCatalogError(Exception):
    """A public LeetCode problem could not be loaded or parsed."""


class _MarkdownConverter(HTMLParser):
    """Convert the allowed problem-content tags to Markdown text."""

    BLOCKS = {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'pre',
              'blockquote', 'table', 'tr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0
        self.preformatted = 0
        self.inline_code = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {'script', 'style', 'iframe', 'object', 'svg'}:
            self.ignored += 1
            return
        if self.ignored:
            return
        if tag in self.BLOCKS and self.parts and not self.parts[-1].endswith('\n'):
            self.parts.append('\n')
        if tag == 'li':
            self.parts.append('- ')
        elif tag == 'br':
            self.parts.append('\n')
        elif tag == 'pre':
            self.preformatted += 1
            self.parts.append('\n```text\n')
        elif tag == 'code' and not self.preformatted:
            self.inline_code += 1
            self.parts.append('`')
        elif tag in {'strong', 'b'} and not self.preformatted:
            self.parts.append('**')
        elif tag in {'em', 'i'} and not self.preformatted:
            self.parts.append('*')
        elif tag == 'a':
            href = values.get('href', '')
            try:
                parsed = urlsplit(href)
                safe = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                safe = False
            self.links.append(href if safe else '')
            self.parts.append('[')
        elif tag == 'img':
            source = values.get('src', '')
            try:
                parsed = urlsplit(source)
                if parsed.scheme == 'https' and parsed.hostname in {'assets.leetcode.com', 'assets.leetcode.cn', 'pic.leetcode.cn'}:
                    self.parts.append(f"![{values.get('alt', '题目图片')}]({source})")
            except ValueError:
                return

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'iframe', 'object', 'svg'} and self.ignored:
            self.ignored -= 1
            return
        if self.ignored:
            return
        if tag in {'strong', 'b'} and not self.preformatted:
            self.parts.append('**')
        elif tag in {'em', 'i'} and not self.preformatted:
            self.parts.append('*')
        elif tag == 'code' and not self.preformatted and self.inline_code:
            self.inline_code -= 1
            self.parts.append('`')
        elif tag == 'pre' and self.preformatted:
            self.preformatted -= 1
            self.parts.append('\n```\n')
        elif tag == 'a' and self.links:
            href = self.links.pop()
            self.parts.append(f"]({href})" if href else ']')
        elif tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)

    def markdown(self):
        return re.sub(r'\n{3,}', '\n\n', ''.join(self.parts)).strip()


def _markdown(html):
    parser = _MarkdownConverter()
    parser.feed(html or '')
    return parser.markdown()


def _examples(markdown):
    samples = []
    for block in re.findall(r'(?ms)^```text\n(.*?)\n```$', markdown):
        example = re.search(
            r'(?ms)^\s*(?:输入|Input)\s*[:：]\s*(.*?)\n\s*(?:输出|Output)\s*[:：]\s*(.*?)(?=\n\s*(?:解释|说明|Explanation)\s*[:：]|\Z)',
            block,
        )
        if example and all(example.groups()):
            samples.append(dict(zip(('input', 'output'), (value.strip() for value in example.groups()))))
    return samples


def search(query):
    """Return up to ten public LeetCode problems matching a title or slug."""
    normalized = (query or '').strip()[:100]
    if not normalized:
        return []
    try:
        response = httpx.post(
            GRAPHQL_URL,
            json={'query': SEARCH_QUERY, 'variables': {
                'filters': {'searchKeywords': normalized}, 'limit': 10, 'skip': 0,
            }},
            headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                     'User-Agent': 'SCU-Reexam-Question-Import/1.0'},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LeetCodeCatalogError('暂时无法连接 LeetCode 题库，请稍后重试') from error
    data = (payload.get('data') or {}).get('problemsetQuestionList') if isinstance(payload, dict) else None
    items = data.get('questions') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LeetCodeCatalogError('LeetCode 返回的题目列表格式无法识别')
    return [
        {'problem_id': item['titleSlug'], 'title': item.get('titleCn') or item['title'],
         'number': item.get('frontendQuestionId'), 'difficulty': item.get('difficulty')}
        for item in items[:10]
        if isinstance(item, dict) and not item.get('paidOnly') and isinstance(item.get('titleSlug'), str)
        and PROBLEM_SLUG.fullmatch(item['titleSlug']) and isinstance(item.get('title'), str)
    ]


def problem(slug):
    """Return a LeetCode question in the shared coding-catalog format."""
    normalized = (slug or '').strip()
    if not PROBLEM_SLUG.fullmatch(normalized):
        raise LeetCodeCatalogError('LeetCode 题目 slug 格式无效')
    try:
        response = httpx.post(
            GRAPHQL_URL,
            json={'query': QUESTION_QUERY, 'variables': {'titleSlug': normalized}},
            headers={'Accept': 'application/json', 'Content-Type': 'application/json',
                     'User-Agent': 'SCU-Reexam-Question-Import/1.0'},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LeetCodeCatalogError('暂时无法连接 LeetCode 题库，请稍后重试') from error
    item = (payload.get('data') or {}).get('question') if isinstance(payload, dict) else None
    if not isinstance(item, dict) or item.get('titleSlug') != normalized:
        raise LeetCodeCatalogError(f'LeetCode 题目 {normalized} 不存在或无法访问')
    if item.get('isPaidOnly'):
        raise LeetCodeCatalogError('此题仅限力扣会员，无法导入公开题面')
    statement = _markdown(item.get('translatedContent') or item.get('content'))
    if not statement:
        raise LeetCodeCatalogError('LeetCode 没有返回可用题面')
    snippets = item.get('codeSnippets') or []
    language_map = {'cpp': 'cpp11', 'c': 'c', 'python3': 'python3'}
    starter_codes = {
        language_map[snippet['langSlug']]: snippet['code']
        for snippet in snippets
        if isinstance(snippet, dict) and snippet.get('langSlug') in language_map
        and isinstance(snippet.get('code'), str) and len(snippet['code']) <= 100000
    }
    difficulty = {'Easy': 1, 'Medium': 3, 'Hard': 5}.get(item.get('difficulty'), 1)
    return {
        'title': item.get('translatedTitle') or item['title'],
        'statement': statement,
        'samples': _examples(statement),
        'difficulty': difficulty,
        'remote_problem_id': normalized,
        'remote_platform': 'leetcode',
        'judge_mode': 'luogu',
        'source_url': f'https://leetcode.cn/problems/{normalized}/',
        'starter_codes': starter_codes,
        'source_info': {'platform': 'leetcode', 'question_id': str(item.get('questionId', '')),
                        'sample_test_case': item.get('sampleTestCase') or '',
                        'leetcode_metadata': item.get('metaData') or ''},
    }
