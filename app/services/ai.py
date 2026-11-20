"""Configured multimodal chat, bounded speech synthesis, and chunked transcription."""
import base64
import io
import os
import shutil
import subprocess
import tempfile
import wave
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException
from app.config import load_config
from app.services import model_settings


def _key(cfg, service):
    key = cfg.get('api_key') or os.getenv(cfg.get('api_key_env', ''))
    if not key or not cfg.get('base_url'):
        raise HTTPException(503, f'未配置{service}服务密钥或接口')
    return key


def _provider_failure(response, service, *, recording=False):
    """Translate known provider failures without forwarding provider text or credentials."""
    status = response.status_code
    try:
        body = response.json()
        error = body.get('error', body)
        code = str(error.get('code', '')).lower()
        message = str(error.get('message', '')).lower()
    except (ValueError, AttributeError, TypeError):
        code, message = '', ''
    signal = code + ' ' + message
    if status in (401, 403):
        reason = '密钥或模型授权不可用，请管理员检查配置'
    elif status == 429:
        reason = '服务繁忙或额度不足，请稍后重试'
    elif status == 404 or ('model' in signal and any(value in signal for value in ('not_supported', 'not_exist', 'not supported', 'not found', 'not exist', 'unsupported', 'is invalid', 'invalid model'))):
        reason = '模型或接口不受支持，请管理员核对模型名称和服务地址'
    elif any(value in signal for value in ('duration', 'too long', 'time limit', '时长')):
        reason = '音频时长超出限制，请管理员检查识别分段设置'
    elif any(value in signal for value in ('audio', 'format', '音频', '格式')):
        reason = '音频格式无法识别，请重试或下载录音后检查'
    elif status == 400:
        reason = '请求参数不被支持，请管理员检查模型和接口配置'
    else:
        reason = '服务暂时不可用，请稍后重试'
    suffix = '，录音已保存' if recording else ''
    return HTTPException(502, f'{service}失败（HTTP {status}）：{reason}{suffix}')


def _message_text(body):
    content = body['choices'][0]['message']['content']
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        raise ValueError('provider returned non-text content')
    return content.strip()


def chat(prompt, *, system=None, media=None, model=None, request_timeout_seconds=None, service='interview'):
    """Keep the expert role separate from user material and request text-only output."""
    cfg = model_settings.resolve(service, load_config())
    key = _key(cfg, 'AI')
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    content = [{'type': 'text', 'text': prompt}, *media] if media else prompt
    messages.append({'role': 'user', 'content': content})
    selected_model = model or cfg['model']
    payload = {'model': selected_model, 'messages': messages, 'stream': False}
    if 'omni' in selected_model.lower():
        payload['modalities'] = ['text']
        payload['reasoning_effort'] = 'none'
    try:
        response = httpx.post(cfg['base_url'].rstrip('/') + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key}, json=payload,
            timeout=request_timeout_seconds or cfg.get('request_timeout_seconds', 90))
        response.raise_for_status()
        text = _message_text(response.json())
        if not text:
            raise ValueError('empty model response')
        return text
    except httpx.HTTPStatusError as error:
        raise _provider_failure(error.response, 'AI') from error
    except httpx.TimeoutException as error:
        raise HTTPException(504,
            '等待 AI 响应超时；模型服务可能已受理请求，Token 费用以阿里云用量记录为准，请核对后再重试') from error
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
        raise HTTPException(502, 'AI 服务返回异常，请稍后重试') from error


def _convert(command, target, cfg, service):
    ffmpeg = shutil.which(cfg.get('ffmpeg', 'ffmpeg'))
    if not ffmpeg:
        raise HTTPException(503, f'未安装 ffmpeg，暂时无法处理{service}')
    try:
        result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', *command, '-y', target],
            capture_output=True, timeout=cfg.get('conversion_timeout_seconds', 30), check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HTTPException(502, f'{service}转换失败，原始录音已保留') from error
    if result.returncode != 0 or not os.path.getsize(target):
        raise HTTPException(400, f'{service}格式无法读取，原始录音已保留')


