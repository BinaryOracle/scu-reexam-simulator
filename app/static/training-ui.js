/** Shared accessible learning forms and authenticated source images. */
import { api, state } from './api.js?v=20261114-ui-v17';
import { el, button, notify } from './ui.js?v=20261114-ui-v17';
export const chapterNames = { interview: '面试篇', written_c: '笔试-软件工程篇', written_ai: '笔试-人工智能篇' };
const urls = new Set();
export function clearLearningMedia() {
  for (const url of urls) URL.revokeObjectURL(url);
  urls.clear();
  for (const dialog of document.querySelectorAll('dialog.learning-dialog')) dialog.close();
}
export function selectField(label, options, selected = '') {
  const wrap = el('div', '', 'learning-field');
  wrap.classList.add('learning-select-field');
  const input = el('select'); input.id = `learning-select-${crypto.randomUUID()}`;
  const title = el('label', label); title.htmlFor = input.id;
  for (const [value, text] of options) {
    const option = el('option', text); option.value = value; input.append(option);
  }
  input.value = selected; wrap.append(title, input);
  return { wrap, input };
}
export function pagination(container, result, change) {
  if (result.total <= result.page_size) return;
  const nav = el('div', '', 'learning-pagination');
  const prev = button('上一页', () => change(result.page - 1)); prev.disabled = result.page <= 1;
  const next = button('下一页', () => change(result.page + 1)); next.disabled = result.page * result.page_size >= result.total;
  nav.append(prev, el('span', `第 ${result.page} / ${Math.ceil(result.total / result.page_size)} 页`), next);
  container.append(nav);
}
export function learningDialog(title) {
  const dialog = el('dialog', '', 'account-dialog learning-dialog');
  const head = el('div', '', 'dialog-header');
  const heading = el('h2', title); heading.id = `learning-dialog-${crypto.randomUUID()}`;
  dialog.setAttribute('aria-labelledby', heading.id);
  const close = button('×', () => dialog.close(), 'icon-button'); close.setAttribute('aria-label', '关闭对话框');
  head.append(heading, close);
  const body = el('div', '', 'dialog-body'); const footer = el('div', '', 'dialog-footer');
  dialog.append(head, body, footer);
  const prior = document.activeElement;
  dialog.addEventListener('close', () => { dialog.remove(); if (prior?.isConnected) prior.focus(); }, { once: true });
  document.body.append(dialog); dialog.showModal();
  return { dialog, body, footer };
}
export function questionEditor(collections, item, save, official = false, defaultSection = 'interview', defaultCollectionId = '') {
  const { dialog, body, footer } = learningDialog(item ? '编辑题目' : official ? '新增公开训练题' : '新增私人题目');
  const form = el('form'); form.id = `question-form-${crypto.randomUUID()}`;
  const enabled = collections.filter(c => c.active !== 0 && c.active !== false);
  const initial = collections.find(c => c.id === (item?.collection_id || defaultCollectionId))?.section_id || defaultSection;
  const chapter = selectField('所属篇章', Object.entries(chapterNames), initial);
  const options = () => enabled.filter(c => c.section_id === chapter.input.value);
  const collection = selectField('所属题目集合', options().map(c => [c.id, c.name]), item?.collection_id || defaultCollectionId || options()[0]?.id);
  chapter.input.addEventListener('change', () => {
    collection.input.replaceChildren();
    for (const c of options()) { const option = el('option', c.name); option.value = c.id; collection.input.append(option); }
    update();
  });
  const question = el('textarea'); question.rows = 5; question.required = true; question.maxLength = 12000;
  question.value = item?.question || ''; question.id = `${form.id}-question`;
  const qlabel = el('label', '题目内容'); qlabel.htmlFor = question.id;
  const answerWrap = el('div', '', 'learning-answer-field');
  const answer = el('textarea'); answer.rows = 7; answer.maxLength = 60000; answer.value = item?.answer || ''; answer.id = `${form.id}-answer`;
  const alabel = el('label', '参考答案（可选）'); alabel.htmlFor = answer.id;
  answerWrap.append(alabel, answer);
  const help = el('p', official ? '保存后将进入公开训练题库。' : '仅自己可见。提交审核并通过后，其他用户才可练习。', 'muted');
  const error = el('p', '', 'form-error'); error.setAttribute('role', 'alert');
  const update = () => {
    const category = enabled.find(c => c.id === collection.input.value)?.category;
    answerWrap.hidden = category === 'oral';
    question.placeholder = category === 'translation' ? '请输入需要翻译的英文段落' : category === 'oral' ? '请输入英文题干' : '请输入题目内容';
    qlabel.textContent = category === 'translation' ? '英文原文' : '题目内容';
    alabel.textContent = category === 'translation' ? '参考译文（可选）' : '参考答案（可选）';
  };
  collection.input.addEventListener('change', update); update();
  form.append(help, chapter.wrap, collection.wrap, qlabel, question, answerWrap, error); body.append(form);
  const submit = el('button', '保存题目', 'button primary'); submit.type = 'submit'; submit.setAttribute('form', form.id);
  footer.append(button('取消', () => dialog.close()), submit);
  const token = state.token;
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (submit.disabled) return;
    submit.disabled = true; error.textContent = '';
    try {
      await save({ collection_id: collection.input.value, question: question.value.trim(), answer: answerWrap.hidden ? '' : answer.value.trim() });
      if (state.token === token && dialog.open) dialog.close();
    } catch (failure) { if (dialog.isConnected) error.textContent = failure.message; }
    finally { submit.disabled = false; }
  });
}
export function passageContext(item) {
  const node = document.createDocumentFragment();
  if (item.source_info?.kind === 'translation' && item.source_info.article) {
    node.append(el('p', `${item.source_info.article} · ${item.source_info.section || '选段'}`, 'learning-passage-source'));
  }
  return node;
}
export function referenceAnswer(item) {
  const node = el('div', '', 'learning-reference');
  const content = el('div', '', 'learning-answer-text');
  let list;
  for (const paragraph of (item.answer || '这道私人题尚未填写参考答案，可在“我的题目”中补充。').trim().split(/\n\s*\n/)) {
    if (/^[•●▪]\s*/.test(paragraph)) {
      if (!list) { list = el('ul'); content.append(list); }
      list.append(el('li', paragraph.replace(/^[•●▪]\s*/, '')));
    } else {
      list = undefined;
      content.append(el('p', paragraph));
    }
  }
  node.append(el('h3', item.category === 'translation' ? '参考译文' : '参考答案'), content);
  if (item.source_info?.kind === 'translation' && item.source_info.editorial_note) {
    const details = el('details', '', 'learning-source-images');
    details.append(el('summary', '校订说明'), el('p', item.source_info.editorial_note));
    node.append(details);
  }
  if (item.source_info?.glossary?.length) {
    const details = el('details', '', 'learning-source-images'); details.append(el('summary', '关键词对照'));
    const terms = el('dl', '', 'learning-glossary');
    for (const [en, zh] of item.source_info.glossary) terms.append(el('dt', en), el('dd', zh));
    details.append(terms); node.append(details);
  }
  if (item.images?.length) {
    const details = el('details', '', 'learning-source-images');
    details.append(el('summary', `查看原文对照 · ${item.images.length} 张`));
    let loaded = false;
    details.addEventListener('toggle', async () => {
      if (!details.open || loaded) return;
      loaded = true; const token = state.token;
      const images = el('div'); details.append(images);
      for (const path of item.images) {
        const holder = el('div', '正在加载原文…', 'learning-image-holder'); images.append(holder);
        const load = async () => {
          const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
          if (!response.ok) throw new Error('原文读取失败，请重试');
          const blob = await response.blob();
          if (state.token !== token || !node.isConnected) return;
          const url = URL.createObjectURL(blob); urls.add(url);
          const img = el('img'); img.src = url; img.alt = '本题参考答案原文'; img.loading = 'lazy';
          const zoom = button('放大查看原文', () => {
            const view = learningDialog('参考答案原文'); view.dialog.classList.add('learning-image-dialog');
            const full = el('img'); full.src = url; full.alt = img.alt; view.body.append(full);
          }, 'button quiet');
          holder.replaceChildren(img, zoom);
        };
        try { await load(); }
        catch (error) { if (holder.isConnected) holder.replaceChildren(button('原文加载失败，点击重试', load)); }
      }
    });
    node.append(details);
  }
  if (item.source_info?.kind === 'supplement') node.append(el('p', '补充题 · 围绕本篇知识体系整理，非 PDF 原题。', 'learning-source-note'));
  if (item.source_info?.kind === 'curated') node.append(el('p', '整理校订题 · 题干与参考答案已重新组织，原文仅作为主题来源。', 'learning-source-note'));
  if (item.source_info?.origins?.length || item.source_info?.file) {
    const sources = item.source_info.origins || [item.source_info];
    for (const source of sources) {
      node.append(el('p', `来源：${source.file}${source.page_start ? ` · 第 ${source.page_start}${source.page_end !== source.page_start ? `–${source.page_end}` : ''} 页` : ''}`, 'learning-source-note'));
    }
  }
  if (item.source_info?.references?.length) {
    const refs = el('details', '', 'learning-source-images'); refs.append(el('summary', '延伸阅读与校订参考'));
    for (const url of item.source_info.references) {
      let parsed; try { parsed = new URL(url); } catch (error) { continue; }
      if (parsed.protocol !== 'https:') continue;
      const link = el('a', parsed.hostname); link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
      const p = el('p'); p.append(link); refs.append(p);
    }
    node.append(refs);
  }
  return node;
}
export function questionPreview(item) {
  const { body } = learningDialog(item.collection_name || '题目预览');
  body.append(passageContext(item), el('p', item.question, `learning-question ${item.category === 'professional' ? '' : 'english'}`));
  if (item.category !== 'oral') body.append(referenceAnswer(item));
}
export function downloadTemplate() {
  const data = [{ collection_id: 'data_structures', question: '栈与队列有什么区别？', answer: '栈后进先出，队列先进先出。' },
    { collection_id: 'translation', question: 'A process is a program in execution.', answer: '进程是正在执行的程序。' },
    { collection_id: 'ai_literature_translation', question: 'Retrieval-augmented generation combines language models with external knowledge.', answer: '检索增强生成将语言模型与外部知识结合。' },
    { collection_id: 'oral', question: 'Why do you want to study at Sichuan University?', answer: '' }];
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = el('a'); a.href = url; a.download = '训练题导入模板.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function importDialog(done) {
  const { dialog, body, footer } = learningDialog('批量导入私人题目');
  body.append(el('p', '上传 JSON 列表，预览确认后统一保存，默认仅自己可见。专业课集合还支持 operating_systems、computer_networks。', 'muted'));
  body.append(button('下载 JSON 模板', downloadTemplate));
  const file = el('input'); file.type = 'file'; file.accept = '.json,application/json'; file.setAttribute('aria-label', '选择 JSON 题目文件');
  const preview = el('div', '', 'learning-import-preview');
  const save = button('确认导入', async () => {
    const result = await api('/training/import', { method: 'POST', body: JSON.stringify({ items }) });
    if (dialog.isConnected) { dialog.close(); notify(`已保存 ${result.created} 道私人题目`); await done(); }
  }, 'button primary'); save.disabled = true;
  let items = []; let generation = 0;
  file.addEventListener('change', async () => {
    const selected = file.files[0]; items = []; save.disabled = true;
    const request = ++generation; if (!selected) return;
    preview.replaceChildren(el('p', '正在检查文件…'));
    try {
      const form = new FormData(); form.append('file', selected);
      const result = await api('/training/import/preview', { method: 'POST', body: form });
      if (!dialog.isConnected || request !== generation) return;
      preview.replaceChildren(el('p', `识别到 ${result.count} 道有效题目${result.errors.length ? `，${result.errors.length} 条错误` : ''}`));
      for (const error of result.errors) preview.append(el('p', error, 'form-error'));
      for (const item of result.items) preview.append(el('p', `[${item.collection_id}] ${item.question}`, 'learning-import-item'));
      items = result.items; save.disabled = !items.length || Boolean(result.errors.length);
    } catch (error) { if (dialog.isConnected && request === generation) preview.replaceChildren(el('p', error.message, 'form-error')); }
  });
  body.append(file, preview); footer.append(button('取消', () => dialog.close()), save);
}
