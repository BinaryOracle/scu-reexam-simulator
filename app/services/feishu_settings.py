"""Encrypted administrator-managed Feishu application credentials."""
import json
import os

from app.db import connect
from app.services.password_vault import decrypt_password, encrypt_password

SETTING_KEY = 'feishu_credentials'


def read(db):
    """Read the stored Feishu application credential record."""
    row = db.execute('SELECT value FROM app_settings WHERE key=?', (SETTING_KEY,)).fetchone()
    return json.loads(row['value']) if row else {}


def save(db, settings):
    """Persist application settings while keeping the App Secret encrypted."""
    db.execute('INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (SETTING_KEY, json.dumps(settings, ensure_ascii=False, sort_keys=True)))


def credentials(db=None):
    """Resolve administrator settings before environment defaults."""
    if db is None:
        with connect() as connection:
            return credentials(connection)
    stored = read(db)
    secret = stored.get('app_secret_encrypted')
    return {
        'app_id': stored.get('app_id') or os.getenv('FEISHU_APP_ID', ''),
        'app_secret': decrypt_password(secret) if secret else os.getenv('FEISHU_APP_SECRET', ''),
    }


def redirect_uri(db):
    """Return the exact allowlisted callback address configured for this deployment."""
    return read(db).get('redirect_uri') or os.getenv('FEISHU_REDIRECT_URI', 'http://127.0.0.1:8000/api/feishu/oauth/callback')


def public_settings(db):
    """Describe effective credential availability without returning secret values."""
    stored = read(db)
    environment_id = os.getenv('FEISHU_APP_ID', '')
    environment_secret = os.getenv('FEISHU_APP_SECRET', '')
    has_stored = bool(stored.get('app_id') or stored.get('app_secret_encrypted'))
    if os.getenv('FEISHU_USER_ACCESS_TOKEN'):
        source = '用户访问令牌环境变量'
    elif has_stored:
        source = '后台设置'
    elif environment_id or environment_secret:
        source = '环境变量'
    else:
        source = '未配置'
    return {
        'app_id': stored.get('app_id') or environment_id,
        'app_secret_configured': bool(stored.get('app_secret_encrypted') or environment_secret),
        'credential_source': source,
        'redirect_uri': redirect_uri(db),
    }


def update(db, changes):
    """Update the App ID and optionally replace or clear the encrypted secret."""
    from app.services import feishu_oauth
    db.execute('BEGIN IMMEDIATE')
    before = feishu_oauth._fingerprint(db)
    settings = read(db)
    if 'redirect_uri' in changes:
        settings['redirect_uri'] = feishu_oauth.validate_redirect_uri(changes['redirect_uri'])
    if 'app_id' in changes:
        if changes['app_id']:
            settings['app_id'] = changes['app_id']
        else:
            settings.pop('app_id', None)
    if changes.get('clear_app_secret'):
        settings.pop('app_secret_encrypted', None)
    elif changes.get('app_secret'):
        settings['app_secret_encrypted'] = encrypt_password(changes['app_secret'])
    save(db, settings)
    if before != feishu_oauth._fingerprint(db):
        feishu_oauth.disconnect(db)
    return public_settings(db)
