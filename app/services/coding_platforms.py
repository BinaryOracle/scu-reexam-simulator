"""Route public problem lookup through the selected online judge adapter."""
from urllib.parse import urlsplit
from app.services import leetcode_catalog, luogu_catalog
from app.services.problem_content import render_statement


ADAPTERS = {'luogu': luogu_catalog, 'leetcode': leetcode_catalog}
CATALOG_ERRORS = (luogu_catalog.LuoguCatalogError, leetcode_catalog.LeetCodeCatalogError)


def search(platform, query):
    """Return normalized problem suggestions for a supported platform."""
    return ADAPTERS[platform].search(query)


def problem(platform, identifier):
    """Fetch and normalize one public problem from its owning platform."""
    item = ADAPTERS[platform].problem(identifier)
    problem_id = item.get('remote_problem_id', item.get('problem_id', identifier))
    if not item['statement'].strip():
        error = luogu_catalog.LuoguCatalogError if platform == 'luogu' else leetcode_catalog.LeetCodeCatalogError
        label = '洛谷' if platform == 'luogu' else 'LeetCode 中国区'
        raise error(f'{label}没有返回完整题面，请稍后重试')
    statement_html = item.get('statement_html') or render_statement(item['statement'])
    return item | {'statement_html': statement_html, 'remote_problem_id': problem_id, 'remote_platform': platform,
                   'judge_mode': 'luogu', 'source_url': problem_url(platform, problem_id)}


def normalize_identifier(platform, value):
    """Accept a problem identifier or a link to a problem on the selected site."""
    value = value.strip()
    if '://' in value:
        url = urlsplit(value)
        prefix, hosts = {
            'luogu': ('/problem/', {'www.luogu.com.cn'}),
            'leetcode': ('/problems/', {'leetcode.cn'}),
        }[platform]
        if (url.scheme not in ('http', 'https') or url.hostname not in hosts or url.username
                or url.password or not url.path.startswith(prefix)):
            raise ValueError('请选择正确的平台并填写对应的原题链接')
        value = url.path.removeprefix(prefix).strip('/')
        if platform == 'leetcode':
            value = value.removesuffix('/description')
    if platform == 'luogu' and luogu_catalog.PROBLEM_ID.fullmatch(value):
        return value.upper()
    if platform == 'leetcode' and len(value) <= 100 and leetcode_catalog.PROBLEM_SLUG.fullmatch(value):
        return value
    raise ValueError('题目标识无效，请填写洛谷题号或 LeetCode slug，也可以填写原题链接')


def problem_url(platform, identifier):
    """Build the canonical public URL for a problem identifier."""
    if platform == 'luogu':
        return f'https://www.luogu.com.cn/problem/{identifier}'
    if platform == 'leetcode':
        return f'https://leetcode.cn/problems/{identifier}/'
    raise ValueError(f'不支持的评测平台：{platform}')
