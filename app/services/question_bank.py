"""Random selection and administration helpers for interview question banks."""
import random
from fastapi import HTTPException

LABELS = {
    'data_structures': '数据结构',
    'operating_systems': '操作系统',
    'computer_networks': '计算机网络',
}


def choose_question(db, category, subject=''):
    """Choose one active question from the requested category and subject."""
    rows = db.execute('''SELECT id,content FROM question_bank
        WHERE category=? AND subject=? AND active=1 ORDER BY id''', (category, subject)).fetchall()
    if not rows:
        raise HTTPException(409, '该题库暂无可用题目，请联系管理员维护题库')
    return random.choice(rows)
