"""Explicit private credential files support restarts without leaking secrets."""
import json

import pytest
from fastapi import HTTPException
from app.services import live_media


@pytest.fixture
def credential_file(tmp_path, monkeypatch):
    path = tmp_path / 'credentials.json'
    path.write_text(json.dumps({'LIVEKIT_API_KEY': 'file-key', 'LIVEKIT_API_SECRET': 'file-secret'}))
    path.chmod(0o600)
    monkeypatch.delenv('LIVEKIT_API_KEY', raising=False)
    monkeypatch.delenv('LIVEKIT_API_SECRET', raising=False)
    monkeypatch.setattr(live_media, 'settings', lambda: {
        'url': 'ws://localhost:7880', 'api_url': 'http://localhost:7880',
        'api_key_env': 'LIVEKIT_API_KEY', 'api_secret_env': 'LIVEKIT_API_SECRET',
        'credentials_file': str(path)})
    return path


def test_environment_pair_takes_precedence_over_private_file(credential_file, monkeypatch):
    monkeypatch.setenv('LIVEKIT_API_KEY', 'env-key')
    monkeypatch.setenv('LIVEKIT_API_SECRET', 'env-secret')
    credential_file.unlink()
    assert live_media.credentials() == ('env-key', 'env-secret')


def test_partial_environment_does_not_mix_with_file_credentials(credential_file, monkeypatch):
    monkeypatch.setenv('LIVEKIT_API_KEY', 'different-key')
    assert not live_media.configured()


@pytest.mark.parametrize('failure', ['missing', 'invalid', 'incomplete', 'readable'])
def test_bad_explicit_file_is_actionable_and_does_not_leak_contents(credential_file, failure):
    if failure == 'missing':
        credential_file.unlink()
    elif failure == 'invalid':
        credential_file.write_text('file-secret invalid JSON')
    elif failure == 'incomplete':
        credential_file.write_text('{"LIVEKIT_API_KEY":"file-secret"}')
    else:
        credential_file.chmod(0o644)
    with pytest.raises(HTTPException) as caught:
        live_media.credentials()
    assert caught.value.status_code == 503
    assert '凭据文件' in caught.value.detail
    assert 'file-secret' not in caught.value.detail
