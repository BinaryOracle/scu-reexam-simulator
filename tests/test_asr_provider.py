"""Aliyun ASR receives converted audio and never exposes its credential in errors."""
import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest


def audio_file(tmp_path):
    path = tmp_path / 'speech.webm'
    subprocess.run([
        'ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'anullsrc=r=16000:cl=mono', '-t', '0.1', '-c:a', 'libopus', '-y', str(path),
    ], check=True)
    return path


def test_aliyun_asr_posts_wav_data_uri_to_workspace_endpoint(tmp_path, monkeypatch):
    from app.services import ai
    secret = 'local-test-key'
    monkeypatch.setattr(ai, 'load_config', lambda: {'asr': {
        'api_key': secret, 'api_key_env': 'UNUSED', 'base_url': 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen3-asr-flash', 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10,
        'request_timeout_seconds': 10,
    }})
    captured = {}
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices': [{'message': {'content': '已识别语音'}}]}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.transcribe(audio_file(tmp_path)) == '已识别语音'
    assert captured['url'] == 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions'
    assert captured['headers']['Authorization'] == f'Bearer {secret}'
    assert captured['json']['model'] == 'qwen3-asr-flash'
    uri = captured['json']['messages'][0]['content'][0]['input_audio']['data']
    assert uri.startswith('data:audio/wav;base64,')
    assert base64.b64decode(uri.partition(',')[2]).startswith(b'RIFF')
    assert captured['json']['asr_options']['enable_itn'] is True


def test_aliyun_credentials_are_not_in_provider_error(tmp_path, monkeypatch):
    from app.services import ai
    secret = 'local-test-key'
    monkeypatch.setattr(ai, 'load_config', lambda: {'asr': {
        'api_key': secret, 'api_key_env': 'UNUSED', 'base_url': 'https://workspace.invalid/v1',
        'model': 'qwen3-asr-flash', 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10,
        'request_timeout_seconds': 10,
    }})
    def fail(*args, **kwargs):
        request = httpx.Request('POST', args[0])
        response = httpx.Response(401, request=request, text=secret)
        raise httpx.HTTPStatusError('bad', request=request, response=response)
    monkeypatch.setattr(ai.httpx, 'post', fail)
    with pytest.raises(Exception) as error:
        ai.transcribe(audio_file(tmp_path))
    assert secret not in str(error.value)
    assert 'HTTP 401' in str(error.value)


def test_aliyun_asr_splits_long_wav_and_joins_transcripts(tmp_path, monkeypatch):
    from app.services import ai
    monkeypatch.setattr(ai, 'load_config', lambda: {'asr': {
        'api_key': 'secret', 'api_key_env': 'UNUSED', 'base_url': 'https://provider.test/v1',
        'model': 'qwen3-asr-flash', 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10,
        'request_timeout_seconds': 10, 'max_segment_seconds': 1,
    }})
    path = tmp_path / 'long.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=16000', '-t', '2.1', '-y', str(path)], check=True)
    captured = []
    def post(url, **kwargs):
        import io, wave
        audio = kwargs['json']['messages'][0]['content'][0]['input_audio']['data']
        with wave.open(io.BytesIO(base64.b64decode(audio.partition(',')[2]))) as wav:
            assert wav.getnframes() <= 16000
        captured.append(audio)
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'choices': [{'message': {'content': f'片段{len(captured)}'}}]})
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.transcribe(path) == '片段1\n片段2\n片段3'
    assert len(captured) == 3


@pytest.mark.parametrize('status,code,message,expected', [
    (404, 'model_not_supported', 'secret', '模型'),
    (400, 'InvalidParameter', 'audio duration exceeds limit secret', '时长'),
    (400, 'InvalidParameter', 'invalid audio format secret', '格式'),
    (429, 'RateLimit', 'secret', '繁忙'),
    (401, 'InvalidApiKey', 'secret', '密钥'),
])
def test_asr_reports_actionable_safe_error_categories(tmp_path, monkeypatch, status, code, message, expected):
    from app.services import ai
    monkeypatch.setattr(ai, 'load_config', lambda: {'asr': {
        'api_key': 'secret', 'api_key_env': 'UNUSED', 'base_url': 'https://provider.test/v1',
        'model': 'qwen3-asr-flash', 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10,
        'request_timeout_seconds': 10,
    }})
    monkeypatch.setattr(ai.httpx, 'post', lambda url, **kw: httpx.Response(status,
        request=httpx.Request('POST', url), json={'error': {'code': code, 'message': message}}))
    with pytest.raises(Exception) as error:
        ai.transcribe(audio_file(tmp_path))
    assert expected in str(error.value)
    assert 'secret' not in str(error.value)


def test_asr_accepts_empty_transcript_for_silence(tmp_path, monkeypatch):
    from app.services import ai
    monkeypatch.setattr(ai, 'load_config', lambda: {'asr': {
        'api_key': 'secret', 'api_key_env': 'UNUSED', 'base_url': 'https://provider.test/v1',
        'model': 'qwen3-asr-flash', 'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10,
        'request_timeout_seconds': 10,
    }})
    monkeypatch.setattr(ai.httpx, 'post', lambda url, **kw: httpx.Response(200,
        request=httpx.Request('POST', url), json={'choices': [{'message': {'content': ''}}]}))
    assert ai.transcribe(audio_file(tmp_path)) == ''
