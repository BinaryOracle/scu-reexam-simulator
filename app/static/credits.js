/** Interview balances and voucher administration have no external shop API. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, emptyState, notify, run, dateTime, badge, confirmAction } from "./ui.js?v=20261114-ui-v17";
import { refreshAccountSettings, setupAccountSettings } from "./profile-account.js?v=20261116-ui-audit-v2";

import { refreshTransfers } from "./credit-transfers.js?v=20261117-points-v1";

let voucherPackage = "";
let voucherPage = 1;
let voucherRequest = 0;
let voucherSearchTimer;
let defaultCreditsDirty = false;
let pointsSettingsDirty = false;
let packageOptions = [];
let profilePoints = 0;
let unitPointsCost = 1;
let purchaseRequestKey = null;
let purchaseQuantity = null;
let purchaseToken = null;
let purchaseBusy = false;
let profileRequest = 0;
let referralRequest = 0;
const money = value => `¥${(value / 100).toFixed(2)}`;
const download = (text, name) => {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = el("a"); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

export async function readCreditSettings() {
  return api("/admin/credit-settings");
}

function voucherLoading() {
  for (const id of ["voucherTotal", "voucherUnused", "voucherRedeemed", "voucherPageLabel"]) $(id).textContent = "—";
  $("voucherPrevious").disabled = true; $("voucherNext").disabled = true;
  $("voucherList").setAttribute("aria-busy", "true");
  $("voucherList").replaceChildren(el("p", "正在加载卡密…", "muted"));
}

export async function refreshVouchers() {
  clearTimeout(voucherSearchTimer);
  const request = ++voucherRequest;
  voucherLoading();
  try {
  const settings = await readCreditSettings();
  if (request !== voucherRequest) return;
  packageOptions = settings.packages;
  if (!packageOptions.some(item => item.id === voucherPackage)) voucherPackage = packageOptions[0]?.id || "";
  $("deleteVoucherPackage").disabled = !settings.packages.some(item => item.id === voucherPackage);
  $("exportVouchers").disabled = !voucherPackage;
  if (!pointsSettingsDirty) $("interviewPointsCost").value = settings.interview_points_cost;
  const rewardForm = $("pointsRewardRulesForm");
  for (const key of ['invite_signup_points', 'training_checkin_points_per_week', 'coding_checkin_points_per_week', 'training_questions_per_reward', 'training_contribution_points', 'coding_questions_per_reward', 'coding_contribution_points'])
    rewardForm.elements.namedItem(key).value = settings.reward_rules[key];
  settings.reward_rules.leaderboard_rewards.forEach((value, index) => { rewardForm.elements.namedItem(`leaderboard_${index + 1}`).value = value; });
  const selected = $("voucherGeneratePackage").value;
  $("voucherGeneratePackage").replaceChildren(...settings.packages.map(item => {
    const option = el("option", `${money(item.price_fen)} / ${item.credits} 积分`); option.value = item.id; return option;
  }));
  $("voucherGeneratePackage").value = settings.packages.some(item => item.id === selected) ? selected : settings.packages[0]?.id || "";
  $("voucherGenerateForm").querySelector('[type="submit"]').disabled = !settings.packages.length;
  $("voucherPackageTabs").replaceChildren(...packageOptions.map(item => {
    const control = button(`${money(item.price_fen)} / ${item.credits} 积分`, () => {
      voucherPackage = item.id; voucherPage = 1; $("voucherBatch").value = "";
      return refreshVouchers();
    }, item.id === voucherPackage ? "selected" : "");
    control.dataset.voucherPackage = item.id;
    control.setAttribute("aria-pressed", String(item.id === voucherPackage));
    return control;
  }));
  const query = new URLSearchParams({ status: $("voucherStatus").value,
    q: $("voucherSearch").value.trim(), batch: $("voucherBatch").value.trim(), page: voucherPage });
  if (voucherPackage) query.set("package", voucherPackage);
  const data = await api(`/admin/vouchers?${query}`);
  if (request !== voucherRequest) return;
  $("voucherList").removeAttribute("aria-busy");
  if (!defaultCreditsDirty) $("defaultCredits").value = settings.default_credits;
  $("voucherCount").max = settings.max_voucher_batch;
  $("voucherMaxHint").textContent = `每批最多 ${settings.max_voucher_batch} 张；每张卡密只能兑换一次。`;
  $("voucherTotal").textContent = data.total;
  $("voucherUnused").textContent = data.unused;
  $("voucherRedeemed").textContent = data.redeemed;
  $("voucherPageLabel").textContent = `${voucherPage} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
  $("voucherPrevious").disabled = voucherPage <= 1;
  $("voucherNext").disabled = voucherPage * data.page_size >= data.total;
  if (!data.items.length) {
    $("voucherList").replaceChildren(emptyState("暂无匹配的卡密", "切换套餐或筛选条件，也可以生成一批新卡密。", "◇"));
    return;
  }
  const wrap = el("div", "", "table-scroll");
  const table = el("table", "", "voucher-table");
  const mobileList = el("div", "", "voucher-mobile-list");
  const head = el("thead"); const titles = el("tr");
  for (const title of ["卡密", "批次", "积分 / 标价", "兑换状态", "兑换用户", "兑换时间"]) {
    const cell = el("th", title); cell.scope = "col"; titles.append(cell);
  }
  head.append(titles);
  const body = el("tbody");
  for (const item of data.items) {
    const row = el("tr");
    const code = el("td");
    const makeCopyButton = () => {
      const copy = button(item.code, async () => {
        await navigator.clipboard.writeText(item.code);
        notify("卡密已复制。");
      }, "voucher-code");
      copy.title = "复制此卡密";
      return copy;
    };
    code.append(makeCopyButton());
    const batch = el("td");
    const makeBatchButton = () => {
      const batchButton = button(item.batch.slice(0, 8), () => {
        $("voucherBatch").value = item.batch; voucherPage = 1; return refreshVouchers();
      }, "text-button mono");
      batchButton.title = `筛选批次 ${item.batch} · 生成于 ${dateTime(item.created)}`;
      return batchButton;
    };
    batch.append(makeBatchButton());
    const redeemed = Boolean(item.redeemed_at);
    const status = el("td"); status.append(badge(redeemed ? "已兑换" : "未兑换", redeemed ? "green" : "orange"));
    row.append(code, batch, el("td", `${item.credits} 积分 / ${money(item.price_fen)}`), status,
      el("td", item.redeemed_by || "—"), el("td", item.redeemed_at ? dateTime(item.redeemed_at) : "—"));
    body.append(row);

    const card = el("article", "", "voucher-mobile-card");
    const cardHeading = el("div", "", "voucher-mobile-heading");
    const cardCode = el("div", "", "voucher-mobile-code");
    cardCode.append(el("span", "卡密"), makeCopyButton());
    cardHeading.append(cardCode, badge(redeemed ? "已兑换" : "未兑换", redeemed ? "green" : "orange"));
    const details = el("dl", "", "voucher-mobile-details");
    const addField = (label, value) => {
      const field = el("div", "", "voucher-mobile-field");
      field.append(el("dt", label), el("dd", value));
      details.append(field);
      return field.querySelector("dd");
    };
    addField("批次", "").append(makeBatchButton());
    addField("套餐", `${item.credits} 积分 / ${money(item.price_fen)}`);
    addField("兑换用户", item.redeemed_by || "—");
    addField("兑换时间", item.redeemed_at ? dateTime(item.redeemed_at) : "—");
    card.append(cardHeading, details);
    mobileList.append(card);
  }
  table.append(head, body); wrap.append(table);
  const results = el("div", "", "voucher-results");
  results.append(wrap, mobileList);
  $("voucherList").replaceChildren(results);
  } catch (error) {
    if (request !== voucherRequest) return;
    $("voucherList").removeAttribute("aria-busy");
    const message = emptyState("卡密加载失败", "请检查网络连接后重试。", "◇");
    message.append(button("重新加载", refreshVouchers));
    $("voucherList").replaceChildren(message);
    throw error;
  }
}

export async function refreshProfile() {
  const request = ++profileRequest, token = state.token;
  const data = await api("/profile");
  if (request !== profileRequest || token !== state.token || !state.user) return;
  state.user.interview_credits = data.remaining;
  state.user.points = data.points;
  profilePoints = data.points;
  unitPointsCost = data.interview_points_cost;
  $("profilePoints").textContent = `${data.points.toLocaleString("zh-CN")} 积分`;
  $("profilePointsStat").hidden = data.is_admin;
  $("profileShopSection").hidden = data.is_admin;
  $("profilePointsHistorySection").hidden = data.is_admin;
  $("pointsProductPrice").textContent = `${unitPointsCost} 积分 / 次`;
  updatePurchaseTotal();
  renderPointsHistory(data.points_history);
  $("profileUsername").textContent = data.username;
  refreshAccountSettings();
  $("profileLoginEmail").hidden = !state.user.email;
  $("profileLoginEmail").textContent = state.user.email ? `登录邮箱：${state.user.email}` : "";
  $("profileAllowanceLabel").textContent = data.is_admin ? "模拟面试" : "剩余模拟面试次数";
  $("profileRemaining").textContent = data.is_admin ? "已开通" : `${data.remaining} 次`;
  $("profileAllowanceHint").textContent = data.is_admin ? "随时开始你的下一场练习" : "正式开始一场面试消耗 1 次";
  $("profileAmount").textContent = money(data.redeemed_amount_fen);
  $("profileRedeemCount").textContent = `${data.redemptions.length} 张`;
  const shop = $("voucherShopLink");
  const voucherSection = $("profileVoucherSection");
  const redemptionStats = $("profileRedemptionStats");
  const redemptionCount = $("profileRedemptionStatsCount");
  const redemptionHistory = $("profileRedemptionHistorySection");
  const contributionRoot = $("profileContribution");
  voucherSection.hidden = Boolean(data.is_admin);
  redemptionStats.hidden = Boolean(data.is_admin);
  redemptionCount.hidden = Boolean(data.is_admin);
  redemptionHistory.hidden = Boolean(data.is_admin);
  shop.hidden = !data.shop_url || Boolean(data.is_admin);
  if (data.shop_url) shop.href = data.shop_url;
  else shop.removeAttribute("href");
  if (!data.redemptions.length) {
    $("redemptionHistory").replaceChildren(emptyState("暂无兑换记录", "兑换成功后，获得的积分和对应套餐金额会显示在这里。", "◇"));
  } else {
    const list = el("div", "", "redemption-list");
    for (const record of data.redemptions) {
      const row = el("article", "", "redemption-record");
      const copy = el("div");
      copy.append(el("strong", `新增 ${record.points} 积分`), el("p", `卡密尾号 ${record.code_suffix} · ${dateTime(record.redeemed_at)}`));
      row.append(copy, el("span", money(record.amount_fen), "redemption-price"));
      list.append(row);
    }
    $("redemptionHistory").replaceChildren(list);
  }
  try { await refreshTransfers(data, refreshProfile); }
  catch {
    if (request !== profileRequest || token !== state.token) return;
    const message = emptyState("转赠记录暂时无法加载", "余额和兑换信息已更新；请稍后重试查看转赠记录。", "◇");
    message.append(button("重新加载", () => { void refreshProfile(); }, "button secondary"));
    $("profileTransfers").replaceChildren(message);
  }
  try {
    const contribution = await api("/training/contribution-rewards");
    if (request !== profileRequest || token !== state.token) return;
    contributionRoot.replaceChildren();
    const contributionHeading = el("div", "", "contribution-heading");
    contributionHeading.append(el("div", "题库贡献奖励", "eyebrow"),
      el("h2", contribution.exempt ? "管理员账号不参与奖励" : "分享题目，获得积分"));
    const contributionProgress = el("p", contribution.exempt
      ? "普通用户投稿审核通过并公开后计入奖励。"
      : "当前规则：每 " + contribution.policy.questions_per_reward + " 道公开题奖励 " +
        contribution.policy.credits_per_reward + " 积分；本规则下已通过 " + contribution.approved_count +
        " 道，再通过 " + contribution.remaining_questions + " 道可达下一奖励。", "muted");
    contributionRoot.append(contributionHeading, contributionProgress);
    if (!contribution.exempt) {
      const history = el("div", "", "contribution-history");
      for (const grant of contribution.grants.slice(0, 5))
        history.append(el("span", "+" + grant.credits + " 积分 · " + new Date(grant.created * 1000).toLocaleDateString("zh-CN")));
      if (!contribution.grants.length) history.append(el("span", "审核通过的投稿达到规则数量后，会在这里显示奖励记录。"));
      contributionRoot.append(history);
    }
  } catch {
    if (request !== profileRequest || token !== state.token) return;
    const message = emptyState("贡献奖励信息暂时无法加载", "账户余额与兑换记录仍可正常查看。", "◇");
    message.append(button("重新加载", () => { void refreshProfile(); }, "button secondary"));
    contributionRoot.replaceChildren(message);
  }
}

async function renderReferrals(request, token) {
  const root = $("referralContent");
  const data = await api('/profile/referrals');
  if (request !== referralRequest || token !== state.token) return;
  const pending = data.items.filter(item => item.purchase_service && !item.rebate_redeemed).length;
  const redeemed = data.items.filter(item => item.purchase_service && item.rebate_redeemed).length;
  const stats = $('referralStats');
  const stat = (label, value, hint, tone = '') => {
    const card = el('article', '', `panel referral-stat${tone ? ` ${tone}` : ''}`);
    card.append(el('span', label), el('strong', value), el('small', hint));
    return card;
  };
  stats.replaceChildren(
    stat('注册奖励', `${data.signup_reward_points} 积分`, '每位新用户首次注册成功'),
    stat('邀请人数', String(data.total_invited), '已通过邀请码建立关系'),
    stat('待兑现服务', String(pending), '套餐或项目服务返利', 'pending'),
    stat('已兑现服务', String(redeemed), '管理员确认完成兑现', 'settled'),
  );
  const title = el('div', '', 'referral-content-heading');
  title.append(el('div', 'YOUR REFERRAL', 'eyebrow'), el('h2', '分享邀请，查看返利'));
  const intro = el('p', `新用户首次注册并填写邀请码后，你将获得 ${data.signup_reward_points} 积分。`);
  const details = el('div', '', 'referral-policy');
  details.append(el('strong', '服务返利说明'), el('p', `邀请成功注册可获得 ${data.signup_reward_points} 积分；被邀请用户购买套餐服务，可获得订单金额 5% 的现金返利；购买项目服务，可获得订单金额 5% 的现金返利。返利兑现请联系微信：ZDH200212zdh。`));
  const codeField = el('div', '', 'referral-share-field');
  const code = el('code', data.invite_code);
  const copyCode = button('复制邀请码', async () => {
    await navigator.clipboard.writeText(data.invite_code);
    notify('邀请码已复制。');
  }, 'button secondary');
  codeField.append(el('span', '我的邀请码'), code, copyCode);
  const url = new URL(window.location.href);
  url.hash = '';
  url.search = '';
  url.searchParams.set('invite', data.invite_code);
  const linkField = el('div', '', 'referral-share-field');
  const linkValue = el('input'); linkValue.readOnly = true; linkValue.value = url.toString(); linkValue.setAttribute('aria-label', '邀请注册链接');
  const copyLink = button('复制邀请链接', async () => {
    await navigator.clipboard.writeText(url.toString());
    notify('邀请链接已复制。');
  }, 'button secondary');
  linkField.append(el('span', '邀请链接'), linkValue, copyLink);
  const list = el('div', '', 'referral-list');
  if (!data.items.length) list.append(emptyState('还没有邀请记录', '分享邀请码或邀请链接，新用户首次注册时填写即可建立邀请关系。', '◇'));
  else for (const item of data.items) {
    const row = el('article', '', 'referral-row');
    const identity = el('div', '', 'referral-identity');
    identity.append(el('strong', item.username), el('small', item.email || '未绑定邮箱'));
    const serviceLabel = item.purchase_service === '套餐服务' ? '套餐服务 · 5%' : item.purchase_service === '项目服务' ? '项目服务 · 5%' : item.purchase_service || '暂无购买服务';
    const state = item.purchase_service ? item.rebate_redeemed ? '已兑现' : '待兑现' : '—';
    row.append(identity, el('span', serviceLabel, 'referral-service'), el('span', state, `referral-rebate-state ${item.rebate_redeemed ? 'redeemed' : item.purchase_service ? 'pending' : 'unset'}`));
    list.append(row);
  }
  const sharing = el('div', '', 'referral-share-grid');
  sharing.append(codeField, linkField);
  const recordsHeading = el('div', '', 'referral-records-heading');
  recordsHeading.append(el('h3', '邀请记录'), el('span', `${data.total_invited} 位用户`));
  root.replaceChildren(title, intro, sharing, details, recordsHeading, list);
}

export async function refreshReferrals() {
  const request = ++referralRequest, token = state.token;
  $('referralContent').replaceChildren(el('p', '正在加载邀请记录…', 'muted'));
  try { await renderReferrals(request, token); }
  catch (error) {
    if (request !== referralRequest || token !== state.token) return;
    const message = emptyState('邀请记录暂时无法加载', error.message, '◇');
    message.append(button('重新加载', () => { void refreshReferrals(); }, 'button secondary'));
    $('referralContent').replaceChildren(message);
  }
}

function updatePurchaseTotal() {
  const quantity = Number($("pointsPurchaseQuantity").value);
  const valid = Number.isInteger(quantity) && quantity > 0 && quantity <= 10000;
  const total = valid ? quantity * unitPointsCost : 0;
  $("pointsPurchaseTotal").textContent = valid ? `合计 ${total.toLocaleString("zh-CN")} 积分 · 当前可用 ${profilePoints} 积分` : "请输入 1～10000 的整数次数";
  $("pointsPurchaseSubmit").disabled = purchaseBusy || !valid || total > profilePoints;
  $("pointsPurchaseSubmit").textContent = valid && total > profilePoints ? "积分不足" : "确认购买";
}

function renderPointsHistory(records) {
  const labels = { redemption: "卡密兑换", checkin_reward: "每日训练连续签到", coding_checkin: "算法带刷连续签到", question_contribution: "题库贡献奖励", coding_contribution: "算法投稿奖励", leaderboard_reward: "周榜奖励", ranking_award: "周榜奖励", purchase_interview: "购买模拟面试次数", course_purchase: "课程积分购买", admin: "管理员调整" };
  if (!records.length) {
    $("pointsHistory").replaceChildren(emptyState("还没有积分记录", "签到、榜单奖励和卡密兑换获得积分后，可在这里查看收支。", "◇"));
    return;
  }
  const list = el("div", "", "points-history-list");
  for (const record of records) {
    const row = el("article", "", "points-history-row");
    const copy = el("div");
    copy.append(el("strong", labels[record.kind] || "积分变动"), el("p", `${dateTime(record.created)} · 余额 ${record.balance_after} 积分`));
    row.append(copy, el("strong", `${record.delta > 0 ? "+" : ""}${record.delta} 积分`, record.delta > 0 ? "points-income" : "points-expense"));
    list.append(row);
  }
  $("pointsHistory").replaceChildren(list);
}

export function setupCredits() {
  setupAccountSettings();
  $("interviewPointsCost").addEventListener("input", () => { pointsSettingsDirty = true; });
  $("pointsSettingsForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const value = $("interviewPointsCost").value;
      await api("/admin/credit-settings", { method: "PATCH", body: JSON.stringify({ interview_points_cost: Number(value) }) });
      pointsSettingsDirty = $("interviewPointsCost").value !== value;
      notify("积分购买规则已更新，后续购买立即生效。");
    }, event.submitter);
  });
  $("pointsRewardRulesForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const form = event.currentTarget;
      const payload = Object.fromEntries(['invite_signup_points', 'training_checkin_points_per_week', 'coding_checkin_points_per_week', 'training_questions_per_reward', 'training_contribution_points', 'coding_questions_per_reward', 'coding_contribution_points'].map(key => [key, Number(form.elements.namedItem(key).value)]));
      payload.leaderboard_rewards = [1, 2, 3].map(index => Number(form.elements.namedItem(`leaderboard_${index}`).value));
      await api('/admin/credit-settings', { method: 'PATCH', body: JSON.stringify(payload) });
      notify('积分奖励规则已更新，仅影响后续获得的奖励。');
      await refreshVouchers();
    }, event.submitter);
  });
  $("deleteVoucherPackage").addEventListener("click", event => run(async () => {
    const item = packageOptions.find(value => value.id === voucherPackage);
    if (!item || item.deleted) return;
    if (!await confirmAction(`删除「${money(item.price_fen)} / ${item.credits} 积分」套餐会同时永久删除该套餐下的全部卡密记录。未兑换卡密将立即失效，兑换历史也会删除；已经到账的积分不会退回。此操作不可撤销。`, { title: "删除套餐及全部卡密？", confirmText: "确认永久删除", danger: true })) return;
    await api(`/admin/voucher-packages/${encodeURIComponent(item.id)}`, { method: "DELETE" });
    notify("套餐及该套餐下的卡密记录已永久删除。");
    try { await refreshVouchers(); }
    catch { notify("套餐及卡密已删除，但列表刷新失败，请重新加载确认状态。", "error"); }
  }, event.currentTarget));
  $("pointsPurchaseQuantity").addEventListener("input", () => {
    if (purchaseQuantity !== Number($("pointsPurchaseQuantity").value)) purchaseRequestKey = null;
    $("pointsPurchaseError").hidden = true;
    updatePurchaseTotal();
  });
  $("pointsPurchaseForm").addEventListener("submit", event => {
    event.preventDefault();
    if (purchaseBusy || $("pointsPurchaseSubmit").disabled) return;
    const quantity = Number($("pointsPurchaseQuantity").value), expectedCost = unitPointsCost, token = state.token;
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 10000 || quantity * expectedCost > profilePoints) return;
    purchaseBusy = true;
    $("pointsPurchaseQuantity").disabled = true;
    void run(async () => {
      $("pointsPurchaseError").hidden = true;
      if (!await confirmAction(`使用 ${quantity * expectedCost} 积分购买 ${quantity} 次模拟面试。兑换成功后，次数会立即加入账户。`, { title: "确认积分购买", confirmText: "确认购买" })) return;
      if (token !== state.token || $("profile").hidden) return;
      if (purchaseToken !== token || purchaseQuantity !== quantity) purchaseRequestKey = null;
      purchaseToken = token;
      purchaseQuantity = quantity;
      purchaseRequestKey ||= crypto.randomUUID();
      try {
        const result = await api("/profile/purchases", { method: "POST", body: JSON.stringify({ product: "interview", quantity, idempotency_key: purchaseRequestKey, expected_unit_cost: expectedCost }) });
        if (token !== state.token) return;
        purchaseRequestKey = null;
        notify(result.already_purchased ? "该笔购买已完成，已更新余额。" : `购买成功，已增加 ${quantity} 次模拟面试。`);
        try { await refreshProfile(); }
        catch { notify("购买已成功，余额刷新失败，请重新进入个人主页查看。", "error"); }
      } catch (error) {
        if (token !== state.token) return;
        $("pointsPurchaseError").textContent = error.message;
        $("pointsPurchaseError").hidden = false;
        if (error.status === 409) { purchaseRequestKey = null; await refreshProfile(); }
      }
    }, event.submitter).finally(() => {
      purchaseBusy = false;
      $("pointsPurchaseQuantity").disabled = false;
      updatePurchaseTotal();
    });
  });
  $("defaultCredits").addEventListener("input", () => { defaultCreditsDirty = true; });
  $("voucherPackageForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const value = $("packagePrice").value;
      if (!/^\d+(\.\d{1,2})?$/.test(value)) throw new Error("金额最多保留两位小数");
      const [yuan, fraction = ""] = value.split(".");
      const price_fen = Number(yuan) * 100 + Number(fraction.padEnd(2, "0"));
      const result = await api("/admin/voucher-packages", { method: "POST", body: JSON.stringify({ price_fen, credits: Number($("packageCredits").value) }) });
      voucherPackage = result.id; voucherPage = 1;
      $("voucherBatch").value = ""; $("voucherSearch").value = ""; $("voucherStatus").value = "unused";
      $("voucherGeneratePackage").replaceChildren();
      $("voucherPackageForm").reset();
      notify("新套餐已添加，可以生成卡密了。");
      try { await refreshVouchers(); }
      catch { notify("新套餐已添加，但列表刷新失败。请点击重新加载；不要重复添加。", "error"); }
    }, event.submitter);
  });
  $("defaultCreditsForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const value = $("defaultCredits").value;
      await api("/admin/credit-settings", { method: "PATCH", body: JSON.stringify({ default_credits: Number(value) }) });
      defaultCreditsDirty = $("defaultCredits").value !== value;
      notify("新用户默认体验次数已更新；现有用户次数保持不变。");
    }, event.submitter);
  });
  $("voucherGenerateForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      const selected = $("voucherGeneratePackage").value;
      const cards = await api("/admin/vouchers", { method: "POST", body: JSON.stringify({ package: selected, count: Number($("voucherCount").value) }) });
      voucherPackage = selected; voucherPage = 1;
      $("voucherStatus").value = "unused"; $("voucherSearch").value = ""; $("voucherBatch").value = cards[0].batch;
      notify(`已生成 ${cards.length} 张新卡密，当前仅展示本批次，可直接导出。`);
      try { await refreshVouchers(); }
      catch { notify(`已生成 ${cards.length} 张卡密，但列表刷新失败。请点击重新加载；不要重复生成。`, "error"); }
    }, event.submitter);
  });
  for (const id of ["voucherSearch", "voucherBatch"]) $(id).addEventListener("input", () => {
    voucherPage = 1;
    voucherRequest++;
    clearTimeout(voucherSearchTimer);
    voucherLoading();
    voucherSearchTimer = setTimeout(() => run(refreshVouchers), 250);
  });
  $("voucherStatus").addEventListener("change", () => { voucherPage = 1; run(refreshVouchers); });
  $("clearVoucherFilters").addEventListener("click", () => {
    $("voucherSearch").value = ""; $("voucherBatch").value = ""; $("voucherStatus").value = "unused"; voucherPage = 1; run(refreshVouchers);
  });
  $("voucherPrevious").addEventListener("click", () => { voucherPage--; run(refreshVouchers); });
  $("voucherNext").addEventListener("click", () => { voucherPage++; run(refreshVouchers); });
  $("exportVouchers").addEventListener("click", event => run(async () => {
    const status = $("voucherStatus").value;
    if (status !== "unused" && !await confirmAction("当前导出范围可能包含已兑换卡密，不能用于商品上架。若用于联动小铺发货，请取消并选择「未兑换」。是否仍要导出用于核对？", { title: "导出包含已兑换卡密的记录？", confirmText: "仅用于核对，继续导出" })) return;
    const query = new URLSearchParams({ package: voucherPackage, status, q: $("voucherSearch").value.trim(), batch: $("voucherBatch").value.trim() });
    const response = await fetch(`/api/admin/vouchers/export?${query}`, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) throw new Error("卡密导出失败，请重新登录后重试");
    const value = await response.text();
    if (!value.trim()) throw new Error("当前筛选条件下没有可导出的卡密");
    download(value, `vouchers-${voucherPackage}-${$("voucherStatus").value}-${$("voucherBatch").value.trim() || "all"}.txt`);
    notify("已导出卡密文件，每行一张卡密，可上传到联动小铺。");
  }, event.currentTarget));
  $("redeemForm").addEventListener("submit", event => {
    event.preventDefault();
    run(async () => {
      $("redeemError").hidden = true;
      let result;
      try {
        result = await api("/profile/redeem", { method: "POST", body: JSON.stringify({ code: $("redeemCode").value }) });
        $("redeemCode").value = "";
      } catch (error) {
        $("redeemError").textContent = error.message;
        $("redeemError").hidden = false;
        return;
      }
      try {
        await refreshProfile();
        notify(`兑换成功，当前可用 ${result.points} 积分。可在积分购买区兑换面试次数。`);
      } catch {
        notify("兑换已成功，但余额刷新失败。请重新加载个人主页确认积分；不要重复兑换。", "error");
      }
    }, event.submitter);
  });
}
