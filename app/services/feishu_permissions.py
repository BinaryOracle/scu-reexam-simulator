"""Grant Feishu document collaborators using server-side credentials and the Drive API."""
import os
import re
import threading
import time
import httpx
from app.services.package_benefits import resource_location
from app.services import feishu_settings, feishu_oauth

TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
USER_LOOKUP_URL = 'https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id'
API_URL = 'https://open.feishu.cn/open-apis/drive/v1/permissions/{token}/members'
_lock = threading.Lock()
_cached_token = ''
_token_expires = 0.0


class GrantError(RuntimeError):
    """A safe, actionable error returned to an administrator for a failed grant."""


def clear_token_cache():
    """Clear process-local application token cache for deterministic tests."""
    global _cached_token, _token_expires
    with _lock:
        _cached_token = ''
        _token_expires = 0.0


def _client():
    """Create a short-timeout client without ambient proxy or redirect behavior."""
    return httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, trust_env=False)


def _application_token():
    global _cached_token, _token_expires
    with _lock:
        if _cached_token and _token_expires > time.time() + 60:
            return _cached_token
        configured = feishu_settings.credentials()
        app_id, secret = configured['app_id'], configured['app_secret']
        if not app_id or not secret:
            raise GrantError('未配置飞书访问凭据：请设置 FEISHU_APP_ID 与 FEISHU_APP_SECRET，或提供 FEISHU_USER_ACCESS_TOKEN')
        try:
            with _client() as client:
                response = client.post(TOKEN_URL, json={'app_id': app_id, 'app_secret': secret})
                data = response.json()
        except (httpx.HTTPError, ValueError):
            raise GrantError('获取飞书应用访问令牌失败，请检查服务端网络与应用凭据') from None
        if not isinstance(data, dict):
            raise GrantError('获取飞书应用访问令牌失败：响应格式异常')
        if not response.is_success or data.get('code') != 0 or not isinstance(data.get('tenant_access_token'), str) or not data['tenant_access_token']:
            raise GrantError(f'获取飞书应用访问令牌失败（HTTP {response.status_code}，错误码 {_safe_code(response)}）')
        _cached_token = data['tenant_access_token']
        _token_expires = time.time() + max(int(data.get('expire', 7200)) - 120, 60)
        return _cached_token


def _safe_code(response):
    try:
        data = response.json()
    except ValueError:
        return '未知'
    code = data.get('code') if isinstance(data, dict) else None
    return str(code) if type(code) is int else '未知'


def _resolve_mobile(mobile):
    """Resolve a visible contact using the configured application's tenant token."""
    token_value = _application_token()
    try:
        with _client() as client:
            response = client.post(USER_LOOKUP_URL, params={'user_id_type': 'open_id'},
                                   headers={'Authorization': f'Bearer {token_value}'}, json={'mobiles': [mobile]})
            data = response.json()
    except (httpx.HTTPError, ValueError):
        raise GrantError('通过手机号定位飞书用户失败，请检查服务端网络后重试') from None
    if not isinstance(data, dict):
        raise GrantError('飞书手机号查询响应格式异常，请稍后重试')
    if not response.is_success or data.get('code') != 0:
        raise GrantError('飞书手机号查询失败，请为应用开通 contact:user.id:readonly 权限并配置通讯录数据范围'
                         f'（错误码 {_safe_code(response)}）')
    result = data.get('data')
    users = result.get('user_list') if isinstance(result, dict) else None
    if not isinstance(users, list):
        raise GrantError('飞书手机号查询响应格式异常，请稍后重试')
    if len(users) != 1 or not isinstance(users[0], dict) or not isinstance(users[0].get('user_id'), str) or not re.fullmatch(r'ou_[A-Za-z0-9_-]+', users[0]['user_id']):
        raise GrantError('未找到该手机号对应的可授权飞书用户，请核对绑定手机号及应用通讯录范围；外部学员可改用飞书邮箱')
    return users[0]['user_id']


def grant(resource, recipient):
    """Grant by email or resolved phone identity; support previously saved Open ID jobs."""
    if not isinstance(resource, dict) or not isinstance(recipient, dict):
        raise GrantError('飞书授权配置无效，请检查套餐权益')
    try:
        resource_type, token = resource_location(resource['url'])
        member_type, member_id = recipient['member_type'], recipient['member_id']
        if member_type not in ('email', 'mobile', 'openid') or not member_id:
            raise ValueError
        if member_type == 'mobile' and not re.fullmatch(r'(?:1\d{10}|\+[1-9]\d{6,14})', member_id):
            raise ValueError
        permission = resource['permission']
        if permission not in ('view', 'edit', 'full_access'):
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise GrantError('飞书授权配置无效，请检查资源链接、授权对象和权限级别') from None
    if member_type == 'mobile':
        member_id = _resolve_mobile(member_id)
        member_type = 'openid'
    try:
        token_value = feishu_oauth.access_token() or os.getenv('FEISHU_USER_ACCESS_TOKEN', '') or _application_token()
    except feishu_oauth.OAuthError as error:
        raise GrantError(str(error)) from None
    try:
        with _client() as client:
            response = client.post(API_URL.format(token=token), params={'type': resource_type},
                                   headers={'Authorization': f'Bearer {token_value}'},
                                   json={'member_type': member_type, 'member_id': member_id,
                                         'perm': permission, 'type': 'user'})
    except httpx.HTTPError:
        raise GrantError('调用飞书授权接口失败，请检查网络后重试；超时结果请先在飞书确认权限') from None
    code = _safe_code(response)
    if not response.is_success or code != '0':
        messages = {
            '1063001': '资源或授权对象无效，请核对飞书链接与用户邮箱/手机号',
            '1063002': '调用身份无权管理该资源；请将应用添加为文档应用，或改用有分享权限的用户令牌',
            '1063003': '资源或企业协作者策略不允许此授权，请检查资源权限设置',
            '1063004': '调用身份缺少分享权限，请在飞书分享设置中开放协作者管理',
            '1063005': '飞书资源不存在或已删除',
        }
        raise GrantError(f'{messages.get(code, "飞书未接受授权请求，请核对应用权限及资源设置")}（错误码 {code}）')
