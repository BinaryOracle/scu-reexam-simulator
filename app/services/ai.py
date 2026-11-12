import os
import httpx
from fastapi import HTTPException
from app.config import load_config

def chat(prompt):
    cfg = load_config()['ai']
    key = os.getenv(cfg['api_key_env'])
    if not key:
        raise HTTPException(503, '未配置 AI 服务密钥')
    try:
        response = httpx.post(cfg['base_url'].rstrip('/') + '/chat/completions', headers={'Authorization': 'Bearer ' + key}, json={'model': cfg['model'], 'messages': [{'role': 'user', 'content': prompt}]}, timeout=60)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        raise HTTPException(502, 'AI 服务不可用') from e

def transcribe(path):
    cfg = load_config()['asr']
    key = os.getenv(cfg['api_key_env'])
    if not key or not cfg['base_url']:
        raise HTTPException(503, '未配置语音识别服务，录音已保存')
    try:
        with open(path, 'rb') as audio:
            response = httpx.post(cfg['base_url'].rstrip('/') + '/audio/transcriptions', headers={'Authorization': 'Bearer ' + key}, data={'model': cfg['model']}, files={'file': (path.name, audio, 'audio/webm')}, timeout=120)
        response.raise_for_status()
        return response.json()['text']
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise HTTPException(502, '语音识别失败，录音已保存') from e
