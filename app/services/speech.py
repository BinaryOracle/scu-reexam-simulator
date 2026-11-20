"""Persist synthesized audio; fixed prompts share audio, expert audio belongs to its interview."""
import hashlib
import json
from pathlib import Path
from filelock import FileLock, Timeout
from fastapi import HTTPException
from app.config import load_config
from app.db import connect
from app.services import ai
from app.services import model_settings


def cached(text, *, interview_id=None):
    """Reuse audio across restarts; serialize concurrent misses without holding a database transaction."""
    config = load_config()
    tts = model_settings.resolve('tts', config)
    if not tts['enabled']:
        raise HTTPException(503, '语音播报暂未启用，可直接阅读题目')
    settings = {key: tts[key] for key in
                ('provider', 'protocol', 'base_url', 'model', 'voice', 'format', 'sample_rate', 'language_type')}
    payload = json.dumps([1, interview_id, text, settings], sort_keys=True, ensure_ascii=False)
    key = hashlib.sha256(payload.encode()).hexdigest()
    # A bounded set of OS file locks also coordinates multiple server workers.
    locks = Path(config['app']['database']).parent / '.speech-locks'
    locks.mkdir(parents=True, exist_ok=True)
    lock = FileLock(locks / f'{key[:2]}.lock', timeout=tts['cache_lock_timeout_seconds'])
    try:
        with lock:
            with connect() as db:
                row = db.execute('SELECT content,mime_type FROM speech_cache WHERE cache_key=?', (key,)).fetchone()
            if row:
                return ai._audio_result(row['content'], row['mime_type'], tts['max_audio_mb'] * 1024 * 1024)
            content, mime = ai.synthesize(text)
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if interview_id is not None and not db.execute('SELECT 1 FROM interviews WHERE id=?', (interview_id,)).fetchone():
                    raise HTTPException(404, '面试不存在')
                db.execute('INSERT INTO speech_cache VALUES (?,?,?,?)', (key, interview_id, content, mime))
            return content, mime
    except Timeout as error:
        raise HTTPException(503, '语音正在准备中，请稍后重试') from error
