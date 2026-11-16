"""Multimodal prompts and speech use configured providers without exposing secrets."""
import base64
from contextlib import nullcontext
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from app.services import ai


def config(monkeypatch, **sections):
    monkeypatch.setattr(ai, 'load_config', lambda: sections)


def test_chat_separates_role_from_untrusted_media_and_uses_omni_text_mode(monkeypatch):
    config(monkeypatch, ai={'api_key': 'secret', 'api_key_env': 'UNUSED',
        'base_url': 'https://provider.test/compatible-mode/v1', 'model': 'qwen3.8-omni-flash',
        'request_timeout_seconds': 90})
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': [{'type': 'text', 'text': '专家问题'}]}}]})
    monkeypatch.setattr(ai.httpx, 'post', post)
    media = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,aGVsbG8='}}]
    assert ai.chat('用户材料', system='只担任面试专家', media=media) == '专家问题'
    payload = captured['json']
    assert payload['messages'] == [{'role': 'system', 'content': '只担任面试专家'},
        {'role': 'user', 'content': [{'type': 'text', 'text': '用户材料'}, *media]}]
    assert payload['modalities'] == ['text']
    assert payload['reasoning_effort'] == 'none'
    assert payload['stream'] is False
    assert captured['timeout'] == 90
    assert media[0]['type'] == 'image_url'


def test_chat_preserves_plain_text_api_and_uses_configured_secret(monkeypatch):
    config(monkeypatch, ai={'api_key': 'secret', 'api_key_env': 'UNUSED',
        'base_url': 'https://provider.test/v1', 'model': 'plain-model', 'request_timeout_seconds': 90})
    def post(url, **kwargs):
        assert kwargs['headers']['Authorization'] == 'Bearer secret'
        assert kwargs['json']['messages'] == [{'role': 'user', 'content': '问题'}]
        assert 'reasoning_effort' not in kwargs['json']
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'choices': [{'message': {'content': '回答'}}]})
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.chat('问题') == '回答'


def test_chat_can_select_a_separate_configured_feature_model(monkeypatch):
    config(monkeypatch, ai={'api_key': 'secret', 'api_key_env': 'UNUSED',
        'base_url': 'https://provider.test/v1', 'model': 'qwen3.8-omni-flash', 'request_timeout_seconds': 90})
    captured = {}
    def post(url, **kwargs):
        captured.update(kwargs)
        assert kwargs['json']['model'] == 'qwen3.8-flash'
        assert 'modalities' not in kwargs['json']
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'choices': [{'message': {'content': '趋势'}}]})
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.chat('汇总来源', model='qwen3.8-flash', request_timeout_seconds=45) == '趋势'
    assert captured['timeout'] == 45


def test_chat_reports_provider_read_timeouts_as_gateway_timeout(monkeypatch):
    config(monkeypatch, ai={'api_key': 'secret', 'api_key_env': 'UNUSED',
        'base_url': 'https://provider.test/v1', 'model': 'plain-model', 'request_timeout_seconds': 90})

    def post(url, **kwargs):
        raise httpx.ReadTimeout('provider response timed out', request=httpx.Request('POST', url))

    monkeypatch.setattr(ai.httpx, 'post', post)
    with pytest.raises(HTTPException) as error:
        ai.chat('汇总趋势')

    assert error.value.status_code == 504
    assert '费用以阿里云用量记录为准' in error.value.detail


def tts_config(monkeypatch, **overrides):
    cfg = {'enabled': True, 'provider': 'dashscope', 'api_key': 'secret', 'api_key_env': 'UNUSED',
        'base_url': 'https://provider.test/api/v1', 'model': 'qwen-audio-3.1-tts-plus',
        'voice': 'Cherry', 'language_type': 'Chinese', 'request_timeout_seconds': 60,
        'max_audio_mb': 1, 'download_hosts': ['audio.test'], 'protocol': 'dashscope_native'}
    cfg.update(overrides)
    config(monkeypatch, tts=cfg)


