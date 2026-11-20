/** Daily practice cards, sequential review, favorites and private contributions. */
import { api, state } from './api.js?v=20261114-ui-v17';
import { $, el, button, notify, confirmAction, badge } from './ui.js?v=20261114-ui-v17';
import { selectField, pagination, questionEditor, referenceAnswer, passageContext, questionPreview, importDialog, clearLearningMedia } from './training-ui.js?v=20261114-ui-v18';
let generation = 0, homeData = null, session = null;
let listRequest = 0;
let section = 'interview';
let sectionRequest = 0;
let collection = '', source = 'all', mode = 'random', tab = 'home', page = 1, search = '';
let questionCount = null, countMode = 'custom';
function live(key, token) { return key === generation && token === state.token && !$('training').hidden; }
export function clearTraining() {
  generation++; session = null; homeData = null; clearLearningMedia();
  $('trainingContent')?.replaceChildren();
}
async function loadHome() {
  const key = generation, token = state.token, selectedSection = section;
  const value = await api(`/training/home?section_id=${selectedSection}`);
  if (!live(key, token) || selectedSection !== section) return false;
  homeData = value;
  if (collection && !value.collections.some(c => c.id === collection)) collection='';
  return true;
}
export async function refreshTraining() {
  const key = ++generation, token = state.token;
  $('trainingContent').replaceChildren(el('div', '正在加载今日训练…', 'learning-loading'));
  const value = await api(`/training/home?section_id=${section}`);
  if (!live(key, token)) return;
  homeData = value; session = null;
  if (collection && !value.collections.some(c => c.id === collection)) collection='';
  render();
  if (tab !== 'home') await list();
}

