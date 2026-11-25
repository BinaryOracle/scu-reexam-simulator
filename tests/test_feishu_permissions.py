"""Official Feishu grant protocol, token reuse, and actionable failures."""
import httpx
import pytest


def test_application_token_is_cached_and_grant_uses_permission_api(monkeypatch):
    from app.services import feishu_permissions as feishu
    monkeypatch.setenv('FEISHU_APP_ID', 'cli_test')
    monkeypatch.setenv('FEISHU_APP_SECRET', 'secret-test')
    monkeypatch.setattr(feishu.feishu_settings, 'credentials', lambda: {'app_id': 'cli_test', 'app_secret': 'secret-test'})
    monkeypatch.delenv('FEISHU_USER_ACCESS_TOKEN', raising=False)
    feishu.clear_token_cache()
    calls = []
    def handler(request):
        import json
        calls.append(request)
        if request.url.path == '/open-apis/auth/v3/tenant_access_token/internal':
            assert json.loads(request.content) == {'app_id': 'cli_test', 'app_secret': 'secret-test'}
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'tenant-test', 'expire': 7200})
        assert request.url.path == '/open-apis/drive/v1/permissions/Folder123/members'
        assert request.url.params['type'] == 'folder'
        assert request.headers['Authorization'] == 'Bearer tenant-test'
        assert json.loads(request.content) == {'member_type': 'email', 'member_id': 'student@example.com', 'perm': 'full_access', 'type': 'user'}
        return httpx.Response(200, json={'code': 0, 'data': {'member': {'perm': 'full_access'}}})
    client_factory = httpx.Client
    monkeypatch.setattr(feishu, '_client', lambda: client_factory(transport=httpx.MockTransport(handler)))
    for _ in range(2):
        feishu.grant({'url': 'https://my.feishu.cn/drive/folder/Folder123', 'permission': 'full_access'},
                     {'member_type': 'email', 'member_id': 'student@example.com'})
    assert len(calls) == 3
    feishu.clear_token_cache()


def test_mobile_is_resolved_with_application_identity_before_document_grant(monkeypatch):
    import json
    from app.services import feishu_permissions as feishu
    monkeypatch.setattr(feishu, '_application_token', lambda: 'tenant-test')
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'user-grant-token')
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == '/open-apis/contact/v3/users/batch_get_id':
            assert request.headers['Authorization'] == 'Bearer tenant-test'
            assert request.url.params['user_id_type'] == 'open_id'
            assert json.loads(request.content) == {'mobiles': ['13800138000']}
            return httpx.Response(200, json={'code': 0, 'data': {'user_list': [
                {'mobile': '13800138000', 'user_id': 'ou_student'}]}})
        assert request.headers['Authorization'] == 'Bearer user-grant-token'
        assert json.loads(request.content) == {'member_type': 'openid', 'member_id': 'ou_student',
                                               'perm': 'view', 'type': 'user'}
        return httpx.Response(200, json={'code': 0})
    client_factory = httpx.Client
    monkeypatch.setattr(feishu, '_client', lambda: client_factory(transport=httpx.MockTransport(handler)))
    feishu.grant({'url': 'https://my.feishu.cn/docx/Document123', 'permission': 'view'},
                 {'member_type': 'mobile', 'member_id': '13800138000'})
    assert len(calls) == 2


@pytest.mark.parametrize('status,body,message', [
    (200, {'code': 0, 'data': {'user_list': []}}, '未找到'),
    (200, {'code': 0, 'data': {'user_list': [{'mobile': '13800138000'}]}}, '未找到'),
    (403, {'code': 99991672, 'msg': 'secret-from-provider'}, '权限'),
    (200, {'code': 0, 'data': {'user_list': [{'user_id': 'ou_one'}, {'user_id': 'ou_two'}]}}, '未找到'),
    (200, {'code': 0, 'data': []}, '响应'),
])
def test_mobile_lookup_failure_never_calls_document_grant(monkeypatch, status, body, message):
    from app.services import feishu_permissions as feishu
    monkeypatch.setattr(feishu, '_application_token', lambda: 'tenant-secret')
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == '/open-apis/contact/v3/users/batch_get_id'
        return httpx.Response(status, json=body)
    client_factory = httpx.Client
    monkeypatch.setattr(feishu, '_client', lambda: client_factory(transport=httpx.MockTransport(handler)))
    with pytest.raises(feishu.GrantError, match=message) as error:
        feishu.grant({'url': 'https://my.feishu.cn/docx/Document123', 'permission': 'view'},
                     {'member_type': 'mobile', 'member_id': '13800138000'})
    assert len(calls) == 1
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('phone', ['13800138000', '+8613800138000', '+14155552671'])
def test_phone_recipient_accepts_domestic_and_international_numbers(phone):
    from app.services.package_benefits import FeishuRecipient
    assert FeishuRecipient(member_type='mobile', member_id=phone).member_id == phone


@pytest.mark.parametrize('phone', ['123', '13800138000\nother', 'someone@example.com', 'ou_student'])
def test_phone_recipient_rejects_invalid_numbers(phone):
    from app.services.package_benefits import FeishuRecipient
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        FeishuRecipient(member_type='mobile', member_id=phone)


def test_user_token_and_permissions_errors_never_leak_credentials(monkeypatch):
    from app.services import feishu_permissions as feishu
    monkeypatch.setenv('FEISHU_USER_ACCESS_TOKEN', 'private-user-token')
    client_factory = httpx.Client
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer private-user-token'
        return httpx.Response(403, json={'code': 1063002, 'msg': 'private-user-token secret'})
    monkeypatch.setattr(feishu, '_client', lambda: client_factory(transport=httpx.MockTransport(handler)))
    with pytest.raises(feishu.GrantError) as error:
        feishu.grant({'url': 'https://my.feishu.cn/docx/Document123', 'permission': 'view'},
                     {'member_type': 'openid', 'member_id': 'ou_test'})
    assert '1063002' in str(error.value)
    assert 'private-user-token' not in str(error.value)


def test_missing_credentials_are_reported_without_network(monkeypatch):
    from app.services import feishu_permissions as feishu
    monkeypatch.setattr(feishu.feishu_settings, 'credentials', lambda: {'app_id': '', 'app_secret': ''})
    for name in ('FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_USER_ACCESS_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    feishu.clear_token_cache()
    with pytest.raises(feishu.GrantError, match='凭据'):
        feishu.grant({'url': 'https://my.feishu.cn/docx/Document123', 'permission': 'view'},
                     {'member_type': 'openid', 'member_id': 'ou_test'})
