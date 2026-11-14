"""Rebuild curated training answers from locally supplied source documents.

Run with --downloads and --translations; source filenames and original numbering
are retained. Large numbered headings, not numbered answer lists, delimit items.
"""
import argparse
import difflib
import json
import re
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / 'app/assets/question-bank'
OUT = ROOT / 'app/assets/training'
SOURCES = [
    ('data_structures', 'data-structures', '专业课问答_ 数据结构八股.pdf', 33),
    ('operating_systems', 'operating-systems', '专业课问答_ 操作系统八股.pdf', 29),
    ('computer_networks', 'computer-networks', '专业课问答_  计算机网络八股.pdf', 34),
]


def clean(text):
    return text.replace('\u200b', '').replace('\ufeff', '').strip()


def normalize(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', clean(text)).lower()


def format_pdf_answer(text):
    """Reflow source-order lines; U+200B marks paragraph ends in supplied PDFs."""
    paragraphs, current = [], ''
    for raw in text.splitlines():
        line = re.sub(r'[ \t\u00a0]+', ' ', clean(raw))
        if not line:
            continue
        if re.match(r'^(?:[•●▪]|\d+[、）)]|\d+\.\s|[一二三四五六七八九十]+、)', line):
            if current:
                paragraphs.append(current)
            current = ''
        if current:
            separator = ' ' if current in ('•', '●', '▪') or (current[-1].isascii() and current[-1].isalnum() and line[0].isascii() and line[0].isalnum()) else ''
            current += separator + line
        else:
            current = line
        if raw.rstrip().endswith('\u200b') and current not in ('•', '●', '▪'):
            paragraphs.append(current)
            current = ''
    if current:
        paragraphs.append(current)
    return '\n\n'.join(paragraphs)


def professional(downloads):
    result, audit = [], []
    for collection, slug, filename, count in SOURCES:
        doc = pymupdf.open(downloads / filename)
        questions = json.loads((BANK / (slug + '.json')).read_text())
        headings = []
        for pno, page in enumerate(doc):
            lines = [line for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
            for index, line in enumerate(lines):
                text = clean(''.join(span['text'] for span in line['spans']))
                match = re.match(r'^(\d+)\.\s*(.+)', text)
                if not match or max(s['size'] for s in line['spans']) < 15:
                    continue
                number = int(match.group(1))
                title, bottom = match.group(2), line['bbox'][3]
                for continuation in lines[index + 1:]:
                    continuation_text = clean(''.join(s['text'] for s in continuation['spans']))
                    if min(s['size'] for s in continuation['spans']) < 15 or re.match(r'^\d+\.', continuation_text):
                        break
                    title += clean(''.join(s['text'] for s in continuation['spans']))
                    bottom = continuation['bbox'][3]
                headings.append((pno, line['bbox'][1], bottom, number, title))
        assert [h[3] for h in headings] == list(range(1, count + 1)), (slug, headings)
        assert len(questions) == count
        for index, (pno, top, bottom, number, title) in enumerate(headings):
            question = questions[index]['question']
            ratio = difflib.SequenceMatcher(None, normalize(title), normalize(question)).ratio()
            assert ratio >= .65, (slug, number, title, question, ratio)
            end_page, end_y = (headings[index + 1][0], headings[index + 1][1] - 3) if index + 1 < count else (len(doc) - 1, doc[-1].rect.height)
            texts, images, used_pages = [], [], []
            for page_number in range(pno, end_page + 1):
                page = doc[page_number]
                y0 = bottom + .5 if page_number == pno else 0
                y1 = end_y if page_number == end_page else page.rect.height
                if y1 - y0 < 8:
                    continue
                clip = pymupdf.Rect(0, y0, page.rect.width, y1)
                # PDF content order preserves inline spans and detached bullets;
                # coordinate sorting interleaves their different font baselines.
                text = page.get_text('text', clip=clip, sort=False)
                # Preserve original layout too: tables, formulas and diagrams do
                # not reliably survive plain-text extraction from these PDFs.
                if text or any(pymupdf.Rect(b['bbox']).intersects(clip) for b in page.get_text('dict')['blocks'] if b['type'] == 1):
                    texts.append(text)
                    name = f'{collection}-{number:02d}-p{page_number + 1:02d}.jpg'
                    page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), clip=clip).save(OUT / 'images' / name, jpg_quality=86)
                    images.append(name)
                    used_pages.append(page_number + 1)
            answer = format_pdf_answer('\n'.join(texts))
            if not answer and images:
                answer = '本题原文参考答案为图示，请展开下方原文对照查看。'
            assert answer, (slug, number)
            result.append(dict(source_key=questions[index]['id'], collection_id=collection, position=number,
                               question=question, answer=answer, images=images,
                               source=dict(file=filename, page_start=min(used_pages), page_end=max(used_pages), number=number)))
            audit.append(f'| {collection} | {number} | {min(used_pages)}–{max(used_pages)} | {ratio:.3f} | {len(images)} | {question} |')
    return result, audit


