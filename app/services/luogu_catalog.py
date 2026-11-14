"""Read public Luogu problem metadata for administrator-managed contests."""
import json
import re
from html.parser import HTMLParser

import httpx
from app.services.problem_content import render_statement

BASE_URL = 'https://www.luogu.com.cn'
PROBLEM_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,31}$')


class LuoguCatalogError(Exception):
    """A public Luogu problem page could not be read or parsed."""


class _ContextParser(HTMLParser):
    """Collect the JSON context embedded in a Luogu HTML response."""

    def __init__(self):
        super().__init__()
        self._capturing = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self._capturing = tag == 'script' and attributes.get('id') == 'lentille-context'

    def handle_data(self, data):
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._capturing:
            self._capturing = False

    def context(self):
        if not self._parts:
            raise LuoguCatalogError('洛谷页面没有提供题目信息')
        try:
            return json.loads(''.join(self._parts))
        except json.JSONDecodeError as error:
            raise LuoguCatalogError('洛谷返回的题目信息无法解析') from error


def _page(path, params):
    try:
        response = httpx.get(
            f'{BASE_URL}{path}',
            params={**params, '_contentOnly': '1'},
            headers={'Accept': 'text/html', 'User-Agent': 'SCU-Reexam-Question-Import/1.0'},
            timeout=8,
        )
        response.raise_for_status()
        parser = _ContextParser()
        parser.feed(response.text)
        context = parser.context()
    except httpx.HTTPError as error:
        raise LuoguCatalogError('暂时无法连接洛谷题库，请稍后重试') from error
    if context.get('status') != 200 or not isinstance(context.get('data'), dict):
        raise LuoguCatalogError('洛谷没有返回可用的题目信息')
    return context['data']


def search(query):
    """Return at most ten Luogu suggestions, prioritizing exact ID matches."""
    data = _page('/problem/list', {'keyword': query.strip(), 'page': 1})
    problems = data.get('problems', {}).get('result', [])
    normalized = query.strip().casefold()
    problems.sort(key=lambda item: (item.get('pid', '').casefold() != normalized,
                                    not item.get('pid', '').casefold().startswith(normalized)))
    return [
        {'problem_id': item['pid'], 'title': item['name'], 'difficulty': item.get('difficulty')}
        for item in problems[:10]
        if isinstance(item.get('pid'), str) and isinstance(item.get('name'), str)
    ]


def problem(problem_id):
    """Return Markdown, safe display HTML and every public sample from Luogu."""
    normalized = problem_id.upper()
    if not PROBLEM_ID.fullmatch(normalized):
        raise LuoguCatalogError('洛谷题目编号格式无效')
    data = _page(f'/problem/{normalized}', {})
    item = data.get('problem')
    if not isinstance(item, dict) or item.get('pid', '').upper() != normalized:
        raise LuoguCatalogError(f'洛谷题目 {normalized} 不存在或无法访问')
    content = item.get('content') or data.get('content') or item.get('contenu') or {}
    sections = []
    for heading, key in (
        ('题目背景', 'background'),
        ('题目描述', 'description'),
        ('输入格式', 'formatI'),
        ('输出格式', 'formatO'),
        ('说明', 'hint'),
    ):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            sections.append(f'## {heading}：\n{value.strip()}')
    limits = item.get('limits', data.get('limits', {}))
    if isinstance(limits, dict):
        time_limit = _format_limit(limits.get('time'), 'ms')
        memory_limit = _format_limit(limits.get('memory'), 'MiB', scale=1024)
        resource_lines = []
        if time_limit:
            resource_lines.append(f'- 时间限制：{time_limit}')
        if memory_limit:
            resource_lines.append(f'- 内存限制：{memory_limit}')
        if resource_lines:
            sections.append('## 资源限制：\n' + '\n'.join(resource_lines))
    raw_samples = item.get('samples', data.get('samples', []))
    samples = []
    if not isinstance(raw_samples, list):
        raise LuoguCatalogError('洛谷返回的样例格式无法识别，请稍后重试')
    for pair in raw_samples:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(value, str) for value in pair):
            raise LuoguCatalogError('洛谷返回的样例格式无法识别，请稍后重试')
        samples.append({'input': pair[0], 'output': pair[1]})
    sample = samples[0] if samples else {'input': '', 'output': ''}
    statement = '\n\n'.join(sections)
    return {
        'problem_id': normalized,
        'title': item.get('name', normalized),
        'statement': statement,
        'statement_html': render_statement(statement),
        'samples': samples,
        'sample_input': sample['input'],
        'sample_output': sample['output'],
    }


def _format_limit(values, unit, scale=1):
    """Format Luogu's numeric limit list, whose memory values are in KiB."""
    if not isinstance(values, list) or not values:
        return ''
    formatted = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return ''
        scaled = value / scale
        text = str(int(scaled)) if scaled.is_integer() else f'{scaled:g}'
        formatted.append(text)
    return f'{"-".join(formatted)} {unit}'
