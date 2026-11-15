#!/usr/bin/env python3
"""Rebuild the coding seed from saved PDF inventories and verified public metadata.

No database is written. --extract reads the two supplied PDFs; --refresh refreshes
public Luogu data; the default uses committed caches and requires no network.
--verify executes only the reviewed local reference programs, never PDF excerpts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'app/assets/coding'
FILES = {
    'guide': '机试历年真题大全 + 全程算法带刷题单！！！.pdf',
    'templates': '历年笔试_上机算法题归类汇总 (模版题为主).pdf',
}
STAGES = [
    ('foundation', '01 · 语法、数组与字符串', '从输入输出开始，练熟循环、数组、字符串、矩阵模拟。'),
    ('structures', '02 · 数据结构与排序', '掌握链表、栈队列、排序、哈希、前缀和与双指针。'),
    ('search', '03 · 递归、分治与搜索', '从递推和枚举进入 DFS、BFS、回溯与剪枝。'),
    ('algorithms', '04 · 二分、贪心与基础数论', '掌握常见算法模型，并练习边界、精度与复杂度。'),
    ('dp', '05 · 动态规划核心模型', '线性、序列、背包和区间动态规划，从状态定义开始。'),
    ('graphs', '06 · 图论与树', '遍历、并查集、拓扑序、最短路与最小生成树。'),
    ('advanced', '07 · 进阶专题', '树形与状压 DP、树状数组、线段树、字符串和数论进阶。'),
    ('challenge', '08 · 综合与压轴', '较难搜索、大模拟和综合应用；先完成前面高星题。'),
]
GROUP_SECTIONS = {0, 1, 9, 18, 27, 28, 35, 41, 58, 66, 83, 92, 101, 105, 115, 127, 132}
PID = re.compile(r'luogu\.com\.cn/problem/([A-Za-z0-9_-]+)', re.I)


def read(name):
    return json.loads((ASSETS / name).read_text(encoding='utf-8'))


def write(name, value):
    (ASSETS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def clean(value):
    return value.replace('\u200b', '').strip()


def extract(directory):
    """Retain every PDF page/link, including repeated annotations and context."""
    try:
        import pymupdf
    except ImportError as error:
        raise SystemExit('PDF extraction requires pymupdf (runtime install: pip install pymupdf)') from error
    for kind, filename in FILES.items():
        path = directory / filename
        doc = pymupdf.open(path)
        pages, headings = [], []
        stage, section = '历史题与扩展', '历年题'
        for number, page in enumerate(doc, 1):
            lines = []
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    text = clean(''.join(span['text'] for span in line['spans']))
                    if text:
                        lines.append({'text': text, 'y': line['bbox'][1],
                                      'size': max(span['size'] for span in line['spans']),
                                      'code': any('SourceCodePro' in span['font'] for span in line['spans'])})
                        if kind == 'templates' and lines[-1]['size'] > 13 and text != '•':
                            headings.append({'title': text, 'page': number, 'y': line['bbox'][1]})
            links, events = [], []
            for line in lines:
                if kind == 'guide' and re.match(r'阶段[一二三]|模拟题|第[一二三]轮|[Dd]ay\d+', line['text']):
                    events.append((line['y'], 'heading', line['text']))
            for link in page.get_links():
                if not link.get('uri'):
                    continue
                rect = pymupdf.Rect(link['from'])
                item = {'url': link['uri'], 'anchor': clean(page.get_textbox(rect)),
                        'context': clean(page.get_textbox(pymupdf.Rect(0, max(0, rect.y0 - 14), page.rect.width, min(page.rect.height, rect.y1 + 14)))),
                        'rect': list(rect)}
                events.append((rect.y0, 'link', item))
            for _, event, item in sorted(events, key=lambda event: event[0]):
                if event == 'heading':
                    if re.match(r'阶段[一二三]|模拟题|第[一二三]轮', item):
                        stage = item
                    section = item
                else:
                    item['pdf_stage'] = stage
                    item['section'] = section
                    links.append(item)
            pages.append({'page': number, 'text': page.get_text(), 'links': links})
        write(f'{kind}-extracted.json', {'file': filename, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'pages': pages})
        if kind != 'templates':
            continue
        sections = []
        for index, heading in enumerate(headings):
            following = headings[index + 1] if index + 1 < len(headings) else {'page': len(doc) + 1, 'y': 0}
            texts, code, links, page_numbers = [], [], [], []
            for number in range(heading['page'], min(following['page'], len(doc)) + 1):
                page = doc[number - 1]
                lo = heading['y'] if number == heading['page'] else 0
                hi = following['y'] if number == following['page'] else page.rect.height
                if hi <= lo:
                    continue
                page_numbers.append(number)
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        if not lo - 0.1 <= line['bbox'][1] < hi:
                            continue
                        text = ''.join(span['text'] for span in line['spans']).replace('\u200b', '')
                        texts.append(text)
                        if any('SourceCodePro' in span['font'] for span in line['spans']) and not text.strip().isdigit():
                            code.append(text)
                for link in page.get_links():
                    if link.get('uri') and lo <= link['from'].y0 < hi:
                        links.append(link['uri'])
            sections.append({'index': index, **heading, 'pages': page_numbers,
                             'text': '\n'.join(texts), 'code': '\n'.join(code), 'links': list(dict.fromkeys(links))})
        write('template-sections.json', sections)


def all_links():
    result = []
    for kind in FILES:
        source = read(f'{kind}-extracted.json')
        for page in source['pages']:
            for link in page['links']:
                result.append({'file': source['file'], 'page': page['page'], **link})
    return result


def remote_ids(links):
    return sorted({match[1].upper() for link in links if (match := PID.search(link['url']))})


def refresh(ids, force=False, workers=2):
    """Use the application formatter; retry only the public JS cookie redirect.

    No script is evaluated, and no login/captcha is attempted. The exact C3VK
    literal set by the public response is carried into one subsequent GET.
    """
    sys.path.insert(0, str(ROOT))
    from app.services import luogu_catalog
    import httpx
    original_httpx = luogu_catalog.httpx
    cache = read('luogu-cache.json') if (ASSETS / 'luogu-cache.json').exists() else {}
    def get(*args, **kwargs):
        response = httpx.get(*args, **kwargs)
        cookie = re.search(r'cookie="(C3VK=[a-zA-Z0-9]+);', response.text)
        if cookie and 'lentille-context' not in response.text:
            kwargs['cookies'] = dict([cookie[1].split('=')])
            response = httpx.get(*args, **kwargs)
        return response
    # Keep the application module's exception class and parsing/formatting intact.
    luogu_catalog.httpx = SimpleNamespace(get=get, HTTPError=httpx.HTTPError)
    try:
        def fetch(pid):
            try:
                result = luogu_catalog.problem(pid)
                result.pop('statement_html', None)
                if not result['statement'].strip() or not result['samples']:
                    raise ValueError('原页面未给出完整题面及公开样例')
                result['fetched_at'] = datetime.now(timezone.utc).isoformat()
                return pid, result
            except (luogu_catalog.LuoguCatalogError, ValueError) as error:
                return pid, {'error': str(error)}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch, pid) for pid in ids if force or pid not in cache or 'error' in cache[pid]]
            for count, future in enumerate(as_completed(futures), 1):
                pid, result = future.result()
                if 'error' in result and pid in cache and 'error' not in cache[pid]:
                    cache[pid]['refresh_error'] = result['error']
                else:
                    cache[pid] = result
                if count % 20 == 0:
                    write('luogu-cache.json', cache)
                    print(f'Fetched {count}/{len(futures)}', flush=True)
        write('luogu-cache.json', cache)
    finally:
        luogu_catalog.httpx = original_httpx


def stage_for(topic, original_stage='', title=''):
    text = f'{topic} {title}'
    if '阶段三' in original_stage or '第三轮' in original_stage or re.search(r'综合练习|斗地主|靶形数独|骑士精神|埃及分数|矩阵链乘', text):
        return 'challenge'
    if re.search(r'树形|状态压缩|状压|Tarjan|树状数组|线段树|LCA|ST 表|单调队列优化|字符串进阶|数论专项|博弈|进阶贪心', text, re.I):
        return 'advanced'
    if re.search(r'DP|动态规划|背包|编辑距离|公共子序列|区间DP|子数组和|子段和|目标和', text, re.I):
        return 'dp'
    if re.search(r'图论|图搜索|拓扑|最短路|最小生成树|并查集|树的基础|极大连通|BFS最短', text):
        return 'graphs'
    if re.search(r'DFS|BFS|搜索|递归|分治|回溯|枚举|递推|皇后|组合总和', text, re.I):
        return 'search'
    if re.search(r'贪心|二分|数论|组合数学|高精度|进制|数学|部分背包|快速幂', text):
        return 'algorithms'
    if re.search(r'数据结构|排序|栈|队列|链表|双指针|前缀|差分|哈希|结构体|映射|堆与选择', text):
        return 'structures'
    return 'foundation'


def score(topic, stage, occurrences):
    if any(o['file'] == FILES['guide'] and o['page'] in (3, 4) for o in occurrences):
        return 5
    if re.search(r'必做|经典模板|背包|编辑距离|最短路|并查集|DFS|BFS|递归|拓扑|排序|数组|字符串基础', topic, re.I):
        return 5
    return {'foundation': 4, 'structures': 4, 'search': 4, 'algorithms': 4, 'dp': 4, 'graphs': 4, 'advanced': 3, 'challenge': 2}[stage]


def build():
    links, sections, local, cache = all_links(), read('template-sections.json'), read('local-templates.json'), read('luogu-cache.json')
    questions, unresolved = [], []
    indexes = {section['index']: section for section in sections}
    section_questions = {section['index']: [] for section in sections}
    alternate_map = {}
    for spec in local:
        source_sections = [indexes[index] for index in spec['sections']]
        occurrences = []
        for section in source_sections:
            section_questions[section['index']].append(spec['source_key'])
            for url in section['links']:
                alternate_map.setdefault(url.split('#')[0].rstrip('/'), []).append(spec['source_key'])
            occurrences.append({'file': FILES['templates'], 'page': section['page'], 'pages': section['pages'], 'anchor': section['title'], 'section': section['title']})
        urls = [u for section in source_sections for u in section['links'] if not PID.search(u)]
        url = next((u for u in urls if re.search(r'leetcode.cn/problems/|vjudge.net/problem/|acwing.com/problem/', u)), '')
        stage = stage_for(spec['topic'], title=spec['title'])
        # Local variants are explicitly adapters, never silently mapped to a remote judge.
        item = {key: value for key, value in spec.items() if key != 'sections'}
        item.update(stage_id=stage, position=0, source_url=url, remote_problem_id='', judge_mode='samples')
        item['source_info'] = {'file': FILES['templates'], 'pages': sorted({p for s in source_sections for p in s['pages']}),
            'kind': 'template_adapter', 'occurrences': occurrences, 'original_urls': list(dict.fromkeys(urls)),
            'reference_kind': 'runnable', 'reference_note': '本页 Python 3 参考程序通过全部公开样例；PDF 原代码另存为未验证片段，可能包含排版或算法错误。',
            'pdf_reference_code': '\n\n'.join(s['title']+'\n'+s['code'] for s in source_sections if s['code']),
            'pdf_reference_kind': 'pdf_excerpt', 'sample_origin': 'editorial_public_examples',
            'importance_note': '星级表示建议练习优先级，不是考试命中概率。'}
        questions.append(item)
    for pid in remote_ids(links):
        occurrences = [{k: v for k, v in link.items() if k != 'rect'} for link in links if (match := PID.search(link['url'])) and match[1].upper() == pid]
        metadata = cache.get(pid, {})
        if metadata.get('error') or not metadata.get('statement') or not metadata.get('samples'):
            unresolved.append({'problem_id': pid, 'occurrences': occurrences, 'reason': metadata.get('error', 'missing public metadata')})
            continue
        template_sections = [section for section in sections if any((match := PID.search(url)) and match[1].upper() == pid for url in section['links'])]
        for section in template_sections:
            section_questions[section['index']].append('luogu-'+pid.lower())
        guide_refs = [o for o in occurrences if o['file'] == FILES['guide'] and o.get('section', '').lower().startswith('day')]
        earliest = guide_refs[0] if guide_refs else occurrences[0]
        topic = re.sub(r'^[Dd]ay\d+\s*[:：]\s*', '', earliest.get('section', ''))
        if not topic or topic in ('历年题', '历史题与扩展'):
            topic = template_sections[0]['title'] if template_sections else '历年题与基础训练'
        stage = stage_for(topic, earliest.get('pdf_stage', ''), metadata['title'])
        difficulty = {'foundation': 1, 'structures': 2, 'search': 2, 'algorithms': 2, 'dp': 3, 'graphs': 3, 'advanced': 4, 'challenge': 5}[stage]
        # The original reference is preserved even when its anchor mislabels the target.
        warnings = []
        if any('排座椅' in o['anchor'] for o in occurrences) and pid == 'P1098':
            warnings.append('原 PDF 的“排座椅”链接实际指向 P1098 字符串的展开；本条采用目标页真实题名/题面。')
        reference = '\n\n'.join('// '+s['title']+'\n'+s['code'] for s in template_sections if s['code'])
        info = {'file': earliest['file'], 'pages': sorted({o['page'] for o in occurrences if o['file'] == earliest['file']}),
                'kind': 'remote_problem', 'occurrences': occurrences, 'original_urls': list(dict.fromkeys(o['url'] for o in occurrences)),
                'reference_kind': 'pdf_excerpt' if reference else 'none',
                'reference_note': 'PDF 原始代码摘录，可能包含多个程序、缺失上下文或错误；不是已验证可直接提交的标准答案。' if reference else '来源题单未提供该题的完整参考程序。',
                'sample_origin': 'luogu_public_problem_page', 'warnings': warnings,
                'importance_note': '难度与星级是本题库教学编排，不等同于洛谷官方等级或考试命中概率。'}
        questions.append({'source_key': 'luogu-'+pid.lower(), 'stage_id': stage, 'title': metadata['title'], 'topic': topic[:160],
                          'difficulty': difficulty, 'stars': score(topic, stage, occurrences), 'position': 0,
                          'statement': metadata['statement'], 'samples': metadata['samples'],
                          'reference_code': reference, 'reference_language': 'c' if reference else 'cpp11',
                          'source_url': f'https://www.luogu.com.cn/problem/{pid}', 'remote_problem_id': pid, 'judge_mode': 'luogu', 'source_info': info})
    rank = {key: index for index, (key, _, _) in enumerate(STAGES)}
    questions.sort(key=lambda q: (rank[q['stage_id']], q['difficulty'], -q['stars'], q['topic'], q['source_key']))
    counters = Counter()
    for question in questions:
        question['position'] = counters[question['stage_id']]
        counters[question['stage_id']] += 1
    stages = [{'id': key, 'title': title, 'description': desc, 'position': index} for index, (key, title, desc) in enumerate(STAGES)]
    catalog = {'version': 1, 'stages': stages, 'questions': questions}
    write('catalog.json', catalog)
    inventory = []
    for link in links:
        match = PID.search(link['url'])
        if match:
            keys = ['luogu-'+match[1].lower()]
            disposition = 'remote_problem' if match[1].upper() not in {x['problem_id'] for x in unresolved} else 'unresolved'
        elif re.search(r'leetcode.cn/problems/|vjudge.net/problem/|acwing.com/problem/', link['url']):
            keys = alternate_map.get(link['url'].split('#')[0].rstrip('/'), [])
            # The guide's three LeetCode links repeat template chapter references.
            if not keys:
                slug = re.search(r'leetcode.cn/problems/([^/]+)', link['url'])
                if slug:
                    keys = sorted({k for url, values in alternate_map.items() if '/'+slug[1]+'/' in url+'/' for k in values})
                    if slug[1] == 'eight-queens-lcci':
                        keys = [q['source_key'] for q in local if 12 in q['sections']]
            disposition = 'local_adapter' if keys else 'unresolved_alternate_reference'
            if not keys:
                # These source chapters pair equivalent arithmetic/counting tasks; I/O conventions differ.
                related = {'multiply-strings': 'luogu-p1303', 'shu-zu-zhong-de-ni-xu-dui-lcof': 'luogu-p1908'}
                slug = re.search(r'leetcode.cn/problems/([^/]+)', link['url'])
                if slug and slug[1] in related:
                    keys, disposition = [related[slug[1]]], 'related_reference'
        else:
            keys = []
            disposition = 'supporting_resource'
        inventory.append({**link, 'disposition': disposition, 'question_keys': keys})
    chapter_inventory = [{**{k: v for k, v in section.items() if k not in ('text', 'code', 'y')},
                          'kind': 'section_heading' if section['index'] in GROUP_SECTIONS else 'problem_or_template',
                          'question_keys': section_questions[section['index']]} for section in sections]
    unrepresented = [s for s in chapter_inventory if s['kind'] == 'problem_or_template' and not s['question_keys']]
    unresolved_alt = [link for link in inventory if link['disposition'] == 'unresolved_alternate_reference']
    report = {'version': 1, 'source_pages': {kind: len(read(f'{kind}-extracted.json')['pages']) for kind in FILES},
              'link_annotations': len(links), 'link_dispositions': dict(Counter(i['disposition'] for i in inventory)),
              'unique_luogu_ids': len(remote_ids(links)), 'seed_questions': len(questions),
              'judge_modes': dict(Counter(q['judge_mode'] for q in questions)), 'stages': dict(counters),
              'template_headings': len(sections), 'template_problem_sections': len(chapter_inventory)-len(GROUP_SECTIONS),
              'unrepresented_template_sections': unrepresented, 'unresolved_remote_problems': unresolved,
              'unresolved_alternate_references': unresolved_alt,
              'links': inventory, 'template_sections': chapter_inventory}
    write('source-inventory.json', report)
    return catalog, report


def verify(catalog):
    """Validate stable identifiers and execute only the authored local references."""
    keys, stage_ids = set(), {s['id'] for s in catalog['stages']}
    sample_count = 0
    for question in catalog['questions']:
        key = question['source_key']
        assert key not in keys, key
        keys.add(key)
        assert question['stage_id'] in stage_ids, key
        assert 1 <= question['stars'] <= 5 and 1 <= question['difficulty'] <= 5, key
        assert question['statement'] and question['samples'], key
        if question['judge_mode'] != 'samples':
            assert question['remote_problem_id'], key
            continue
        assert len(question['samples']) >= 3, key
        assert question['source_info']['reference_kind'] == 'runnable', key
        for index, sample in enumerate(question['samples']):
            result = subprocess.run([sys.executable, '-I', '-c', question['reference_code']],
                                    input=sample['input'], text=True, capture_output=True, timeout=10)
            expected = '\n'.join(line.rstrip() for line in sample['output'].rstrip().splitlines())
            actual = '\n'.join(line.rstrip() for line in result.stdout.rstrip().splitlines())
            if result.returncode or actual != expected:
                raise SystemExit(f'{key} sample {index+1} failed: {result.stderr or repr(result.stdout)}; expected {sample["output"]!r}')
            sample_count += 1
    print(f'Validated {len(keys)} questions; {sample_count} local reference/sample runs passed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract', action='store_true')
    parser.add_argument('--pdf-dir', type=Path, default=Path.home() / 'Downloads')
    parser.add_argument('--refresh', action='store_true', help='fetch missing/failed metadata, retain successful cache')
    parser.add_argument('--force-refresh', action='store_true', help='re-fetch successful metadata too')
    parser.add_argument('--workers', type=int, choices=range(1, 6), default=2)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    if args.extract:
        extract(args.pdf_dir)
    if args.refresh or args.force_refresh:
        refresh(remote_ids(all_links()), force=args.force_refresh, workers=args.workers)
    catalog, report = build()
    if args.verify:
        verify(catalog)
    summary = {k: v for k, v in report.items() if k not in ('links', 'template_sections')}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report['unrepresented_template_sections'] or report['unresolved_remote_problems'] or report['unresolved_alternate_references']:
        raise SystemExit('Some source entries remain unresolved; see source-inventory.json. No fabricated statements were added.')


if __name__ == '__main__':
    main()
