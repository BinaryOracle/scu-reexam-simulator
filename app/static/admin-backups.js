/** Module downloads and explicit, validated restores for the system owner. */
import { api, state } from './api.js?v=20261114-ui-v17';
import { $, el, notify, confirmAction } from './ui.js?v=20261114-ui-v17';

let catalog = [];
let selected = null;
let preview = null;
let revision = 0;
let busy = false;
const linkedModules = [['accounts', 'credits'], ['courses', 'live']];

function formatSize(bytes) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index++; }
  return `${bytes.toFixed(index ? 1 : 0)} ${units[index]}`;
}
function updateSelection() {
  const choices = selected || new Set();
  for (const input of document.querySelectorAll('#backupModuleList input')) {
    input.checked = choices.has(input.value);
    input.closest('label').classList.toggle('selected', input.checked);
  }
  $('backupStatus').textContent = `已选择 ${choices.size} / ${catalog.length} 个模块`;
  $('exportBackup').disabled = busy || !choices.size;
}
function setBusy(value) {
  busy = value;
  for (const control of document.querySelectorAll('#backupPanel button, #backupPanel input')) control.disabled = value;
  $('restoreBackup').disabled = value || !preview;
  if (!value) updateSelection();
}
export async function refreshBackupModules() {
  const panel = $('backupPanel');
  if (!panel) return;
  panel.hidden = !state.user?.is_superadmin;
  if (panel.hidden || busy) return;
  const token = state.token;
  const refreshed = await api('/admin/backups/modules');
  if (state.token !== token) return;
  catalog = refreshed;
  if (!selected) selected = new Set(refreshed.map(module => module.id));
  $('backupModuleList').replaceChildren(...refreshed.map(module => {
    const label = el('label', '', 'backup-module-card');
    const checkbox = el('input');
    checkbox.type = 'checkbox'; checkbox.value = module.id;
    checkbox.setAttribute('aria-label', `选择${module.name}备份`);
    const copy = el('span', '', 'backup-module-copy');
    copy.append(el('strong', module.name), el('span', module.description, 'backup-module-description'));
    const meta = el('span', '', 'backup-module-meta');
    meta.append(el('span', module.media ? `${module.rows} 个文件` : `${module.rows} 条记录`));
    if (module.media) meta.append(el('span', formatSize(module.estimated_bytes)));
    label.append(checkbox, copy, meta);
    checkbox.addEventListener('change', () => {
      const ids = linkedModules.find(group => group.includes(module.id)) || [module.id];
      for (const id of ids) checkbox.checked ? selected.add(id) : selected.delete(id);
      updateSelection();
    });
    return label;
  }));
  updateSelection();
}
async function downloadBackup() {
  if (busy || !selected?.size) return;
  setBusy(true);
  $('backupStatus').textContent = '正在打包备份，媒体较多时可能需要一些时间…';
  try {
    const response = await fetch('/api/admin/backups/export', {
      method: 'POST', headers: { Authorization: `Bearer ${state.token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ modules: [...selected] }),
    });
    if (!response.ok) {
      if (response.status === 401) window.dispatchEvent(new Event('session-expired'));
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : '备份导出失败，请重试');
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = el('a');
    link.href = url;
    link.download = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/i)?.[1] || 'scu-backup.zip';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    notify('备份已下载，包含密码与密钥，请存放在受保护的位置。', 'info');
  } catch (error) {
    notify(error.message, 'error');
  } finally { setBusy(false); }
}
function clearPreview() {
  revision++;
  preview = null;
  $('backupPreview').replaceChildren();
  $('backupPreview').hidden = true;
  $('restoreBackup').disabled = true;
  $('backupRestoreStatus').textContent = '';
}
async function previewBackup(event) {
  event.preventDefault();
  if (busy) return;
  const file = $('backupFile').files[0];
  if (!file) { notify('请先选择备份 ZIP 文件。', 'error'); return; }
  clearPreview();
  const current = revision;
  const token = state.token;
  setBusy(true);
  $('backupRestoreStatus').textContent = '正在验证文件完整性、密码密钥和数据关联，当前数据不会改变…';
  try {
    const body = new FormData(); body.append('file', file);
    const result = await api('/admin/backups/preview', { method: 'POST', body });
    if (current !== revision || token !== state.token) return;
    preview = { ...result, file };
    const list = el('div', '', 'backup-preview-modules');
    for (const module of result.modules) list.append(el('span', `${module.name} · ${module.rows} 条`, 'backup-preview-tag'));
    const date = new Date(result.exported_at);
    $('backupPreview').append(el('strong', '备份校验通过'),
      el('p', `${Number.isNaN(date.valueOf()) ? '未知备份时间' : date.toLocaleString('zh-CN')} · ${result.files} 个媒体文件${result.includes_passwords ? ' · 含账号密码' : ''}`), list);
    for (const warning of result.warnings) $('backupPreview').append(el('p', warning, 'backup-warning'));
    $('backupPreview').hidden = false;
    $('backupRestoreStatus').textContent = '请确认模块范围。恢复会替换这些模块的现有数据，并使所有账号退出登录。';
  } catch (error) {
    $('backupRestoreStatus').textContent = error.message;
    notify(error.message, 'error');
  } finally { setBusy(false); }
}
async function restoreBackup() {
  if (busy || !preview) return;
  const candidate = preview;
  // Lock file selection while the confirmation dialog is open.
  setBusy(true);
  try {
    const names = candidate.modules.map(module => module.name).join('、');
    if (!await confirmAction(`将以备份内容替换「${names}」的现有数据，所有账号需要重新登录。恢复前会自动保存当前数据库和被覆盖的媒体文件。请先结束面试、直播与录制，并暂停其他操作。`,
      { title: '确认恢复这份备份？', confirmText: '确认替换并恢复', danger: true })) return;
    $('backupRestoreStatus').textContent = '正在保存安全副本并恢复，请保持页面打开…';
    const body = new FormData(); body.append('file', candidate.file);
    body.append('sha256', candidate.sha256); body.append('confirmation', 'RESTORE');
    const result = await api('/admin/backups/restore', { method: 'POST', body });
    clearPreview();
    notify(`恢复完成。安全副本：${result.safety_backup}。请使用恢复后的账号密码重新登录。`, 'info');
    window.dispatchEvent(new Event('session-expired'));
  } catch (error) {
    $('backupRestoreStatus').textContent = error.message;
    notify(error.message, 'error');
  } finally { setBusy(false); }
}
export function setupBackups() {
  $('refreshBackupModules')?.addEventListener('click', () => void refreshBackupModules().catch(error => notify(error.message, 'error')));
  $('exportBackup')?.addEventListener('click', () => void downloadBackup());
  $('backupSelectAll')?.addEventListener('click', () => { selected = new Set(catalog.map(module => module.id)); updateSelection(); });
  $('backupSelectNone')?.addEventListener('click', () => { selected = new Set(); updateSelection(); });
  $('backupFile')?.addEventListener('change', clearPreview);
  $('backupRestoreForm')?.addEventListener('submit', event => void previewBackup(event));
  $('restoreBackup')?.addEventListener('click', () => void restoreBackup());
  window.addEventListener('session-expired', () => { selected = null; clearPreview(); });
}
