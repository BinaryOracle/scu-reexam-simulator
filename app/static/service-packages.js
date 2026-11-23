/** Package catalog and shared purchase-detail reader. All money comes from server fen totals. */
import { api, state } from './api.js?v=20261122-session-guard-v1';
import { $, el, button, emptyState, notify, confirmAction, run } from './ui.js?v=20261114-ui-v17';
import { packageMoney, rebateText, filterPackages, insertPastedImages } from './service-package-model.mjs?v=20261123-packages-v2';
export { rebateText };
let catalog = [], page = 1, request = 0;
const packageImageUrls = new Set();
let search = '', status = 'all';
const pageSize = 8;
const rateText = rate => `${Number((rate / 100).toFixed(2))}%`;

function releasePackageImages(container = null) {
  for (const image of (container || document).querySelectorAll('img[data-package-object-url]')) {
    const url = image.dataset.packageObjectUrl;
    URL.revokeObjectURL(url); packageImageUrls.delete(url);
    delete image.dataset.packageObjectUrl;
  }
  if (!container) {
    packageImageUrls.forEach(url => URL.revokeObjectURL(url));
    packageImageUrls.clear();
  }
}

async function hydratePackageImages(container, dialog = null) {
  const token = state.token;
  for (const image of container.querySelectorAll('img')) {
    const match = /^\/api\/(?:admin\/)?announcements\/assets\/([a-f0-9]{32})$/.exec(image.getAttribute('src') || '');
    if (!match) continue;
    image.removeAttribute('src');
    image.alt ||= '套餐详情图片';
    try {
      const response = await fetch(`/api/admin/announcements/assets/${match[1]}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error('图片加载失败');
      const blob = await response.blob();
      if (token !== state.token || !image.isConnected || (dialog && !dialog.open)) return;
      const url = URL.createObjectURL(blob);
      packageImageUrls.add(url);
      image.dataset.packageObjectUrl = url;
      image.src = url;
    } catch {
      if (token === state.token && image.isConnected) image.alt = '图片暂时无法加载';
    }
  }
}

function dialogShell(title, wide = false) {
  const previous = document.activeElement;
  const dialog = el('dialog', '', `account-dialog package-dialog${wide ? ' package-dialog-wide' : ''}`);
  const heading = el('h2', title); heading.id = `package-dialog-${crypto.randomUUID()}`;
  dialog.setAttribute('aria-labelledby', heading.id);
  const header = el('header', '', 'dialog-header');
  header.append(heading, button('×', () => dialog.close(), 'icon-button'));
  header.lastChild.setAttribute('aria-label', '关闭对话框');
  const body = el('div', '', 'dialog-body package-dialog-body');
  dialog.append(header, body);
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  } });
  dialog.addEventListener('close', () => {
    releasePackageImages(dialog);
    dialog.remove();
    if (previous?.isConnected) previous.focus({ preventScroll: true });
  }, { once: true });
  document.body.append(dialog); dialog.showModal();
  return { dialog, body };
}

export function purchaseSummaryButton(user, open) {
  const control = button('', open, 'package-purchase-summary');
  control.setAttribute('aria-label', `查看 ${user.username} 的套餐服务明细`);
  control.append(el('strong', packageMoney(user.purchase_total_fen)),
    el('span', `返利 ${packageMoney(user.rebate_total_fen)}`),
    el('small', `${user.purchase_count} 个套餐 · 查看明细 ›`));
  return control;
}

/** Both admin and inviter use the same detail body; write controls are admin-only. */
export async function openPurchaseDetails(user, { manage = false, onChange = async () => {} } = {}) {
  const { dialog, body } = dialogShell(`${user.username} · 套餐服务`, true);
  const token = state.token;
  const base = manage ? `/admin/users/${user.id}/package-purchases` : `/profile/referrals/${user.id}/package-purchases`;
  let revision = 0;
  async function load() {
    const current = ++revision;
    body.replaceChildren(el('p', '正在加载购买明细…', 'muted'));
    try {
      const [data, options] = await Promise.all([api(base), manage ? api('/admin/service-packages') : Promise.resolve([])]);
      if (!dialog.open || token !== state.token || current !== revision) return;
      render(data, options);
    } catch (error) {
      if (!dialog.open || token !== state.token || current !== revision) return;
      const errorBox = emptyState('购买明细暂时无法加载', error.message, '◇');
      errorBox.append(button('重新加载', load)); body.replaceChildren(errorBox);
    }
  }
  async function changed() {
    await load();
    try { await onChange(); }
    catch { notify('购买记录已保存，但列表刷新失败，请刷新列表查看。', 'info'); }
  }
  function render(data, options) {
    body.replaceChildren();
    const note = el('p', '按购买时的价格和返利比例计算；下架套餐暂不计入，重新启用后恢复。', 'package-help');
    const list = el('div', '', 'package-purchase-list');
    if (!data.items.length) list.append(emptyState('暂无有效购买记录', manage ? '从下方选择已启用套餐，为该用户登记购买。' : '用户购买的套餐经管理员登记后，会在这里显示。', '◇'));
    for (const item of data.items) {
      const row = el('article', '', 'package-purchase-row');
      const identity = el('div', '', 'package-purchase-name');
      identity.append(el('strong', item.package_name), el('small', new Date(item.created * 1000).toLocaleDateString('zh-CN')));
      const price = el('div'); price.append(el('small', '套餐价格'), el('strong', packageMoney(item.price_fen)));
      const rate = el('div'); rate.append(el('small', '返利比例'), el('strong', rateText(item.rebate_basis_points)));
      const rebate = el('div'); rebate.append(el('small', '返利金额'), el('strong', packageMoney(item.rebate_fen)),
        el('small', rebateText(data.rebate_status === 'unset' ? 'unset' : item.redeemed ? 'redeemed' : 'pending')));
      row.append(identity, price, rate, rebate);
      if (manage) row.append(button('移除', async () => {
        if (!await confirmAction(`移除「${item.package_name}」的购买登记后，该记录将不再计入金额与返利汇总。`, { title: '移除购买记录？', confirmText: '确认移除', danger: true })) return;
        if (!dialog.open || token !== state.token) return;
        await api(`${base}/${item.id}`, { method: 'DELETE' });
        notify('购买记录已移除。'); await changed();
      }, 'text-button danger'));
      list.append(row);
    }
    const total = el('footer', '', 'package-purchase-total');
    const purchased = el('div'); purchased.append(el('span', '套餐服务总额'), el('strong', packageMoney(data.purchase_total_fen)));
    const earned = el('div'); earned.append(el('span', '总返利金额'), el('strong', packageMoney(data.rebate_total_fen)));
    total.append(purchased, earned, el('span', rebateText(data.rebate_status), `account-rebate-state ${data.rebate_status}`));
    body.append(note, list, total);
    if (data.rebate_status !== 'unset') body.append(el('p', `待兑换 ${packageMoney(data.pending_rebate_fen)} · 已兑换 ${packageMoney(data.redeemed_rebate_fen)}`, 'package-help package-settlement-breakdown'));
    if (manage) {
      const activeIds = new Set(data.items.map(item => item.package_id));
      const available = options.filter(item => item.enabled && !activeIds.has(item.id));
      const form = el('form', '', 'package-purchase-add');
      const label = el('label', '登记购买套餐');
      const select = el('select'); select.required = true; select.setAttribute('aria-label', '选择购买套餐');
      select.append(new Option(available.length ? '请选择套餐' : '暂无可登记的已启用套餐', ''));
      for (const item of available) select.append(new Option(`${item.name} · ${packageMoney(item.price_fen)} · 返利 ${rateText(item.rebate_basis_points)}`, item.id));
      label.append(select);
      const submit = el('button', '登记购买', 'button primary'); submit.type = 'submit'; submit.disabled = !available.length;
      form.append(label, submit);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        void run(async () => {
          if (!await confirmAction('请确认用户已购买该套餐。此操作只登记购买与返利，不会扣除用户积分或发起支付。', { title: '确认登记购买？', confirmText: '确认登记' })) return;
          if (!dialog.open || token !== state.token) return;
          await api(base, { method: 'POST', body: JSON.stringify({ package_id: Number(select.value) }) });
          notify('购买套餐已登记。'); await changed();
        }, submit);
      });
      body.append(form);
      if (user.legacy_purchase_note) body.append(el('p', `历史手填备注：${user.legacy_purchase_note}（未计入金额，请按实际购买情况登记套餐）`, 'package-help package-legacy-note'));
    }
  }
  await load();
}

function openPackageEditor(item = null) {
  const { dialog, body } = dialogShell(item ? '编辑套餐' : '新增套餐', true);
  const token = state.token;
  const form = el('form', '', 'package-editor');
  const fields = el('div', '', 'package-editor-fields');
  const input = (title, value, type, extra = {}) => {
    const label = el('label', title);
    const field = el('input'); field.type = type; field.value = value;
    field.required = true; Object.assign(field, extra); field.setAttribute('aria-label', title);
    label.append(field); fields.append(label); return field;
  };
  const name = input('套餐名', item?.name || '', 'text', { maxLength: 100 });
  const price = input('价格（元）', item ? (item.price_fen / 100).toFixed(2) : '', 'number', { min: '0', max: '100000000', step: '0.01' });
  const rate = input('返利比例（%）', item ? (item.rebate_basis_points / 100).toFixed(2) : '5', 'number', { min: '0', max: '100', step: '0.01' });
  const markdown = el('textarea'); markdown.value = item?.description || ''; markdown.maxLength = 50000;
  markdown.rows = 10; markdown.placeholder = '## 套餐内容\n\n- 服务内容\n- 适合人群\n- 服务说明';
  markdown.setAttribute('aria-label', '套餐详情 Markdown');
  const uploadStatus = el('p', '', 'package-markdown-status');
  uploadStatus.setAttribute('role', 'status'); uploadStatus.hidden = true;
  const setUploadStatus = (message, error = false) => {
    uploadStatus.textContent = message; uploadStatus.hidden = !message;
    uploadStatus.classList.toggle('is-error', error);
  };
  markdown.addEventListener('paste', event => {
    const images = [...(event.clipboardData?.items || [])]
      .filter(item => ['image/png', 'image/jpeg', 'image/webp'].includes(item.type))
      .map(item => item.getAsFile()).filter(Boolean);
    if (!images.length) return;
    event.preventDefault();
    markdown.readOnly = true;
    setUploadStatus(`正在上传 ${images.length} 张图片…`);
    void insertPastedImages(markdown, images, async file => {
      const data = new FormData(); data.append('file', file, file.name || 'pasted-image.png');
      return api('/admin/announcements/assets', { method: 'POST', body: data });
    }).then(count => {
      if (!dialog.open || token !== state.token) return;
      setUploadStatus(`已插入 ${count} 张图片，保存套餐后生效。`);
      markdown.focus();
    }).catch(error => {
      if (dialog.open && token === state.token) setUploadStatus(error.message, true);
    }).finally(() => { markdown.readOnly = false; });
  });
  const preview = el('div', '', 'package-markdown'); preview.hidden = true;
  const toolbar = el('div', '', 'package-editor-toolbar');
  const label = el('strong', '套餐详情');
  const previewControl = button('预览 Markdown', async () => {
    if (!preview.hidden) { markdown.hidden = false; preview.hidden = true; previewControl.textContent = '预览 Markdown'; return; }
    const result = await api('/question-markdown/preview', { method: 'POST', body: JSON.stringify({ markdown: markdown.value }) });
    if (!dialog.open || token !== state.token) return;
    releasePackageImages(preview);
    preview.innerHTML = result.html; preview.hidden = false; markdown.hidden = true; previewControl.textContent = '继续编辑';
    void hydratePackageImages(preview, dialog);
  }, 'button quiet');
  toolbar.append(label, previewControl);
  const help = el('p', item ? '支持 Markdown；可直接粘贴截图或图片，图片会自动上传。修改后的价格和比例仅用于之后登记的新购买记录。' : '支持 Markdown；可直接粘贴截图或图片，图片会自动上传。购买记录由管理员登记。', 'package-help');
  const footer = el('div', '', 'package-editor-footer');
  const save = el('button', '保存套餐', 'button primary'); save.type = 'submit';
  footer.append(button('取消', () => dialog.close()), save);
  form.append(fields, toolbar, markdown, uploadStatus, preview, help, footer);
  form.addEventListener('submit', event => {
    event.preventDefault(); if (!form.reportValidity()) return;
    void run(async () => {
      await api(item ? `/admin/service-packages/${item.id}` : '/admin/service-packages', {
        method: item ? 'PATCH' : 'POST', body: JSON.stringify({ name: name.value.trim(), price_yuan: price.value, rebate_percent: rate.value, description: markdown.value }),
      });
      if (token !== state.token) return;
      if (dialog.open) dialog.close(); notify('套餐已保存。');
      try { await refreshServicePackages(); }
      catch { notify('套餐已保存，但目录刷新失败，请刷新页面查看。', 'info'); }
    }, save);
  });
  body.append(form); name.focus();
}

function renderCatalog() {
  const root = $('servicePackagesContent');
  releasePackageImages(root);
  const filtered = filterPackages(catalog, search, status);
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize)); page = Math.min(page, pages);
  const list = el('div', '', 'package-catalog-grid');
  if (!filtered.length) list.append(emptyState(catalog.length ? '没有匹配的套餐' : '还没有套餐', catalog.length ? '调整名称或上架状态筛选。' : '新增套餐后，即可在用户管理中登记购买。', '◇'));
  for (const item of filtered.slice((page - 1) * pageSize, page * pageSize)) {
    const card = el('article', '', `panel package-card${item.enabled ? '' : ' package-card-disabled'}`);
    const heading = el('div', '', 'package-card-heading');
    heading.append(el('h3', item.name), el('span', item.enabled ? '已启用' : '已下架', `package-catalog-state ${item.enabled ? 'enabled' : ''}`));
    const metrics = el('div', '', 'package-card-metrics');
    const price = el('div'); price.append(el('small', '套餐价格'), el('strong', packageMoney(item.price_fen)));
    const rate = el('div'); rate.append(el('small', '返利比例'), el('strong', rateText(item.rebate_basis_points)));
    metrics.append(price, rate);
    const details = el('details', '', 'package-card-description');
    details.append(el('summary', '查看套餐详情'));
    const content = el('div', '', 'package-markdown'); content.innerHTML = item.description_html || '<p>暂无说明</p>'; details.append(content);
    void hydratePackageImages(content);
    const footer = el('div', '', 'package-card-footer');
    footer.append(el('small', `${item.purchase_count} 条购买登记`), button('编辑', () => openPackageEditor(item), 'button quiet'),
      button(item.enabled ? '下架' : '启用', async () => {
        const title = item.enabled ? '下架这个套餐？' : '重新启用这个套餐？';
        const message = item.enabled
          ? `「${item.name}」下架后，关联的 ${item.purchase_count} 条购买记录将暂时隐藏，不再计入套餐总额与返利；记录不会删除，重新启用后恢复。`
          : `「${item.name}」启用后，关联购买记录及原有返利状态将恢复展示并重新计入汇总。`;
        if (!await confirmAction(message, { title, confirmText: item.enabled ? '确认下架' : '确认启用', danger: item.enabled })) return;
        await api(`/admin/service-packages/${item.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !item.enabled }) });
        notify(item.enabled ? '套餐已下架，购买记录已暂时隐藏。' : '套餐已启用，购买记录已恢复。');
        await refreshServicePackages();
      }, 'button secondary'));
    card.append(heading, metrics, details, footer); list.append(card);
  }
  const pager = el('div', '', 'package-pagination');
  const previous = button('上一页', () => { page--; renderCatalog(); }); previous.disabled = page === 1;
  const next = button('下一页', () => { page++; renderCatalog(); }); next.disabled = page === pages;
  pager.append(el('span', `共 ${filtered.length} 个套餐 · 第 ${page} / ${pages} 页`), previous, next);
  root.replaceChildren(list, pager);
}

export async function refreshServicePackages() {
  const root = $('servicePackagesContent');
  if (!$('newServicePackage').dataset.ready) {
    $('newServicePackage').dataset.ready = 'true';
    $('newServicePackage').addEventListener('click', () => openPackageEditor());
    $('servicePackageSearch').addEventListener('input', event => { search = event.target.value; page = 1; renderCatalog(); });
    $('servicePackageStatus').addEventListener('change', event => { status = event.target.value; page = 1; renderCatalog(); });
  }
  const current = ++request, token = state.token;
  root.replaceChildren(el('p', '正在加载套餐…', 'muted'));
  try {
    const data = await api('/admin/service-packages');
    if (current !== request || token !== state.token) return;
    catalog = data; renderCatalog();
  } catch (error) {
    if (current !== request || token !== state.token) return;
    const message = emptyState('套餐暂时无法加载', error.message, '◇');
    message.append(button('重新加载', refreshServicePackages)); root.replaceChildren(message);
  }
}