def test_dashscope_tts_downloads_only_trusted_https_audio(monkeypatch):
    tts_config(monkeypatch)
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'output': {'audio': {'url': 'https://audio.test/speech.wav'}}})
    def stream(method, url, **kwargs):
        assert method == 'GET'
        assert url == 'https://audio.test/speech.wav'
        assert kwargs['follow_redirects'] is False
        return nullcontext(httpx.Response(200, request=httpx.Request('GET', url), headers={'content-type': 'audio/wav'}, content=b'RIFFaudio'))
    monkeypatch.setattr(ai.httpx, 'post', post)
    monkeypatch.setattr(ai.httpx, 'stream', stream)
    assert ai.synthesize('请介绍你的项目') == (b'RIFFaudio', 'audio/wav')
    assert captured['url'].endswith('/services/aigc/multimodal-generation/generation')
    assert captured['json']['model'] == 'qwen-audio-3.1-tts-plus'
    assert captured['json']['input'] == {'text': '请介绍你的项目', 'voice': 'Cherry', 'language_type': 'Chinese'}


def test_dashscope_audio_speech_synthesizer_uses_configured_workspace_endpoint(monkeypatch):
    tts_config(monkeypatch, protocol='dashscope_audio',
        base_url='https://workspace-id.cn-beijing.maas.aliyuncs.com/api/v1',
        model='qwen-audio-3.1-tts-plus', voice='longanhuan_v3.1')
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'output': {'audio': {'url': 'https://audio.test/speech.wav'}}})
    def stream(method, url, **kwargs):
        return nullcontext(httpx.Response(200, request=httpx.Request('GET', url),
            headers={'content-type': 'audio/wav'}, content=b'RIFFaudio'))
    monkeypatch.setattr(ai.httpx, 'post', post)
    monkeypatch.setattr(ai.httpx, 'stream', stream)
    assert ai.synthesize('请介绍你的项目') == (b'RIFFaudio', 'audio/wav')
    assert captured['url'] == 'https://workspace-id.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer'
    assert captured['json'] == {'model': 'qwen-audio-3.1-tts-plus', 'input': {
        'text': '请介绍你的项目', 'voice': 'longanhuan_v3.1', 'format': 'wav', 'sample_rate': 24000}}


def test_dashscope_audio_protocol_requires_explicit_workspace_endpoint(monkeypatch):
    tts_config(monkeypatch, protocol='dashscope_audio', base_url='')
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert error.value.status_code == 503


def test_dashscope_audio_accepts_official_shared_endpoint(monkeypatch):
    tts_config(monkeypatch, protocol='dashscope_audio',
        base_url='https://dashscope.aliyuncs.com/api/v1', voice='longanhuan_v3.1')
    def post(url, **kwargs):
        assert url == 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer'
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'output': {'audio': {'url': 'https://audio.test/speech.wav'}}})
    monkeypatch.setattr(ai.httpx, 'post', post)
    monkeypatch.setattr(ai.httpx, 'stream', lambda method, url, **kw: nullcontext(
        httpx.Response(200, request=httpx.Request(method, url),
            headers={'content-type': 'audio/wav'}, content=b'RIFFaudio')))
    assert ai.synthesize('请介绍你的项目') == (b'RIFFaudio', 'audio/wav')


@pytest.mark.parametrize('base_url', [
    'http://workspace.cn-beijing.maas.aliyuncs.com/api/v1',
    'https://dashscope.aliyuncs.com.evil.test/api/v1',
    'https://workspace.cn-beijing.maas.aliyuncs.com:444/api/v1',
    'https://user@workspace.cn-beijing.maas.aliyuncs.com/api/v1',
])
def test_dashscope_audio_protocol_rejects_untrusted_workspace_endpoint(monkeypatch, base_url):
    tts_config(monkeypatch, protocol='dashscope_audio', base_url=base_url)
    monkeypatch.setattr(ai.httpx, 'post', lambda *a, **kw: pytest.fail('invalid workspace host was contacted'))
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert error.value.status_code == 503


def test_tts_upgrades_trusted_audio_url_without_requesting_plain_http(monkeypatch):
    tts_config(monkeypatch)
    def stream(method, url, **kwargs):
        assert url == 'https://audio.test/speech.wav?signature=preserved'
        return nullcontext(httpx.Response(200, request=httpx.Request(method, url),
            headers={'content-type': 'audio/wav'}, content=b'RIFFaudio'))
    monkeypatch.setattr(ai.httpx, 'stream', stream)
    assert ai._download_speech('http://audio.test/speech.wav?signature=preserved',
        {'download_hosts': ['audio.test'], 'request_timeout_seconds': 60}, 1024) == (b'RIFFaudio', 'audio/wav')


