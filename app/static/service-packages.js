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
const MODULE_LABELS = { training: '每日训练', coding: '算法带刷', interview: '模拟面试', exam: '上机考试' };
const FEISHU_LABELS = { view: '可阅读', edit: '可编辑', full_access: '可管理' };

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

/** Administrators can enable packages and remove entries; inviters can inspect purchase details. */
export async function openPurchaseDetails(user, { manage = false, onChange = async () => {} } = {}) {
  const { dialog, body } = dialogShell(`${user.username} · 套餐服务`, true);
  const token = state.token;
  const base = manage ? `/admin/users/${user.id}/package-purchases` : `/profile/referrals/${user.id}/package-purchases`;
  let revision = 0;
  async function load() {
    const current = ++revision;
    body.replaceChildren(el('p', '正在加载购买明细…', 'muted'));
    try {
      const [data, options] = await Promise.all([
        api(base), manage ? api('/admin/service-packages') : Promise.resolve([]),
      ]);
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
    if (!data.items.length) list.append(emptyState('暂无有效套餐服务', manage ? '可在下方为该用户添加并启用套餐。' : '用户已启用的套餐服务会显示在这里。', '◇'));
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
        if (!await confirmAction(`移除「${item.package_name}」后，该记录将不再计入金额与返利汇总。已发放的模块、积分、课程等权益不会自动撤销。`, { title: '移除套餐服务记录？', confirmText: '确认移除', danger: true })) return;
        if (!dialog.open || token !== state.token) return;
        await api(`${base}/${item.id}`, { method: 'DELETE' });
        notify('套餐服务记录已移除。'); await changed();
      }, 'text-button danger'));
      if (manage) {
        const authorization = el('details', '', 'package-document-authorization');
        authorization.append(el('summary', '查看文档授权状态'));
        const status = el('div', '', 'package-help');
        const refresh = button('刷新状态', loadAuthorization, 'text-button');
        const retry = button('重试文档授权', async () => {
          await api(`${base}/${item.id}/benefits/retry`, { method: 'POST' });
          notify('已重新提交文档授权，请稍后刷新状态。', 'info');
          await loadAuthorization();
        }, 'text-button');
        retry.hidden = true;
        authorization.append(status, refresh, retry);
        let loaded = false;
        async function loadAuthorization() {
          const result = await api(`${base}/${item.id}/benefits`);
          if (!authorization.isConnected || !dialog.open || token !== state.token) return;
          status.replaceChildren();
          const grants = result.grants.filter(grant => grant.kind === 'feishu');
          if (!grants.length) status.append(el('p', '此记录没有文档授权任务。'));
          const labels = { pending: '待处理', processing: '授权中', granted: '已授权', failed: '授权失败' };
          for (const grant of grants) {
            status.append(el('p', `${grant.payload.resource.name || '飞书资料'} · ${labels[grant.status] || grant.status}${grant.error ? `：${grant.error}` : ''}`));
          }
          retry.hidden = !grants.some(grant => ['pending', 'failed'].includes(grant.status));
          loaded = true;
        }
        authorization.addEventListener('toggle', () => {
          if (authorization.open && !loaded) void run(loadAuthorization, refresh);
        });
        row.append(authorization);
      }
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
      const label = el('label', '添加套餐服务', 'package-enable-field');
      const select = el('select'); select.required = true; select.setAttribute('aria-label', '选择并启用套餐');
      select.append(new Option(available.length ? '请选择要启用的套餐' : '暂无可启用的套餐', ''));
      for (const item of available) select.append(new Option(`${item.name} · ${packageMoney(item.price_fen)}`, item.id));
      label.append(select);
      const recipientType = el('select'); recipientType.setAttribute('aria-label', '飞书授权对象类型');
      recipientType.append(new Option('飞书手机号', 'mobile'), new Option('飞书邮箱', 'email'));
      const recipientId = el('input');
      const recipientFields = el('div', '', 'package-recipient-fields'); recipientFields.hidden = true;
      const typeLabel = el('label', '授权对象类型'); typeLabel.append(recipientType);
      const idLabel = el('label', '飞书手机号'); idLabel.append(recipientId);
      recipientFields.append(typeLabel, idLabel);
      function syncRecipientType() {
        const email = recipientType.value === 'email';
        idLabel.firstChild.textContent = email ? '飞书邮箱' : '飞书手机号';
        recipientId.type = email ? 'email' : 'tel';
        recipientId.inputMode = email ? 'email' : 'tel';
        if (email) recipientId.removeAttribute('pattern');
        else recipientId.pattern = '(?:1[0-9]{10}|\\+[1-9][0-9]{6,14})';
        recipientId.title = email ? '请输入用户绑定飞书的邮箱' : '中国大陆手机号填 11 位；其他地区需加 + 国际区号';
        recipientId.placeholder = email ? '请输入用户绑定飞书的邮箱' : '请输入飞书绑定手机号，如 13800138000';
        recipientId.setAttribute('aria-label', email ? '飞书邮箱' : '飞书手机号');
      }
      recipientType.addEventListener('change', syncRecipientType);
      syncRecipientType();
      select.addEventListener('change', () => {
        const chosen = available.find(value => value.id === Number(select.value));
        const hasFeishu = Boolean(chosen?.benefits?.feishu_resources?.length);
        recipientFields.hidden = !hasFeishu;
        recipientId.required = hasFeishu;
        recipientId.disabled = recipientType.disabled = !hasFeishu;
      });
      recipientId.disabled = recipientType.disabled = true;
      const hint = el('p', '启用后自动开通套餐配置的模块权限、积分和课程。飞书资料可通过绑定手机号定位用户，或使用飞书邮箱授权；手机号查询受应用通讯录范围限制。', 'package-help package-enable-hint');
      const submit = el('button', '添加并启用套餐', 'button primary'); submit.type = 'submit'; submit.disabled = !available.length;
      const controls = el('div', '', 'package-enable-controls'); controls.append(label, submit);
      form.append(controls, recipientFields, hint);
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        void run(async () => {
          if (!await confirmAction('确认要为该用户添加并启用所选套餐吗？系统会记录套餐服务金额与返利，并自动发放套餐配置的相关权益。', { title: '启用套餐服务？', confirmText: '确认启用' })) return;
          if (!dialog.open || token !== state.token) return;
          await api(base, { method: 'POST', body: JSON.stringify({ package_id: Number(select.value), ...(recipientFields.hidden ? {} : { feishu_recipient: { member_type: recipientType.value, member_id: recipientId.value.trim() } }) }) });
          notify(recipientFields.hidden ? '套餐服务已添加并启用，相关权益已处理。' : '套餐已启用，文档授权已提交，可在套餐明细中查看授权状态。'); await changed();
        }, submit);
      });
      body.append(form);
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
  const originalBenefits = item?.benefits || {};
  const benefitPanel = el('section', '', 'package-benefits-editor');
  benefitPanel.append(el('h3', '购买后自动开放'), el('p', '仅影响之后登记的购买；已登记用户的权益快照不会随套餐修改而变化。', 'package-help package-benefit-intro'));
  const moduleGrid = el('div', '', 'package-module-options');
  const moduleInputs = {};
  for (const [key, labelText] of Object.entries(MODULE_LABELS)) {
    const label = el('label'); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.checked = (originalBenefits.modules || []).includes(key);
    checkbox.setAttribute('aria-label', labelText); moduleInputs[key] = checkbox; label.append(checkbox, el('span', labelText)); moduleGrid.append(label);
  }
  const giftLabel = el('label', '赠送积分', 'package-benefit-field package-gift-field'); const giftPoints = el('input'); giftPoints.type = 'number'; giftPoints.min = '0'; giftPoints.max = '1000000'; giftPoints.step = '1'; giftPoints.value = originalBenefits.gift_points || 0; giftPoints.setAttribute('aria-label', '购买套餐赠送积分'); giftLabel.append(giftPoints);
  const courseLabel = el('div', '', 'package-benefit-field package-course-field');
  const courseHeading = el('span', '套餐默认课程（可多选）', 'package-course-label');
  const courseList = el('div', '', 'package-course-list'); courseList.append(el('p', '正在加载课程…', 'package-course-empty')); courseList.setAttribute('role', 'group'); courseList.setAttribute('aria-label', '套餐默认开放课程');
  courseLabel.append(courseHeading, courseList);
  const courseHelp = el('p', '积分课程按配置的开放起止日期授权；私域课程会加入用户课程库。选择当前管理员可管理的已发布课程。', 'package-help');
  const resourceList = el('div', '', 'package-feishu-resources');
  function addFeishuResource(resource = {}) {
    const row = el('div', '', 'package-feishu-resource');
    const title = el('input'); title.value = resource.name || ''; title.placeholder = '资料名称'; title.setAttribute('aria-label', '飞书资料名称');
    const url = el('input'); url.value = resource.url || ''; url.placeholder = 'https://my.feishu.cn/drive/folder/...'; url.setAttribute('aria-label', '飞书文档或目录链接');
    const perm = el('select'); perm.setAttribute('aria-label', '飞书文档权限');
    for (const value of ['view', 'edit', 'full_access']) perm.append(new Option(FEISHU_LABELS[value], value));
    perm.value = resource.permission || 'view';
    row.append(title, url, perm, button('移除', () => row.remove(), 'text-button danger')); resourceList.append(row);
  }
  for (const resource of originalBenefits.feishu_resources || []) addFeishuResource(resource);
  const addResource = button('添加飞书文档或目录', () => addFeishuResource(), 'button package-add-resource');
  const feishuHelp = el('p', '启用套餐时可填写接收人的飞书绑定手机号或邮箱。手机号定位需配置飞书应用凭据、contact:user.id:readonly 权限及通讯录范围；文件夹授权要求调用身份具有管理权限。飞书分享密码不参与授权，请勿填入套餐链接。', 'package-help');
  benefitPanel.append(moduleGrid, giftLabel, courseLabel, courseHelp, resourceList, addResource, feishuHelp);
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
  form.append(fields, benefitPanel, toolbar, markdown, uploadStatus, preview, help, footer);
  let courseOptionsLoaded = false;
  void api('/courses?scope=managed').then(data => {
    if (!dialog.open || token !== state.token) return;
    const selected = new Set(originalBenefits.course_ids || []);
    const courses = data.items.filter(course => course.publication_status === 'published');
    courseList.replaceChildren();
    if (!courses.length) courseList.append(el('p', '暂无已发布课程可选。', 'package-course-empty'));
    for (const course of courses) {
      const option = el('label', '', `package-course-option${selected.has(course.id) ? ' is-selected' : ''}`);
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = course.id; checkbox.checked = selected.has(course.id);
      checkbox.addEventListener('change', () => option.classList.toggle('is-selected', checkbox.checked));
      const copy = el('span', '', 'package-course-copy');
      const title = el('strong', course.title, 'package-course-title');
      const access = course.access_mode === 'points'
        ? `积分课程 · ${course.points_price} 积分 · ${course.points_access_start_date || '未设置起始日'} 至 ${course.points_access_end_date || '未设置结束日'}`
        : '私域课程 · 加入用户课程库';
      copy.append(title, el('small', access, 'package-course-meta'));
      option.append(checkbox, copy); courseList.append(option);
    }
    courseOptionsLoaded = true;
  }).catch(() => { courseList.replaceChildren(el('p', '课程列表暂时无法加载，请关闭后重新打开套餐编辑。', 'package-course-empty package-benefit-error')); });
  form.addEventListener('submit', event => {
    event.preventDefault(); if (!form.reportValidity()) return;
    void run(async () => {
      await api(item ? `/admin/service-packages/${item.id}` : '/admin/service-packages', {
        method: item ? 'PATCH' : 'POST', body: JSON.stringify({ name: name.value.trim(), price_yuan: price.value, rebate_percent: rate.value, description: markdown.value, benefits: { modules: Object.entries(moduleInputs).filter(([, checkbox]) => checkbox.checked).map(([key]) => key), gift_points: Number(giftPoints.value || 0), course_ids: courseOptionsLoaded ? [...courseList.querySelectorAll('input:checked')].map(option => Number(option.value)) : (originalBenefits.course_ids || []), feishu_resources: [...resourceList.children].map(row => ({ name: row.children[0].value.trim(), url: row.children[1].value.trim(), permission: row.children[2].value })) } }),
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
