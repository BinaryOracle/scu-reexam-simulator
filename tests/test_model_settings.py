"""Administrator model settings are effective at runtime without exposing stored keys."""
import json
import httpx

from app.db import connect
from app.config import load_config
from app.services import model_settings
from test_system import client, login


def test_admin_can_change_models_and_keys_without_reading_key_values(client, monkeypatch):
    admin, student = login(client, 'manager'), login(client, 'alice')
    assert client.get('/api/admin/model-settings', headers=student).status_code == 403

    settings = client.get('/api/admin/model-settings', headers=admin)
    assert settings.status_code == 200
    assert set(settings.json()['services']) == {'interview', 'asr', 'tts', 'trends'}
    assert all('api_key' not in item for item in settings.json()['services'].values())

    secret = 'model-key-not-for-response'
    updated = client.patch('/api/admin/model-settings', headers=admin, json={
        'interview': {
            'base_url': 'https://models.example.test/v1',
            'model': 'multimodal-v2',
            'api_key': secret,
        },
        'asr': {'model': 'speech-recognition-v2'},
        'tts': {'provider': 'openai', 'model': 'speech-synthesis-v2', 'voice': 'alloy'},
        'trends': {'model': 'text-analysis-v2'},
    })
    assert updated.status_code == 200, updated.text
    body = updated.json()['services']
    assert body['interview']['model'] == 'multimodal-v2'
    assert body['interview']['api_key_configured'] is True
    assert body['asr']['model'] == 'speech-recognition-v2'
    assert body['tts']['provider'] == 'openai' and body['tts']['voice'] == 'alloy'
    assert body['trends']['model'] == 'text-analysis-v2'
    assert secret not in updated.text

    with connect() as db:
        encoded = db.execute("SELECT value FROM app_settings WHERE key='ai_model_settings'").fetchone()['value']
    assert secret not in encoded
    stored = json.loads(encoded)
    assert stored['interview']['api_key_encrypted'] != secret
    interview = model_settings.resolve('interview', load_config())
    trends = model_settings.resolve('trends', load_config())
    assert (interview['base_url'], interview['model'], interview['api_key']) == (
        'https://models.example.test/v1', 'multimodal-v2', secret)
    assert trends['model'] == 'text-analysis-v2' and trends['api_key'] == secret

    from app.services import ai
    captured = {}
    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'choices': [{'message': {'content': '已切换'}}]})
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.chat('测试请求') == '已切换'
    assert captured['url'] == 'https://models.example.test/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer ' + secret
    assert captured['json']['model'] == 'multimodal-v2'


def test_admin_model_settings_validate_service_urls_and_ignore_failed_updates(client):
    admin = login(client, 'manager')
    before = client.get('/api/admin/model-settings', headers=admin).json()
    invalid = client.patch('/api/admin/model-settings', headers=admin, json={
        'interview': {'base_url': 'javascript:alert(1)'},
    })
    assert invalid.status_code == 422
    assert client.get('/api/admin/model-settings', headers=admin).json() == before
