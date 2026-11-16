"""Encrypted administrator overrides for external model providers."""
import json
import os
from pathlib import Path
import sqlite3

from app.config import load_config
from app.services.password_vault import decrypt_password, encrypt_password

SETTING_KEY = 'ai_model_settings'
SERVICES = ('interview', 'asr', 'tts', 'trends')
FIELDS = {
    'interview': ('base_url', 'model'),
    'asr': ('base_url', 'model'),
    'tts': ('base_url', 'model', 'provider', 'protocol', 'voice'),
    'trends': ('base_url', 'model'),
}
SECTIONS = {'interview': 'ai', 'asr': 'asr', 'tts': 'tts', 'trends': 'trends'}


def read(db):
    """Read encrypted service overrides from the caller's SQLite unit of work."""
    row = db.execute('SELECT value FROM app_settings WHERE key=?', (SETTING_KEY,)).fetchone()
    return json.loads(row['value']) if row else {}


def save(db, settings):
    """Persist an override document without writing API keys in plaintext."""
    value = json.dumps(settings, ensure_ascii=False, sort_keys=True)
    db.execute('INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (SETTING_KEY, value))


def _config_section(config, service):
    section = SECTIONS[service]
    if service != 'trends':
        return dict(config.get(section, {}))
    return {**config.get('ai', {}), **config.get(section, {})}


def _stored(config):
    """Read settings without creating a database for config-only unit callers."""
    app = config.get('app')
    if not app or not Path(app['database']).is_file():
        return {}
    path = Path(app['database']).resolve()
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            row = db.execute('SELECT value FROM app_settings WHERE key=?', (SETTING_KEY,)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error).lower():
            return {}
        raise
    return json.loads(row[0]) if row else {}


def resolve(service, config=None, overrides=None):
    """Return deployment defaults merged with administrator overrides."""
    config = config or load_config()
    stored = _stored(config) if overrides is None else overrides
    effective = (resolve('interview', config, stored) if service == 'trends'
                 else _config_section(config, service))
    if service == 'trends':
        effective.update(config.get('trends', {}))
    values = stored.get(service, {})
    for field in FIELDS[service]:
        if field in values:
            effective[field] = values[field]
    ciphertext = values.get('api_key_encrypted')
    if ciphertext:
        effective['api_key'] = decrypt_password(ciphertext)
    return effective


def public_settings(config=None, overrides=None):
    """Build administrator settings without returning API key material."""
    config = config or load_config()
    stored = _stored(config) if overrides is None else overrides
    result = {}
    for service in SERVICES:
        values = stored.get(service, {})
        effective = resolve(service, config, stored)
        section_name = 'ai' if service == 'trends' else SECTIONS[service]
        section = config.get(section_name, {})
        encrypted = bool(values.get('api_key_encrypted'))
        configured_value = bool(section.get('api_key'))
        env_name = section.get('api_key_env', '')
        environment_value = bool(env_name and os.getenv(env_name))
        if encrypted:
            source = '后台设置'
        elif service == 'trends' and stored.get('interview', {}).get('api_key_encrypted'):
            source = '继承通用模型设置'
        elif configured_value:
            source = '配置文件'
        elif environment_value:
            source = '环境变量'
        else:
            source = '未配置'
        result[service] = {field: effective.get(field, '') for field in FIELDS[service]}
        result[service]['api_key_configured'] = bool(effective.get('api_key') or environment_value)
        result[service]['api_key_source'] = source
    return {'services': result}


def apply_update(db, current, updates):
    """Validate against known services and persist selected fields and encrypted keys."""
    updated = {service: dict(current.get(service, {})) for service in SERVICES}
    for service, values in updates.items():
        if values is None:
            continue
        target = updated[service]
        clear_key = values.pop('clear_api_key', False)
        key = values.pop('api_key', None)
        for field, value in values.items():
            if field in FIELDS[service] and value is not None:
                target[field] = value
        if clear_key:
            target.pop('api_key_encrypted', None)
        elif key:
            target['api_key_encrypted'] = encrypt_password(key)
    save(db, updated)
    return updated
