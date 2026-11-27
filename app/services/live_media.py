"""LiveKit server SDK integration. API failures never become successful media state."""
import json
import logging
import os
import stat
from datetime import timedelta
import aiohttp
from fastapi import HTTPException
from livekit import api
from app.config import load_config

logger = logging.getLogger(__name__)


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
    except api.TwirpError as error:
        logger.warning('LiveKit %s.%s failed with code=%s status=%s',
                       service, method, error.code, error.status)
        if error.code == 'not_found' and method == 'update_participant':
            raise HTTPException(409, '课堂音视频连接已中断，正在恢复；请等待“连接正常”后重新点击共享屏幕。') from error
        if error.code == 'not_found':
            raise HTTPException(404, '找不到该直播房间，或房间已结束。请退出后重新进入；若仍失败，请管理员确认 live.api_url 与 live.url 指向同一 LiveKit 服务。') from error
        if error.code in {'unauthenticated', 'permission_denied'}:
            raise HTTPException(503, '直播服务鉴权失败，请联系管理员检查 LiveKit 服务端密钥和权限配置。') from error
        if error.code in {'unavailable', 'deadline_exceeded'}:
            raise HTTPException(503, '直播媒体服务暂时不可用，请稍后重试；若持续发生，请联系管理员检查服务状态。') from error
        raise HTTPException(502, 'LiveKit 暂时无法完成此操作，请稍后重试；若持续发生，请联系管理员查看服务日志。') from error
    except (aiohttp.ClientError, TimeoutError) as error:
        if isinstance(error, TimeoutError):
            logger.warning('LiveKit %s.%s timed out', service, method)
            raise HTTPException(504, '连接直播媒体服务超时，请检查网络后重试。') from error
        logger.warning('LiveKit %s.%s could not connect: %s', service, method, type(error).__name__)
        raise HTTPException(502, '无法连接直播媒体服务，请稍后重试；若持续发生，请联系管理员检查服务状态。') from error
    finally:
        await client.aclose()


async def permission(lid, uid, speak, share):
    mapping = {'microphone': api.TrackSource.MICROPHONE, 'camera': api.TrackSource.CAMERA,
               'screen_share': api.TrackSource.SCREEN_SHARE, 'screen_share_audio': api.TrackSource.SCREEN_SHARE_AUDIO}
    return await call('room', 'update_participant', api.UpdateParticipantRequest(
        room=room(lid), identity=str(uid), permission=api.ParticipantPermission(
            can_subscribe=True, can_publish=bool(speak or share), can_publish_data=False,
            can_publish_sources=[mapping[source] for source in sources(speak, share)])))
