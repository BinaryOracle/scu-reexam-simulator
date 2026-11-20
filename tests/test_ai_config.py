"""Multimodal and speech settings remain explicit, validated deployment options."""
from pathlib import Path
import pytest
from app.config import load_config


def config_file(tmp_path, monkeypatch, extra=''):
    text = Path('config.example.toml').read_text()
    path = tmp_path / 'config.toml'
    path.write_text(text + extra)
    monkeypatch.setenv('SCU_CONFIG', str(path))
    return path


def test_omni_and_tts_defaults_are_configurable(tmp_path, monkeypatch):
    config_file(tmp_path, monkeypatch)
    config = load_config()
    assert config['ai']['model'] == 'qwen3.8-omni-flash'
    assert config['ai']['include_audio'] is True
    assert config['ai']['include_slide_images'] is True
    assert config['ai']['max_slide_pages'] >= config['presentation']['max_pages']
    assert config['tts']['model'] == 'qwen-audio-3.1-tts-plus'
    assert config['tts']['provider'] == 'dashscope'
    assert config['tts']['protocol'] == 'dashscope_audio'
    assert config['tts']['voice'] == 'longanhuan_v3.1'
    assert config['asr']['max_segment_seconds'] == 30
    assert config['trends'] == {
        'model': 'qwen3.7-plus', 'request_timeout_seconds': 300,
        'source_timeout_seconds': 15, 'max_sources': 36,
        'auto_refresh': True, 'refresh_time': '06:00', 'retry_interval_minutes': 15,
    }


@pytest.mark.parametrize('section,key,value', [
    ('ai', 'max_audio_mb', 0), ('ai', 'include_audio', 'yes'),
    ('tts', 'provider', 'unknown'), ('tts', 'max_audio_mb', -1),
    ('tts', 'download_hosts', ['https://example.com']),
    ('tts', 'cache_lock_timeout_seconds', 0),
    ('asr', 'max_segment_seconds', 0),
    ('trends', 'max_sources', 101),
    ('trends', 'refresh_time', '6am'),
    ('trends', 'retry_interval_minutes', 0),
])
def test_invalid_provider_settings_fail_before_serving(tmp_path, monkeypatch, section, key, value):
    path = config_file(tmp_path, monkeypatch)
    import tomllib
    # Each malformed value replaces its existing example setting, avoiding duplicate TOML keys.
    import json
    text = path.read_text()
    if f'[{section}]' not in text:
        text += f'\n[{section}]\n'
    start = text.index(f'[{section}]')
    end = text.find('\n[', start + 1)
    end = len(text) if end == -1 else end
    lines = text[start:end].splitlines()
    lines = [line for line in lines if not line.startswith(key + ' =')]
    lines.append(f'{key} = {json.dumps(value)}')
    path.write_text(text[:start] + '\n'.join(lines) + '\n' + text[end:])
    tomllib.loads(path.read_text())
    with pytest.raises(ValueError, match=section + r'\.' + key):
        load_config()