def media_audio(paths):
    """Combine local recordings into one 16 kHz mono MP3 for an Omni request."""
    if not paths:
        return []
    cfg = model_settings.resolve('interview', load_config())
    inputs = [argument for path in paths for argument in ('-i', str(path))]
    if len(paths) > 1:
        filters = ''.join(f'[{i}:a:0]aresample=16000,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}];' for i in range(len(paths)))
        filters += ''.join(f'[a{i}]' for i in range(len(paths))) + f'concat=n={len(paths)}:v=0:a=1[out]'
        inputs += ['-filter_complex', filters, '-map', '[out]']
    with tempfile.NamedTemporaryFile(suffix='.mp3') as converted:
        _convert([*inputs, '-ac', '1', '-ar', '16000', '-c:a', 'libmp3lame', '-b:a', '48k', '-f', 'mp3'],
            converted.name, cfg, '面试音频')
        if os.path.getsize(converted.name) > cfg.get('max_audio_mb', 8) * 1024 * 1024:
            raise HTTPException(413, '面试音频超出 AI 输入大小限制，请管理员检查音频配置')
        audio = base64.b64encode(converted.read()).decode('ascii')
    return [{'type': 'input_audio', 'input_audio': {'data': f'data:audio/mp3;base64,{audio}', 'format': 'mp3'}}]


def transcribe(path):
    """Convert recordings and split long audio before requesting ASR."""
    cfg = model_settings.resolve('asr', load_config())
    try:
        key = _key(cfg, '语音识别')
    except HTTPException as error:
        raise HTTPException(error.status_code, error.detail + '，录音已保存') from error
    transcripts = []
    with tempfile.NamedTemporaryFile(suffix='.wav') as converted:
        _convert(['-i', str(path), '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-f', 'wav'],
            converted.name, cfg, '录音')
        with wave.open(converted.name, 'rb') as source:
            frames_per_segment = source.getframerate() * cfg.get('max_segment_seconds', 30)
            while frames := source.readframes(frames_per_segment):
                output = io.BytesIO()
                with wave.open(output, 'wb') as segment:
                    segment.setnchannels(source.getnchannels())
                    segment.setsampwidth(source.getsampwidth())
                    segment.setframerate(source.getframerate())
                    segment.writeframes(frames)
                text = _transcribe_segment(output.getvalue(), cfg, key)
                if text:
                    transcripts.append(text)
    return '\n'.join(transcripts)


def _transcribe_segment(audio, cfg, key):
    base_url = cfg['base_url'].rstrip('/')
    if not base_url.endswith('/v1'):
        base_url += '/v1'
    encoded = base64.b64encode(audio).decode('ascii')
    try:
        response = httpx.post(base_url + '/chat/completions', headers={'Authorization': 'Bearer ' + key},
            json={'model': cfg['model'], 'messages': [{'role': 'user', 'content': [
                {'type': 'input_audio', 'input_audio': {'data': f'data:audio/wav;base64,{encoded}'}}]}],
                'stream': False, 'asr_options': {'enable_itn': True}},
            timeout=cfg['request_timeout_seconds'])
        response.raise_for_status()
        return _message_text(response.json())
    except httpx.HTTPStatusError as error:
        raise _provider_failure(error.response, '阿里云语音识别', recording=True) from error
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
        raise HTTPException(502, '语音识别响应异常，请稍后重试，录音已保存') from error


def _audio_result(data, content_type, maximum):
    if len(data) > maximum:
        raise HTTPException(502, '合成音频大小超出限制，请缩短问题后重试')
    if not data:
        raise HTTPException(502, '语音合成未返回音频，请稍后重试')
    media_type = content_type.partition(';')[0].strip().lower()
    if media_type not in ('audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/aac', 'audio/flac', 'audio/mp4'):
        raise HTTPException(502, '语音合成返回了不支持的音频格式')
    return data, media_type


