"""Persistent interview timing; only the server decides whether writes are allowed."""
import math
import time
from fastapi import HTTPException
from app.config import load_config


def timestamp():
    return time.time()


def timing(item):
    """Project the current state without a scheduler or a database mutation on reads."""
    now = timestamp()
    config = load_config()['interview']
    timed = item['workflow_version'] >= 3
    started, deadline = item['started_at'], item['deadline_at']
    duration = round(deadline - started) if timed and started is not None else config['duration_seconds']
    end = item['ended_at'] if item['ended_at'] is not None else now
    expired = bool(timed and deadline is not None and end >= deadline)
    status = item['status']
    if timed and status == 'active':
        status = 'preparing' if started is None else 'expired' if expired else 'active'
    return {'status': status, 'server_time': now, 'duration_seconds': duration,
            'warning_seconds': min(config['warning_seconds'], duration), 'timed_out': expired,
            'remaining_seconds': max(0, math.ceil(deadline - end)) if timed and deadline is not None else None}


def require_running(item):
    """Reject early and late writes, including the result of a long external call."""
    if item['workflow_version'] < 3:
        return
    if item['started_at'] is None:
        raise HTTPException(409, '请先点击「开始本轮面试」，确认后开始十分钟计时')
    if timestamp() >= item['deadline_at']:
        raise HTTPException(409, '面试时间已到，已停止作答；可查看已保存内容并生成点评')