def english(path):
    lines = [clean(line) for line in path.read_text().splitlines() if clean(line) and not re.fullmatch(r'[-—*_\s]+', clean(line))]
    assert len(lines) == 62, len(lines)
    translations = json.loads((BANK / 'english-translation.json').read_text())
    oral = json.loads((BANK / 'english-oral.json').read_text())
    result = []
    for i, item in enumerate(translations):
        source_question, answer = lines[i * 2:i * 2 + 2]
        ratio = difflib.SequenceMatcher(None, normalize(source_question), normalize(item['question'])).ratio()
        assert ratio > .97, (i + 1, ratio)
        assert re.search(r'[\u4e00-\u9fff]', answer)
        result.append(dict(source_key=item['id'], collection_id='translation', position=i + 1,
                           question=item['question'], answer=answer, images=[],
                           source=dict(file='用户提供的英文翻译与中文译文', number=i + 1)))
    for i, item in enumerate(oral):
        result.append(dict(source_key=f'oral-{i + 1:03d}', collection_id='oral', position=i + 1,
                           question=item, answer='', images=[],
                           source=dict(file='用户提供的历年英文口语题与前沿热点题', number=i + 1)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--translations', type=Path, required=True)
    args = parser.parse_args()
    (OUT / 'images').mkdir(parents=True, exist_ok=True)
    items, audit = professional(args.downloads)
    items.extend(english(args.translations))
    assert len(items) == 180 and len({i['source_key'] for i in items}) == 180
    (OUT / 'catalog.json').write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n')
    report = '# 每日训练来源核对\n\n共180题：专业课96题、翻译31题、英文问答53题。专业课按16.5pt大标题顺序切分，答案内12pt编号不作为题目；所有题目编号与既有题库一一核对。\n\n可复制文本按 PDF 内容流顺序抽取，依据原文段落结束标记合并软换行，保留项目符号；不使用会打乱不同字体基线的坐标排序。每道专业课参考答案保留重排文本与逐页原文裁片，完整保留表格、公式与图示。页面裁片不包含下一题标题或答案；图像仅在用户展开原文对照后加载。英文翻译按31对原文/译文验证，词嵌入第17段的空格修正经规范化匹配通过。英文问答不补写答案。\n\n数据结构原文第3、4题的“数的”笔误沿用已有“数据的”题干；计网第16、28题包括换行标题。参考内容来自用户材料，不声明为学校官方标准答案。\n\n| 集合 | 原题号 | 答案页 | 标题相似度 | 原文裁片数 | 题干 |\n| --- | ---: | --- | ---: | ---: | --- |\n' + '\n'.join(audit) + '\n'
    (ROOT / 'docs/training-source-audit.md').write_text(report)
    print(f'Wrote {len(items)} questions, {sum(len(i["images"]) for i in items)} reference page crops.')


if __name__ == '__main__':
    main()