export function selectTrainingSection(value) {
  if (['interview','written_c','written_ai'].includes(value)) section = value;
}
function render() {
  listRequest++;
  clearLearningMedia();
  const root = $('trainingContent'); root.replaceChildren();
  const head = el('div', '', 'page-heading');
  const title = el('div'); title.append(el('span', 'A LITTLE EVERY DAY', 'eyebrow'), el('h1', '每日训练'), el('p', '把大目标，拆成每天的一小步。', 'muted'));
  head.append(title, button('新增题目', () => editQuestion(), 'button secondary'));
  root.append(head);
  const chapters = el('div', '', 'learning-chapters'); chapters.setAttribute('aria-label', '训练篇章');
  for (const item of homeData.sections) {
    const control = button('', async () => {
      const request = ++sectionRequest;
      section = item.id; collection = ''; page = 1; session = null; search = '';
      if (await loadHome() && request === sectionRequest) { render(); if (tab !== 'home') await list(); }
    }, `learning-chapter ${section === item.id ? 'selected' : ''}`);
    control.setAttribute('aria-pressed', String(section === item.id));
    control.append(el('strong', item.name), el('span', item.count ? `${item.count} 道可练题目` : '等待你来补充'));
    chapters.append(control);
  }
  if (!session) root.append(chapters);
  const tabs = el('div', '', 'learning-tabs');
  for (const [value, label] of [['home','今日练习'],['favorites','重点回顾'],['mine','我的题目']]) {
    const control = button(label, async () => {
      tab = value; page = 1; session = null;
      if (tab === 'home') { if (await loadHome()) render(); }
      else { render(); await list(); }
    }, `button ${tab === value ? 'primary' : 'quiet'}`);
    control.setAttribute('aria-pressed', String(tab === value)); tabs.append(control);
  }
  root.append(tabs);
  if (session) renderSession(root);
  else if (tab === 'home') renderHome(root);
  else renderListShell(root);
}
function checkinControl() {
  const control = button(homeData.checked_in ? '今日已打卡 ✓' : homeData.completed >= homeData.goal ? '完成今日打卡' : `再练 ${homeData.goal-homeData.completed} 题可打卡`, async () => {
    const key = generation, token = state.token;
    const result = await api('/training/checkin', { method: 'POST', body: '{}' });
    if (!live(key, token)) return;
    homeData = result.home;
    if (!await loadHome()) return;
    notify(result.already_checked ? '今天已经打卡过了' : result.credits ? `打卡成功，获得 ${result.credits} 次模拟面试机会` : `打卡成功，已连续坚持 ${homeData.streak} 天`);
    render();
  }, 'button primary');
  control.disabled = homeData.checked_in || homeData.completed < homeData.goal;
  return control;
}
function renderHome(root) {
  const overview = el('div', '', 'learning-overview');
  const goal = el('div', '', 'learning-goal');
  goal.append(el('span', 'TODAY', 'eyebrow'), el('h2', homeData.checked_in ? '今天的坚持，已记录。' : '今天，也向前一点。'));
  const count = el('p', '', 'learning-goal-number'); count.append(el('strong', String(homeData.completed)), el('span', ` / ${homeData.goal} 道`));
  goal.append(count, el('p', '每天完成不同题目，达成目标后签到。', 'muted'));
  const track = el('div', '', 'learning-progress'); const fill = el('span'); fill.style.width = `${Math.min(100,homeData.completed/homeData.goal*100)}%`; track.append(fill);
  goal.append(track, checkinControl());
  const streak = el('div', '', 'learning-streak');
  streak.append(el('span', 'STEADY PROGRESS', 'eyebrow'), el('h2', `连续 ${homeData.streak} 天`));
  const days = el('div', '', 'learning-week');
  for (const day of homeData.recent_days) {
    const item = el('div', '', day.checked_in ? 'checked' : '');
    item.title = day.date; item.append(el('span', day.date.slice(5).replace('-', '/')), el('b', day.checked_in ? '✓' : '·')); days.append(item);
  }
  streak.append(days, el('p', homeData.is_admin ? '持续练习，让表达更从容。管理员无需领取面试次数。' : `下个节点：连续 ${homeData.next_milestone} 天，再得 ${homeData.next_reward} 次面试机会。`, 'muted'));
  const rule = el('details', '', 'learning-rules'); rule.append(el('summary', '查看打卡奖励规则'), el('p', '第 7 天新增 1 次，第 14 天再新增 2 次，第 21 天再新增 3 次，依此递增。断签后从第 1 天重新累计，已获次数保留。以北京时间的自然日为准，同题当日仅计一次。'));
  streak.append(rule); overview.append(goal, streak); root.append(overview);
  if (homeData.active_session) {
    const active = homeData.active_session;
    const banner = el('div', '', 'learning-resume');
    banner.append(el('div', `${homeData.sections.find(s => s.id === active.section_id)?.name || '面试篇'} · 上次练习已完成 ${active.completed}/${active.total} 题`));
    banner.append(button('继续练习', () => resume(active.id), 'button primary'), button('结束这一轮', async () => {
      if (!await confirmAction('已完成题目会保留，尚未完成的题目不会计入今日目标。', { title: '结束本轮训练', confirmText: '结束本轮' })) return;
      await api(`/training/sessions/${active.id}/end`, { method: 'POST', body: '{}' });
      if (await loadHome()) render();
    })); root.append(banner);
  }
  const setup = el('section', '', 'learning-setup'); setup.append(el('h2', '选择今天的练习'));
  const scoped = homeData.collections.filter(c => c.section_id === section);
  const categories = el('div', '', 'learning-categories');
  categories.classList.toggle('learning-categories-ai', section === 'written_ai');
  for (const [index, item] of scoped.entries()) {
    const control = button('', () => { collection = item.id; render(); }, 'learning-category');
    control.dataset.collection = item.id;
    control.classList.toggle('selected', collection === item.id); control.setAttribute('aria-pressed', String(collection === item.id));
    control.append(el('span', String(index + 1).padStart(2, '0'), 'learning-category-number'), el('h3', item.name),
      el('small', `${item.count} 道可练题目`)); categories.append(control);
  }
  if (!scoped.some(c => c.count)) setup.append(el('p', '本篇暂无公开题目。你可以新增私人题目进行训练，提交并通过审核后与大家分享。', 'learning-empty-chapter'));
  setup.append(el('p', `${homeData.sections.find(s => s.id === section)?.name || ''} · 本轮仅从当前篇章抽题。`, 'muted'));
  setup.append(categories);
  const form = el('form'); form.className = 'learning-setup-form';
  const filters = el('div', '', 'learning-filters');
  const c = selectField('题目集合', [['','全部集合'], ...scoped.map(c => [c.id, `${c.name} · ${c.count} 题`])], collection);
  const s = selectField('训练来源', [['all','全部可练题'],['favorites','仅重点回顾']], source);
  const m = selectField('复习方式', [['random','随机训练'],['sequential','按顺序复习']], mode);
  const roundOptions = el('div', '', 'learning-round-options');
  const amountMode = selectField('本次训练题量', [['custom','指定题目数量'],['all','整个筛选集合']], countMode);
  const amountWrap = el('div', '', 'learning-field');
  const amountLabel = el('label', '题目数量'); amountLabel.htmlFor = 'trainingQuestionCount';
  const amount = el('input'); amount.id = amountLabel.htmlFor; amount.type = 'number'; amount.min = '1';
  amount.max = String(homeData.max_round_questions); amount.step = '1'; amount.required = true;
  amount.value = String(questionCount ?? homeData.default_round_size);
  amount.addEventListener('input', () => { questionCount = amount.value; updateCount(); });
  amountWrap.append(amountLabel,amount);
  const countHint = el('p', '', 'learning-round-hint'); countHint.id = 'trainingCountHint';
  countHint.setAttribute('aria-live', 'polite'); amount.setAttribute('aria-describedby', countHint.id);
  const updateCount = () => {
    const candidates = scoped.filter(item => !collection || item.id === collection);
    const count = candidates.reduce((n,item) => n + (source === 'favorites' ? item.favorites : item.count),0);
    const whole = countMode === 'all'; amount.disabled = whole; amountWrap.hidden = whole;
    begin.disabled = Boolean(homeData.active_session) || count === 0;
    countHint.textContent = `当前筛选共 ${count} 道可练题。${whole ? '本轮练完整个筛选集合，每题一次。' : '题量不足时只安排现有题目；顺序复习到集合末尾时结束本轮。'}`;
  };
  amountMode.input.addEventListener('change', () => { countMode = amountMode.input.value; updateCount(); });
  c.input.addEventListener('change', () => {
    collection = c.input.value;
    for (const tile of categories.children) { const active=tile.dataset.collection===collection;tile.classList.toggle('selected',active);tile.setAttribute('aria-pressed',String(active)); }
    updateCount();
  });
  s.input.addEventListener('change', () => { source = s.input.value; updateCount(); });
  m.input.addEventListener('change', () => { mode = m.input.value; });
  const begin = button('开始训练 →', async () => {
    if (!form.reportValidity()) return;
    const key = generation, token = state.token;
    const value = await api('/training/sessions', { method: 'POST', body: JSON.stringify({ section_id: section, collection_id: collection, source, mode,
      question_count: countMode === 'all' ? 'all' : Number(amount.value) }) });
    if (!live(key, token)) return; session = value; render(); $('trainingContent').scrollIntoView({ behavior: 'smooth' });
  }, 'button primary'); begin.disabled = Boolean(homeData.active_session);
  filters.append(c.wrap, s.wrap, m.wrap);
  roundOptions.append(amountMode.wrap, amountWrap, begin); updateCount();
  form.append(filters,roundOptions,countHint);
  form.addEventListener('submit', event => { event.preventDefault(); if (!begin.disabled) begin.click(); });
  setup.append(form);
  setup.append(el('p', '全部可练题默认包含公开题和你自己的私人题。随机训练优先巩固“还需练习”的题目，一轮内不重复；顺序复习会记住完成位置。', 'muted'));
  setup.append(el('p', `个人掌握记录 · 还需巩固 ${homeData.mastery.again} 题 · 已掌握 ${homeData.mastery.known} 题`, 'learning-mastery-summary'));
  root.append(setup);
  if (homeData.rewards.length) {
    const history = el('details', '', 'learning-reward-history'); history.append(el('summary', '我的打卡奖励'));
    for (const reward of homeData.rewards) history.append(el('p', `${reward.date} · 连续 ${reward.streak} 天 · +${reward.credits} 次模拟面试`));
    root.append(history);
  }
}
async function resume(id) {
  const key = generation, token = state.token;
  const value = await api(`/training/sessions/${id}`);
  if (live(key, token)) { session = value; section = value.section_id; collection = value.collection_id; tab = 'home'; render(); }
}
function renderSession(root) {
  const panel = el('section', '', 'learning-study');
  const top = el('div', '', 'learning-study-top');
  top.append(button('← 返回今日练习', async () => { session = null; if (await loadHome()) render(); }, 'button quiet'), el('span', session.mode === 'sequential' ? '按顺序复习' : '随机训练', 'muted'));
  panel.append(top);
  if (session.status !== 'active') {
    panel.classList.add('learning-complete');
    panel.append(el('span', '✓', 'learning-complete-icon'), el('h2', '这一轮，完成了。'), el('p', `已完成 ${session.completed} 道卡片。继续练习，或回到今日目标完成打卡。`, 'muted'));
    panel.append(button('查看今日进度', async () => { session = null; if (await loadHome()) render(); }, 'button primary'));
    root.append(panel); return;
  }
  const card = session.cards.find(c => !c.completed);
  const bar = el('div', '', 'learning-progress'); const fill = el('span'); fill.style.width = `${session.completed/session.total*100}%`; bar.append(fill);
  const meta = el('div', '', 'learning-card-meta'); meta.append(badge(card.collection_name), el('span', `${session.completed + 1} / ${session.total}`));
  if (card.available) meta.firstChild.append(el('span', card.mastery.status === 'again' ? ' · 还需巩固' : card.mastery.status === 'known' ? ' · 已掌握' : ' · 未自评'));
  panel.append(bar, meta);
  if (card.category === 'translation') panel.classList.add('learning-translation');
  const question = el('h2', card.question, `learning-question ${card.category === 'professional' ? '' : 'english'}`); question.tabIndex = -1;
  panel.append(passageContext(card), question);
  const actions = el('div', '', 'learning-card-actions');
  const favorite = button(card.favorite ? '★ 已加入重点回顾' : '☆ 加入重点回顾', async () => {
    const value = await api(`/training/questions/${card.question_id}/favorite`, { method: 'PUT', body: JSON.stringify({ favorite: !card.favorite }) });
    if (!panel.isConnected) return; card.favorite = value.favorite; favorite.textContent = value.favorite ? '★ 已加入重点回顾' : '☆ 加入重点回顾'; favorite.setAttribute('aria-pressed', String(value.favorite));
  }, 'button quiet'); favorite.disabled = !card.available; favorite.setAttribute('aria-pressed', String(card.favorite)); actions.append(favorite); panel.append(actions);
  let saving = false;
  const complete = async rating => {
    if (saving) return; saving = true;
    try {
    const key = generation, token = state.token;
    const value = await api(`/training/sessions/${session.id}/cards/${card.id}/complete`, { method: 'POST', body: JSON.stringify({ rating }) });
    if (!live(key, token)) return;
    session = value; render();
    $('trainingContent').querySelector('.learning-study')?.scrollIntoView({ block:'start', behavior:'instant' });
    $('trainingContent').querySelector('.learning-question')?.focus({ preventScroll: true });
    } finally { saving = false; }
  };
  const footer = el('div', '', 'learning-study-footer');
  if (!card.available) footer.append(button('跳过不可用题目', () => complete('done'), 'button primary'));
  else if (card.category === 'oral') {
    panel.append(el('p', '试着用英文完整回答，无需录音。此类题目不提供示例答案。', 'learning-study-hint'));
    footer.append(button('完成本题，下一题 →', () => complete('done'), 'button primary'));
  } else {
    const reveal = button(card.category === 'translation' ? '查看参考译文' : '查看参考答案', () => {
      reveal.remove(); panel.insertBefore(referenceAnswer(card), footer);
      footer.replaceChildren(button('还需练习，下一题 →', () => complete('again')), button('已掌握，下一题 →', () => complete('known'), 'button primary'));
      const explanation = el('p', '自评会保存：还需练习的题在下轮随机训练中更容易抽中，已掌握后降低权重。', 'learning-rating-hint');
      panel.insertBefore(explanation,footer);
    }, 'button primary');
    panel.append(el('p', card.category === 'translation' ? '先独立翻译，再对照参考译文。留意术语与逻辑关系。' : '先回忆，再对照。不必着急翻看答案。', 'learning-study-hint'));
    footer.append(reveal);
  }
  panel.append(footer); root.append(panel);
}
function renderListShell(root) {
  const heading = el('div', '', 'learning-list-heading');
  heading.append(el('p', tab === 'mine' ? '你的补充题目默认仅自己可见，审核通过后才公开。' : '把想再想一遍的题，留在这里。', 'muted'));
  if (tab === 'mine') heading.append(button('批量导入 JSON', () => importDialog(async () => { await loadHome(); await list(); })));
  else heading.append(button('训练重点回顾', () => { source='favorites';collection='';tab='home';render(); }, 'button primary'));
  const input = el('input'); input.type = 'search'; input.value = search; input.placeholder = '搜索题目后按回车'; input.setAttribute('aria-label', '搜索题目');
  const searchForm = el('form', '', 'learning-search'); searchForm.append(input, button('搜索', async () => { search=input.value.trim();page=1;await list(); }));
  searchForm.addEventListener('submit', e => { e.preventDefault(); searchForm.querySelector('button').click(); });
  root.append(heading, searchForm, el('div', '', 'learning-list')); root.querySelector('.learning-list').id = 'learningList';
}
async function list() {
  if ($('training').hidden || tab === 'home') return;
  const request = ++listRequest;
  const key = generation, token = state.token, selected = tab;
  const params = new URLSearchParams({ section_id: section, page, q: search, mine: tab === 'mine', favorites: tab === 'favorites' });
  const result = await api(`/training/questions?${params}`);
  if (!live(key, token) || selected !== tab || request !== listRequest) return;
  const root = $('learningList'); if (!root) return; root.replaceChildren();
  if (!result.items.length) {
    root.append(el('div', tab === 'favorites' ? '还没有重点回顾题目。练习时点击 ☆，即可加入。' : '暂时没有匹配的私人题目。可以新增一道，或批量导入。', 'empty-state'));
    return;
  }
  for (const item of result.items) {
    const row = el('article', '', 'learning-list-item'); const info = el('div');
    info.append(badge(item.collection_name), button(item.question, () => questionPreview(item), `learning-question-link ${item.category === 'translation' ? 'learning-passage-link' : ''}`));
    if (item.category === 'translation') info.append(el('p', '点击原文查看完整内容与参考译文', 'muted'));
    if (item.mastery.status !== 'unseen') info.append(el('p', item.mastery.status === 'again' ? '还需巩固 · 随机抽题优先复习' : '已掌握 · 降低随机抽题权重', 'learning-mastery-label'));
    const controls = el('div', '', 'learning-list-actions');
    if (tab === 'mine') {
      const labels = { draft:'仅自己可见',pending:'待审核',approved:'已公开',rejected:'未通过' };
      info.append(el('p', labels[item.review_status], 'muted'));
      if (item.review_reason) info.append(el('p', `审核意见：${item.review_reason}`, 'learning-review-reason'));
      controls.append(button('编辑', () => editQuestion(item)), button('删除', async () => {
        if (!await confirmAction('删除后不再参与训练，已完成的题数会保留。', { title:'删除题目', confirmText:'删除', danger:true })) return;
        await api(`/training/questions/${item.id}`, { method:'DELETE' }); await list();
      }, 'button quiet'));
      if (item.review_status === 'pending') controls.append(button('撤回审核', async () => { await api(`/training/questions/${item.id}/withdraw`, { method:'POST', body:JSON.stringify({ version:item.version }) }); await list(); }));
      else if (item.visibility !== 'public') controls.append(button('提交公开审核', async () => {
        await api(`/training/questions/${item.id}/submit`, { method:'POST', body:JSON.stringify({ version:item.version }) }); notify('已提交审核，通过前仍仅自己可见'); await list();
      }));
    } else controls.append(button('移出重点回顾', async () => { await api(`/training/questions/${item.id}/favorite`, { method:'PUT',body:JSON.stringify({ favorite:false }) }); await list(); }));
    row.append(info, controls); root.append(row);
  }
  pagination(root,result,async value => { page=value; await list(); });
}
async function editQuestion(item=null) {
  if (item?.visibility === 'public' && !await confirmAction('保存修改后此题将暂时转为私人，重新审核通过后才会公开。', { title:'编辑公开题目', confirmText:'继续编辑' })) return;
  if (!homeData) return;
  questionEditor(homeData.collections,item,async data => {
    const token=state.token,key=generation;
    await api(item ? `/training/questions/${item.id}` : '/training/questions', { method:item ? 'PATCH':'POST',body:JSON.stringify({ ...data,...(item ? { version:item.version } : {}) }) });
    if (!live(key,token)) return;
    section = homeData.collections.find(c => c.id === data.collection_id)?.section_id || section;
    if (!await loadHome()) return;
    notify('题目已保存，默认参与自己的训练，仅自己可见'); tab='mine';page=1;render();await list();
  }, false, section, collection);
}
