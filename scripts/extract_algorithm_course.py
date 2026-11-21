"""Regenerate the offline lesson assets from the four chapters of the source PDF."""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pymupdf as pdf


DIRECTORY = Path(__file__).resolve().parents[1] / 'app/assets/courses/algorithm-beginner'
RADICALS = str.maketrans({chr(cp): unicodedata.normalize('NFKC', chr(cp))
                          for cp in range(0x2f00, 0x2fd6)})
RADICALS.update(str.maketrans('⻓⻅⻋⻚⻄⺟⻜⻦⺠⻘', '长见车页西母飞鸟民青'))
CODE_BACKGROUND = (247 / 255,) * 3


def clean(text):
    return text.translate(RADICALS)


def text_line(line, code=False):
    parts = []
    for span in line['spans']:
        value = clean(span['text'])
        if not code and 'Mono' in span['font'] and value.strip():
            value = ' `' + value.strip().replace('`', '``') + '` '
        parts.append(value)
    return ''.join(parts)


def page_elements(page):
    """Use the printed code backgrounds to distinguish blocks from inline identifiers."""
    boxes = [item['rect'] for item in page.get_drawings() if item.get('fill')
             and all(abs(actual - expected) < 1e-5 for actual, expected in zip(item['fill'], CODE_BACKGROUND))
             and item['rect'].width > 300]
    flags = pdf.TEXTFLAGS_DICT & ~pdf.TEXT_PRESERVE_IMAGES
    events, code_lines = [], [[] for _ in boxes]
    for block in page.get_text('dict', flags=flags)['blocks']:
        for line in block['lines']:
            raw = text_line(line, code=True)
            x, y, _, bottom = line['bbox']
            if not raw.strip() or y < 66 or y > 782:
                continue
            box = next((i for i, rect in enumerate(boxes)
                        if rect.x0 <= x < rect.x1 and rect.y0 <= y <= rect.y1
                        and all('Mono' in s['font'] for s in line['spans'])), None)
            if box is not None:
                code_lines[box].append((y, raw.rstrip()))
                continue
            bold = all('Bold' in span['font'] for span in line['spans'])
            large = max(span['size'] for span in line['spans'])
            kind = 'title' if large >= 25 and y < 135 else 'heading' if bold and large >= 16 else 'text'
            events.append((y, bottom, kind, text_line(line).strip(), None))
    for box, rows in zip(boxes, code_lines):
        if not rows:
            continue
        lines, previous = [], None
        for y, content in sorted(rows):
            if previous is not None and y - previous > 24:
                lines.append('')
            lines.append(content)
            previous = y
        events.append((max(box.y0, 70), box.y1, 'code', '\n'.join(lines), box))
    for index, image in enumerate(page.get_image_info(), 1):
        size = (image['width'], image['height'])
        if size in {(2320, 324), (258, 258)}:
            continue  # banner and follow QR code
        box = pdf.Rect(image['bbox'])
        events.append((box.y0, box.y1, 'image', f'p{page.number + 1}-{index}.webp', box))
    return sorted(events, key=lambda item: item[0])


def lesson_markdown(document, first, last, figures):
    output, paragraph = [], []
    previous_bottom, previous_code = None, None
    omitted, in_footer, skip_animation_filename = False, False, False

    def flush():
        if paragraph:
            output.append(''.join(paragraph))
            paragraph.clear()

    for number in range(first, last + 1):
        for y, bottom, kind, value, box in page_elements(document[number - 1]):
            if kind == 'title' or re.fullmatch(r'学好?算法.*认准.*labuladong.*', value):
                continue
            if re.match(r'[_＿]{5,}$|^刷算法[，,]学套路|^本文由公众号|^后台回复', value):
                flush()
                if re.match(r'^刷算法|^本文由公众号|^后台回复', value):
                    in_footer = True
                continue
            if '由于格式原因' in value and '公众号' in value:
                flush()
                omitted, in_footer = True, True
                continue
            if in_footer:
                continue
            if skip_animation_filename:
                skip_animation_filename = False
                if '可移步' in value or '.gif' in value.lower():
                    continue
            if 'PDF格式无法显示' in value and 'GIF' in value:
                flush()
                output.append('> 原 PDF 未包含此处的动画。')
                skip_animation_filename = '】' not in value
                continue
            if any(word in value for word in ('可移步公众号查看】', '可移步公众号中查看】')):
                paragraph.clear()
                continue
            if kind == 'code':
                flush()
                if previous_code and previous_code[0] == number - 1 and box.y0 < 65:
                    index, start, old = previous_code[1:]
                    value = old + '\n' + value
                    del output[index:]
                else:
                    index, start = len(output), number
                label = str(number) if start == number else f'{start}–{number}'
                fence = '`' * max(3, 1 + max((len(m[0]) for m in re.finditer(r'`+', value)), default=0))
                output.append(f'::: code\n第 {label} 页 · PDF 原文摘录\n\n{fence}text\n{value}\n{fence}\n:::')
                previous_code = (number, index, start, value) if box.y1 > 790 else None
            elif kind == 'image':
                flush()
                if not (figures / value).is_file():
                    page = document[number - 1]
                    pixmap = page.get_pixmap(matrix=pdf.Matrix(1.6, 1.6), clip=box, alpha=False)
                    pixmap.pil_save(figures / value, format='WEBP', lossless=True)
                output.append(f'![原书第 {number} 页插图](figure:{value})')
                previous_code = None
            else:
                previous_code = None
                if kind == 'heading':
                    flush()
                    output.append('### ' + value)
                else:
                    if (previous_bottom is None or y - previous_bottom > 13
                            or re.match(r'^(?:[-•]|\d+[、.])\s*', value)):
                        flush()
                    if paragraph and paragraph[-1] and paragraph[-1][-1:].isascii() and value[:1].isascii():
                        paragraph.append(' ')
                    paragraph.append(value)
            previous_bottom = bottom
        # Keep a wrapped sentence joined across printed page breaks.
        previous_bottom = 73 if previous_bottom is not None and previous_bottom > 745 else None
    flush()
    if omitted:
        output.insert(0, '> PDF 未收录完整正文。以下只保留原书可读的部分。')
    return '\n\n'.join(output).strip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    args = parser.parse_args()
    catalog = json.loads((DIRECTORY / 'catalog.json').read_text(encoding='utf-8'))
    with args.pdf.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != catalog['source_sha256']:
        parser.error('PDF does not match the edition identified in catalog.json')
    figures = DIRECTORY / 'figures'
    figures.mkdir(exist_ok=True)
    with pdf.open(args.pdf) as document:
        for section in catalog['sections']:
            for lesson in section['lessons']:
                first, last = lesson['pages']
                markdown = lesson_markdown(document, first, last, figures)
                if not markdown.strip():
                    raise ValueError(f'No readable content on pages {first}–{last}')
                (DIRECTORY / lesson['document']).write_text(markdown, encoding='utf-8')


if __name__ == '__main__':
    main()
