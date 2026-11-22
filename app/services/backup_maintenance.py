"""Admission control for online restore in the supported single-process deployment."""
from contextlib import contextmanager
import threading
from fastapi import HTTPException

_lock = threading.Lock()
_active = 0
_restoring = False


def enter_request():
    global _active
    with _lock:
        if _restoring:
            return False
        _active += 1
        return True


def leave_request():
    global _active
    with _lock:
        _active -= 1


@contextmanager
def exclusive_restore():
    """Refuse active requests and reject new requests until the restore finishes."""
    global _restoring
    with _lock:
        if _restoring or _active > 1:
            raise HTTPException(409, '当前仍有请求处理中，请暂停其他操作后重试恢复')
        _restoring = True
    try:
        yield
    finally:
        with _lock:
            _restoring = False


class BackupMaintenanceMiddleware:
    """Track complete HTTP responses, including streaming downloads, during maintenance."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if scope.get('path') in ('/api/admin/backups/preview', '/api/admin/backups/restore'):
            from app.config import load_config
            from fastapi.responses import JSONResponse
            limit = load_config()['backups']['max_upload_mb'] * 1024 * 1024 + 1024 * 1024
            raw_length = dict(scope.get('headers', [])).get(b'content-length', b'0')
            try:
                length = int(raw_length)
            except ValueError:
                length = limit + 1
            if length < 0 or length > limit:
                response = JSONResponse({'detail': '上传内容超过备份大小限制'}, status_code=413)
                return await response(scope, receive, send)
            original_receive = receive
            received = 0

            async def bounded_receive():
                nonlocal received
                message = await original_receive()
                received += len(message.get('body', b''))
                if received > limit:
                    raise HTTPException(413, '上传内容超过备份大小限制')
                return message
            receive = bounded_receive
        if not enter_request():
            from fastapi.responses import JSONResponse
            response = JSONResponse({'detail': '系统正在恢复备份，请稍后重新登录'}, status_code=503,
                                    headers={'Retry-After': '5', 'Cache-Control': 'no-store'})
            return await response(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            leave_request()
