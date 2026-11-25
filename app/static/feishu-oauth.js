/** Connect the shared Feishu document manager without exposing tokens in the browser. */
import { api, state } from './api.js?v=20261122-session-guard-v1';
import { $, confirmAction, notify } from './ui.js?v=20261114-ui-v17';

export async function refreshFeishuOAuth() {
  const result = await api('/feishu/oauth/status');
  const status = $('feishuOAuthStatus');
  status.textContent = result.message;
  if (result.connected && result.refresh_expires_at) {
    status.textContent += ` · 当前续期凭据有效至 ${new Date(result.refresh_expires_at * 1000).toLocaleString('zh-CN')}`;
  }
  status.classList.toggle('form-error', result.needs_reconnect);
  $('connectFeishuOAuth').hidden = !state.user?.is_superadmin;
  $('connectFeishuOAuth').textContent = result.connected ? '重新连接账号' : '连接飞书账号';
  $('disconnectFeishuOAuth').hidden = !state.user?.is_superadmin || !(result.connected || result.needs_reconnect);
}

export function setupFeishuOAuth() {
  $('connectFeishuOAuth').addEventListener('click', async event => {
    const control = event.currentTarget;
    if (!await confirmAction('请先保存上方应用凭证与回调地址。接下来将前往飞书授权页面；请选择有权分享套餐资料的账号，并核对添加协作者与离线访问两项权限。', {
      title: '连接飞书资料管理账号', confirmText: '前往飞书',
    })) return;
    control.disabled = true;
    try {
      const result = await api('/feishu/oauth/connect', { method: 'POST' });
      window.location.assign(result.authorization_url);
    } catch (error) {
      $('feishuOAuthStatus').textContent = error.message;
      $('feishuOAuthStatus').classList.add('form-error');
    } finally { control.disabled = false; }
  });
  $('disconnectFeishuOAuth').addEventListener('click', async event => {
    if (!await confirmAction('断开后将停止使用此账号自动授权文档，已添加的文档协作者权限不会被撤回。可在飞书账号的应用授权管理中撤销授权。', {
      title: '断开飞书账号连接？', confirmText: '断开连接', danger: true,
    })) return;
    const control = event.currentTarget;
    control.disabled = true;
    try {
      await api('/feishu/oauth/connection', { method: 'DELETE' });
      await refreshFeishuOAuth();
      notify('飞书账号连接已断开。');
    } catch (error) { notify(error.message); }
    finally { control.disabled = false; }
  });
}
