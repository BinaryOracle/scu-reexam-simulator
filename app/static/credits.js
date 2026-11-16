/** Interview balances and voucher administration have no external shop API. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, emptyState, notify, run, dateTime, badge, confirmAction } from "./ui.js?v=20261114-ui-v17";
import { refreshAccountSettings, setupAccountSettings } from "./profile-account.js?v=20261116-ui-audit-v2";

import { refreshTransfers } from "./credit-transfers.js?v=20261115-dialog-v1";

let voucherPackage = "";
let voucherPage = 1;
let voucherRequest = 0;
let voucherSearchTimer;
let defaultCreditsDirty = false;
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
  if (!settings.packages.some(item => item.id === voucherPackage)) voucherPackage = settings.packages[0]?.id || "";
  const selected = $("voucherGeneratePackage").value;
  $("voucherGeneratePackage").replaceChildren(...settings.packages.map(item => {
    const option = el("option", `${money(item.price_fen)} / ${item.credits} 次`); option.value = item.id; return option;
  }));
  $("voucherGeneratePackage").value = settings.packages.some(item => item.id === selected) ? selected : voucherPackage;
  $("voucherGenerateForm").querySelector('[type="submit"]').disabled = !settings.packages.length;
  $("voucherPackageTabs").replaceChildren(...settings.packages.map(item => {
    const control = button(`${money(item.price_fen)} / ${item.credits} 次`, () => {
      voucherPackage = item.id; voucherPage = 1; $("voucherBatch").value = "";
      return refreshVouchers();
    }, item.id === voucherPackage ? "selected" : "");
    control.dataset.voucherPackage = item.id;
    control.setAttribute("aria-pressed", String(item.id === voucherPackage));
    return control;
  }));
  const query = new URLSearchParams({ package: voucherPackage, status: $("voucherStatus").value,
    q: $("voucherSearch").value.trim(), batch: $("voucherBatch").value.trim(), page: voucherPage });
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
  for (const title of ["卡密", "批次", "次数 / 标价", "兑换状态", "兑换用户", "兑换时间"]) {
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
    row.append(code, batch, el("td", `${item.credits} 次 / ${money(item.price_fen)}`), status,
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
    addField("套餐", `${item.credits} 次 / ${money(item.price_fen)}`);
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
  const data = await api("/profile");
  state.user.interview_credits = data.remaining;
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
    $("redemptionHistory").replaceChildren(emptyState("暂无兑换记录", "兑换成功后，次数和对应套餐金额会显示在这里。", "◇"));
  } else {
    const list = el("div", "", "redemption-list");
    for (const record of data.redemptions) {
      const row = el("article", "", "redemption-record");
      const copy = el("div");
      copy.append(el("strong", `新增 ${record.credits} 次面试`), el("p", `卡密尾号 ${record.code_suffix} · ${dateTime(record.redeemed_at)}`));
      row.append(copy, el("span", money(record.amount_fen), "redemption-price"));
      list.append(row);
    }
    $("redemptionHistory").replaceChildren(list);
  }
  try { await refreshTransfers(data, refreshProfile); }
  catch {
    const message = emptyState("转赠记录暂时无法加载", "余额和兑换信息已更新；请稍后重试查看转赠记录。", "◇");
    message.append(button("重新加载", () => { void refreshProfile(); }, "button secondary"));
    $("profileTransfers").replaceChildren(message);
  }
  try {
    const contribution = await api("/training/contribution-rewards");
    contributionRoot.replaceChildren();
    const contributionHeading = el("div", "", "contribution-heading");
    contributionHeading.append(el("div", "题库贡献奖励", "eyebrow"),
      el("h2", contribution.exempt ? "管理员账号不参与奖励" : "分享题目，获得面试次数"));
    const contributionProgress = el("p", contribution.exempt
      ? "普通用户投稿审核通过并公开后计入奖励。"
      : "当前规则：每 " + contribution.policy.questions_per_reward + " 道公开题奖励 " +
        contribution.policy.credits_per_reward + " 次；本规则下已通过 " + contribution.approved_count +
        " 道，再通过 " + contribution.remaining_questions + " 道可达下一奖励。", "muted");
    contributionRoot.append(contributionHeading, contributionProgress);
    if (!contribution.exempt) {
      const history = el("div", "", "contribution-history");
      for (const grant of contribution.grants.slice(0, 5))
        history.append(el("span", "+" + grant.credits + " 次 · " + new Date(grant.created * 1000).toLocaleDateString("zh-CN")));
      if (!contribution.grants.length) history.append(el("span", "审核通过的投稿达到规则数量后，会在这里显示奖励记录。"));
      contributionRoot.append(history);
    }
  } catch {
    const message = emptyState("贡献奖励信息暂时无法加载", "账户余额与兑换记录仍可正常查看。", "◇");
    message.append(button("重新加载", () => { void refreshProfile(); }, "button secondary"));
    contributionRoot.replaceChildren(message);
  }
}

export function setupCredits() {
  setupAccountSettings();
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
        notify(`兑换成功，当前剩余 ${result.remaining} 次模拟面试。`);
      } catch {
        notify("兑换已成功，但余额刷新失败。请重新加载个人主页确认次数；不要重复兑换。", "error");
      }
    }, event.submitter);
  });
}
