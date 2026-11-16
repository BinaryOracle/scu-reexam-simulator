"""LiveKit server SDK integration. API failures never become successful media state."""
import json
import os
import stat
from datetime import timedelta
import aiohttp
from fastapi import HTTPException
from livekit import api
from app.config import load_config


def settings():
    return load_config()['live']


def credentials():
    """Use an environment pair, otherwise the explicitly configured private JSON file.

    Never combine credentials from different sources; incomplete environment
    overrides remain unconfigured. File errors do not expose file contents.
    """
    config = settings()
    names = config['api_key_env'], config['api_secret_env']
    values = tuple(os.environ.get(name, '') for name in names)
    if any(name in os.environ for name in names) or not config['credentials_file']:
        return values
    try:
        with open(config['credentials_file'], encoding='utf-8') as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or (os.name == 'posix' and metadata.st_mode & 0o077):
                raise ValueError('private regular file required')
            stored = json.load(source)
        if not isinstance(stored, dict) or any(not isinstance(stored.get(name), str) or not stored[name].strip() for name in names):
            raise ValueError('credential pair required')
        return stored[names[0]], stored[names[1]]
    except (OSError, ValueError) as error:
        raise HTTPException(503, '直播凭据文件不可用，请管理员检查 live.credentials_file、JSON 密钥字段及文件权限（Mac/Linux 使用 chmod 600）') from error


def configured():
    key, secret = credentials()
    config = settings()
    return bool(config['url'] and config['api_url'] and key and secret)


def require_configured():
    if not configured():
        raise HTTPException(503, '直播媒体尚未配置，请联系管理员配置 LiveKit 服务')


def room(lid):
    return f'classroom-{lid}'


def sources(speak, share):
    return (['microphone', 'camera'] if speak else []) + (['screen_share', 'screen_share_audio'] if share else [])


def token(lid, user, speak, share):
    require_configured()
    key, secret = credentials()
    return (api.AccessToken(key, secret).with_identity(str(user['id'])).with_name(user['username'])
            .with_ttl(timedelta(seconds=settings()['token_seconds']))
            .with_grants(api.VideoGrants(room_join=True, room=room(lid), can_publish=bool(speak or share),
                can_publish_sources=sources(speak, share), can_publish_data=False, can_subscribe=True)).to_jwt())


async def call(service, method, request):
    require_configured()
    key, secret = credentials()
    client = api.LiveKitAPI(settings()['api_url'], key, secret, timeout=aiohttp.ClientTimeout(total=15))
    try:
        return await getattr(getattr(client, service), method)(request)
    except (api.TwirpError, aiohttp.ClientError, TimeoutError) as error:
        raise HTTPException(502, 'LiveKit 服务操作失败，请检查服务状态后重试') from error
    finally:
        await client.aclose()


async def permission(lid, uid, speak, share):
    mapping = {'microphone': api.TrackSource.MICROPHONE, 'camera': api.TrackSource.CAMERA,
               'screen_share': api.TrackSource.SCREEN_SHARE, 'screen_share_audio': api.TrackSource.SCREEN_SHARE_AUDIO}
    return await call('room', 'update_participant', api.UpdateParticipantRequest(
        room=room(lid), identity=str(uid), permission=api.ParticipantPermission(
            can_subscribe=True, can_publish=bool(speak or share), can_publish_data=False,
            can_publish_sources=[mapping[source] for source in sources(speak, share)])))
