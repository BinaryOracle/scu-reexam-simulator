"""Curated source mappings keep complete references and oral prompts without answers."""
import json
from collections import Counter
from pathlib import Path


def test_training_seed_counts_and_source_media():
    root = Path('app/assets/training')
    data = json.loads((root / 'catalog.json').read_text())
    assert Counter(q['collection_id'] for q in data) == {
        'data_structures': 33, 'operating_systems': 29, 'computer_networks': 34, 'translation': 31, 'oral': 53}
    assert len({q['source_key'] for q in data}) == 180
    for row in data:
        assert row['question'].strip()
        assert row['position'] > 0 and row['source']['number'] == row['position']
        if row['collection_id'] == 'oral':
            assert row['answer'] == '' and row['images'] == []
        else:
            assert row['answer'].strip()
        for name in row['images']:
            assert Path(name).name == name
            assert (root / 'images' / name).stat().st_size > 500
    diagram = next(q for q in data if q['collection_id'] == 'operating_systems' and q['position'] == 8)
    assert diagram['images']
    assert '图示' in diagram['answer']
    first = next(q for q in data if q['collection_id'] == 'data_structures' and q['position'] == 1)
    assert first['source']['page_end'] > first['source']['page_start']
    translation = next(q for q in data if q['collection_id'] == 'translation' and q['position'] == 17)
    assert 'Word representations' in translation['question']
    assert '词' in translation['answer']


def test_pdf_answer_restores_paragraphs_and_detached_bullets():
    from scripts.extract_training_bank import format_pdf_answer
    raw = ('路由器根据转发表将用户的IP 数据报从合适的端口转发出去，路由表是根据路由选择\n'
           '算法得出的。\u200b\n•\n路由选择。根据网络拓扑的变化情\n况，改变路由。\u200b\n'
           '•\n分组转发。转发数据报。\u200b\nA network protocol\n'
           'specifies communication rules.\u200b\n')
    assert format_pdf_answer(raw) == (
        '路由器根据转发表将用户的IP 数据报从合适的端口转发出去，路由表是根据路由选择算法得出的。\n\n'
        '• 路由选择。根据网络拓扑的变化情况，改变路由。\n\n'
        '• 分组转发。转发数据报。\n\nA network protocol specifies communication rules.')


def test_router_reference_keeps_reading_order_and_natural_paragraphs():
    data = json.loads(Path('app/assets/training/catalog.json').read_text())
    answer = next(q['answer'] for q in data if q['source_key'] == 'computer_networks-17')
    assert '当一个分组到达时所采取的动作' in answer
    assert '• 路由选择。' in answer
    assert '• 分组转发。指路由器根据转发表将用户的IP 数据报从合适的端口转发出去。路由表是根据路由选择算法得出的' in answer
    assert len(answer.split('\n\n')) == 3