def _download_speech(url, cfg, maximum):
    try:
        parsed = urlsplit(url)
        allowed = [host.lower() for host in cfg.get('download_hosts', [])]
        # Some DashScope responses use HTTP URLs; request the same trusted resource over TLS.
        if parsed.scheme == 'http' and parsed.hostname and parsed.hostname.lower() in allowed:
            parsed = parsed._replace(scheme='https')
            url = urlunsplit(parsed)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname.lower() not in allowed or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('untrusted audio URL')
    except (ValueError, TypeError) as error:
        raise HTTPException(502, '语音合成返回的音频地址不受信任，请管理员检查配置') from error
    with httpx.stream('GET', url, follow_redirects=False, timeout=cfg['request_timeout_seconds']) as response:
        response.raise_for_status()
        size = response.headers.get('content-length')
        if size and (not size.isdigit() or int(size) > maximum):
            raise HTTPException(502, '合成音频大小超出限制，请缩短问题后重试')
        chunks, length = [], 0
        for chunk in response.iter_bytes():
            length += len(chunk)
            if length > maximum:
                raise HTTPException(502, '合成音频大小超出限制，请缩短问题后重试')
            chunks.append(chunk)
        return _audio_result(b''.join(chunks), response.headers.get('content-type', 'audio/wav'), maximum)


def synthesize(text):
    """Synthesize one expert question, bounded by configured size and trusted hosts."""
    cfg = model_settings.resolve('tts', load_config())
    if not cfg.get('enabled', True):
        raise HTTPException(503, '专家语音播报暂未启用，可直接阅读问题')
    key = _key(cfg, '语音合成')
    maximum = cfg.get('max_audio_mb', 12) * 1024 * 1024
    headers = {'Authorization': 'Bearer ' + key}
    base = cfg['base_url'].rstrip('/')
    try:
        if cfg.get('provider', 'dashscope') == 'openai':
            response = httpx.post(base + '/audio/speech', headers=headers,
                json={'model': cfg['model'], 'input': text, 'voice': cfg['voice'], 'response_format': 'mp3'},
                timeout=cfg['request_timeout_seconds'])
            response.raise_for_status()
            return _audio_result(response.content, response.headers.get('content-type', 'audio/mpeg'), maximum)
        protocol = cfg.get('protocol', 'dashscope_audio')
        if protocol == 'dashscope_audio':
            endpoint = urlsplit(base)
            if (endpoint.scheme != 'https' or not endpoint.hostname
                    or not (endpoint.hostname.lower() == 'dashscope.aliyuncs.com'
                        or endpoint.hostname.lower().endswith('.maas.aliyuncs.com'))
                    or endpoint.username or endpoint.password or endpoint.port not in (None, 443)
                    or endpoint.query or endpoint.fragment):
                raise HTTPException(503, '语音合成需要配置有效的阿里云 HTTPS 接口地址')
            payload = {'model': cfg['model'], 'input': {'text': text, 'voice': cfg['voice'],
                'format': cfg.get('format', 'wav'), 'sample_rate': cfg.get('sample_rate', 24000)}}
            endpoint_url = base + '/services/audio/tts/SpeechSynthesizer'
        elif protocol == 'dashscope_native':
            payload = {'model': cfg['model'], 'input': {'text': text, 'voice': cfg['voice'],
                'language_type': cfg.get('language_type', 'Chinese')}}
            endpoint_url = base + '/services/aigc/multimodal-generation/generation'
        else:
            raise HTTPException(503, '语音合成协议配置无效，请管理员检查配置')
        response = httpx.post(endpoint_url, headers=headers, json=payload,
            timeout=cfg['request_timeout_seconds'])
        response.raise_for_status()
        output = response.json()['output']['audio']
        return _download_speech(output['url'], cfg, maximum)
    except httpx.HTTPStatusError as error:
        raise _provider_failure(error.response, '语音合成') from error
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as error:
        raise HTTPException(502, '语音合成响应异常，可直接阅读专家问题并稍后重试') from error