@pytest.mark.parametrize('url', ['http://untrusted.test/a.wav', 'https://127.0.0.1/a.wav',
    'https://audio.test.evil.test/a.wav', 'https://secret@audio.test/a.wav', 'https://audio.test:444/a.wav'])
def test_tts_rejects_untrusted_audio_urls(monkeypatch, url):
    tts_config(monkeypatch)
    monkeypatch.setattr(ai.httpx, 'post', lambda endpoint, **kw: httpx.Response(200,
        request=httpx.Request('POST', endpoint), json={'output': {'audio': {'url': url}}}))
    monkeypatch.setattr(ai.httpx, 'stream', lambda *a, **kw: pytest.fail('untrusted URL was downloaded'))
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert error.value.status_code == 502


def test_tts_bounded_download_and_provider_errors(monkeypatch):
    tts_config(monkeypatch)
    monkeypatch.setattr(ai.httpx, 'post', lambda endpoint, **kw: httpx.Response(200,
        request=httpx.Request('POST', endpoint), json={'output': {'audio': {'url': 'https://audio.test/a.wav'}}}))
    monkeypatch.setattr(ai.httpx, 'stream', lambda method, url, **kw: nullcontext(httpx.Response(200,
        request=httpx.Request(method, url), headers={'content-length': str(2 * 1024 * 1024)}, content=b'x')))
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert '大小' in error.value.detail


def test_openai_tts_returns_native_audio_and_does_not_use_download(monkeypatch):
    tts_config(monkeypatch, provider='openai', base_url='https://provider.test/v1')
    def post(url, **kwargs):
        assert url == 'https://provider.test/v1/audio/speech'
        assert kwargs['json']['input'] == '问题'
        return httpx.Response(200, request=httpx.Request('POST', url),
            headers={'content-type': 'audio/mpeg'}, content=b'mp3audio')
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.synthesize('问题') == (b'mp3audio', 'audio/mpeg')


def test_media_audio_combines_local_recordings_into_one_small_mp3(tmp_path, monkeypatch):
    config(monkeypatch, ai={'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10, 'max_audio_mb': 1})
    paths = []
    for number in range(2):
        path = tmp_path / f'{number}.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=16000', '-t', '0.1', '-y', str(path)], check=True)
        paths.append(path)
    media = ai.media_audio(paths)
    assert len(media) == 1
    audio = media[0]['input_audio']
    assert audio['format'] == 'mp3'
    assert audio['data'].startswith('data:audio/mp3;base64,')
    decoded = base64.b64decode(audio['data'].partition(',')[2])
    assert decoded.startswith(b'ID3') or decoded.startswith(b'\xff')
    assert len(decoded) < 1024 * 1024
    assert ai.media_audio([]) == []


def test_tts_stream_limit_applies_without_content_length(monkeypatch):
    tts_config(monkeypatch)
    monkeypatch.setattr(ai.httpx, 'post', lambda endpoint, **kw: httpx.Response(200,
        request=httpx.Request('POST', endpoint), json={'output': {'audio': {'url': 'https://audio.test/a.wav'}}}))
    monkeypatch.setattr(ai.httpx, 'stream', lambda method, url, **kw: nullcontext(httpx.Response(200,
        request=httpx.Request(method, url), headers={'content-type': 'audio/wav'}, content=b'x' * (1024 * 1024 + 1))))
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert '大小' in error.value.detail


def test_tts_model_error_does_not_expose_credentials_or_download_url(monkeypatch):
    tts_config(monkeypatch)
    monkeypatch.setattr(ai.httpx, 'post', lambda endpoint, **kw: httpx.Response(400,
        request=httpx.Request('POST', endpoint), json={'code': 'InvalidParameter',
        'message': 'Model qwen-audio-3.1-tts-plus is not supported, secret'}))
    with pytest.raises(HTTPException) as error:
        ai.synthesize('问题')
    assert '模型' in error.value.detail
    assert 'secret' not in error.value.detail


def test_media_audio_rejects_large_output(tmp_path, monkeypatch):
    config(monkeypatch, ai={'ffmpeg': 'ffmpeg', 'conversion_timeout_seconds': 10, 'max_audio_mb': 0.0001})
    path = tmp_path / 'speech.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'sine=frequency=440:sample_rate=16000', '-t', '0.1', '-y', str(path)], check=True)
    with pytest.raises(HTTPException) as error:
        ai.media_audio([path])
    assert error.value.status_code == 413
