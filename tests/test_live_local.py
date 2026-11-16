"""Local deployment configuration preserves existing application data and secrets."""
import json
from pathlib import Path
import tomllib

import pytest
from scripts import live_local


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    from app import config
    source = (live_local.ROOT / 'config.example.toml').read_text()
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/fonts.conf').write_text('<fontconfig/>\n')
    path = tmp_path / 'config.toml'
    path.write_text(source)
    monkeypatch.setenv('SCU_CONFIG', str(path))
    monkeypatch.setattr(live_local, 'ROOT', tmp_path)
    monkeypatch.setattr(live_local, 'RUNTIME', tmp_path / 'runtime')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    return path


def test_prepare_preserves_other_sections_and_credentials_across_restarts(local_config):
    before = tomllib.loads(local_config.read_text())
    live_local.prepare()
    first = json.loads((live_local.RUNTIME / 'credentials.json').read_text())
    live_local.prepare()
    assert json.loads((live_local.RUNTIME / 'credentials.json').read_text()) == first
    after = tomllib.loads(local_config.read_text())
    assert {k: v for k, v in before.items() if k != 'live'} == {k: v for k, v in after.items() if k != 'live'}
    assert after['live']['recording_enabled'] is True
    assert after['live']['url'] == 'ws://127.0.0.1:7880'
    assert first['LIVEKIT_API_SECRET'] not in local_config.read_text()
    assert (live_local.RUNTIME / 'credentials.json').stat().st_mode & 0o777 == 0o600
    assert tomllib.loads((live_local.RUNTIME / 'config.before-live.toml').read_text()) == before
    assert Path(live_local.environment()['LIVE_RECORDINGS_DIR']).is_dir()


def test_prepare_adds_live_section_to_old_configuration(local_config):
    import re
    local_config.write_text(re.sub(r'^\[live\]\n.*?(?=^\[|\Z)', '', local_config.read_text(), flags=re.S | re.M))
    live_local.prepare()
    assert tomllib.loads(local_config.read_text())['live']['api_url'] == 'http://127.0.0.1:7880'


def test_prepared_media_survives_plain_app_restart_without_injected_environment(local_config, monkeypatch):
    from app.services import live_media
    monkeypatch.delenv('LIVEKIT_API_KEY', raising=False)
    monkeypatch.delenv('LIVEKIT_API_SECRET', raising=False)
    live_local.prepare()
    assert live_media.configured()
    saved = json.loads((live_local.RUNTIME / 'credentials.json').read_text())
    assert live_media.credentials() == (saved['LIVEKIT_API_KEY'], saved['LIVEKIT_API_SECRET'])


def test_launcher_does_not_take_over_an_existing_application(monkeypatch):
    monkeypatch.setattr(live_local, 'listener_exists', lambda: True)
    with pytest.raises(RuntimeError, match='8000'):
        live_local.app_start()


def test_down_does_not_kill_reused_process_id(tmp_path, monkeypatch):
    from types import SimpleNamespace
    pid = tmp_path / 'app.pid'
    pid.write_text('123\n')
    monkeypatch.setattr(live_local, 'PIDFILE', pid)
    monkeypatch.setattr(live_local.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout='/usr/bin/unrelated-app'))
    with pytest.raises(RuntimeError, match='未终止'):
        live_local.app_stop()
    assert pid.exists()
