/** Searchable participant selection, isolated from contest problem editing. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button } from "./ui.js?v=20261114-ui-v17";

let selected = new Set();
let users = [];
let query = "";
let loaded = false;
let turn = 0;
let owner = null;
let legacy = false;

function render() {
  const root = $("contestParticipants"); root.replaceChildren(); root.className = "full-width contest-roster";
  const heading = el("div", "", "contest-roster-heading");
  const count = el("span", `已选择 ${selected.size} 位用户`, "muted"); heading.append(el("h3", "参赛用户"), count); root.append(heading);
  root.append(el("p", legacy ? "历史比赛原为所有用户开放；本次保存后按以下名单授权。管理员默认可查看和管理比赛。" : "仅选中用户可进入比赛和查看赛后题目；管理员默认可查看和管理比赛。", "field-help"));
  if (!loaded) { root.append(el("p", "正在加载用户名单…", "muted")); return; }
  const tools = el("div", "", "contest-roster-tools");
  const search = el("input"); search.type = "search"; search.placeholder = "搜索用户名或邮箱"; search.setAttribute("aria-label", "搜索参赛用户"); search.value = query;
  const list = el("div", "", "contest-roster-list"); list.setAttribute("aria-label", "可参加比赛的用户");
  const filtered = () => users.filter(user => `${user.username} ${user.email || ""}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const draw = () => {
    list.replaceChildren(); count.textContent = `已选择 ${selected.size} / ${users.length} 位用户`;
    for (const user of filtered()) {
      const label = el("label", "", "contest-roster-user"); const check = el("input"); check.type = "checkbox"; check.checked = selected.has(user.id);
      check.setAttribute("aria-label", `允许 ${user.username} 参加比赛`);
      check.addEventListener("change", () => { if (check.checked) selected.add(user.id); else selected.delete(user.id); count.textContent = `已选择 ${selected.size} / ${users.length} 位用户`; });
      const copy = el("span", user.username); if (user.email || !user.is_active) copy.append(el("small", [user.email, !user.is_active ? "账号已停用" : ""].filter(Boolean).join(" · ")));
      label.append(check, copy); list.append(label);
    }
    if (!filtered().length) list.append(el("p", "没有匹配的用户", "muted"));
  };
  search.addEventListener("input", () => { query = search.value.trim(); draw(); });
  tools.append(search, button("选择筛选结果", () => { filtered().forEach(user => selected.add(user.id)); draw(); }, "text-button"), button("清空选择", () => { selected.clear(); draw(); }, "text-button"));
  root.append(tools, list); draw();
}

export async function loadContestRoster(cid = null) {
  const current = ++turn, token = state.token; owner = token; loaded = false; selected.clear(); query = ""; legacy = false; render();
  try {
    const [accounts, roster] = await Promise.all([api("/admin/contest-participants"), cid ? api(`/admin/contests/${cid}/participants`) : Promise.resolve({ participant_ids: [] })]);
    if (current !== turn || token !== state.token) return;
    users = accounts; selected = new Set(roster.participant_ids); legacy = Boolean(roster.legacy_open); loaded = true; render();
  } catch (error) {
    if (current !== turn || token !== state.token) return;
    $("contestParticipants").replaceChildren(el("p", error.message, "form-error"), button("重新加载名单", () => loadContestRoster(cid), "button secondary"));
    throw error;
  }
}
export function resetContestRoster() { turn++; selected.clear(); query = ""; legacy = false; loaded = false; render(); }
export function contestParticipantIds() {
  if (!loaded || owner !== state.token) throw new Error("参赛名单尚未加载完成，请展开比赛表单后重试");
  return [...selected];
}
export function setupContestRoster() {
  $("contestForm").closest("details").addEventListener("toggle", () => {
    if ($("contestForm").closest("details").open && (!loaded || owner !== state.token)) void loadContestRoster().catch(error => {
      // The loader keeps the failure and retry control in the form.
    });
  });
}
