import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const read = name => readFile(new URL(`../app/static/${name}`, import.meta.url), "utf8");
const [leaderboard, training, coding, markup, styles] = await Promise.all([
  read("leaderboard.js"), read("training.js"), read("coding.js"), read("index.html"), read("leaderboard.css"),
]);

test("leaderboard renders four distinct weekly boards with regular-user names", () => {
  for (const key of ["training_checkins", "training_questions", "coding_checkins", "coding_solved"])
    assert.match(leaderboard, new RegExp(`${key}: \\{`));
  assert.match(leaderboard, /payload\.boards\[key\]/);
  assert.match(leaderboard, /typeof item\.username === "string"/);
  assert.match(leaderboard, /person\.append\(el\("strong", item\.username\)\)/);
  assert.match(leaderboard, /每周六 00:00（北京时间）结算/);
  assert.match(leaderboard, /\[\[1, 3\], \[2, 2\], \[3, 1\]\]/);
  assert.match(leaderboard, /row\.setAttribute\("aria-current", "true"\)/);
});

test("daily training and algorithm practice show only their own two boards", () => {
  assert.match(training, /from '\.\/leaderboard\.js\?v=20261117-weekly-leaderboard-v3'/);
  assert.match(training, /mountLeaderboard\(root, \{ scope: "training", onBack:/);
  assert.match(coding, /from "\.\/leaderboard\.js\?v=20261117-weekly-leaderboard-v3"/);
  assert.match(coding, /mountLeaderboard\(root, \{ scope: "coding", onBack:/);
});

test("leaderboard errors distinguish auth and missing API and provide retry", () => {
  assert.match(leaderboard, /error\.status === 401/);
  assert.match(leaderboard, /error\.status === 404/);
  assert.match(leaderboard, /重新加载/);
  assert.match(leaderboard, /排行榜数据暂未更新/);
});

test("leaderboard styling presents four boards cleanly on desktop and mobile", () => {
  assert.match(markup, /leaderboard\.css\?v=20261117-weekly-leaderboard-v3/);
  assert.match(styles, /\.leaderboard-grid\{display:grid;grid-template-columns:repeat\(2/);
  assert.match(styles, /\.leaderboard-row\.current/);
  assert.match(styles, /\.leaderboard-rewards/);
  assert.match(styles, /\.leaderboard-rows\{[^}]*max-height:634px[^}]*overflow-y:auto/);
  assert.match(styles, /overscroll-behavior:contain/);
  assert.match(styles, /@media \(max-width:700px\)/);
  assert.match(styles, /leaderboard-grid\{grid-template-columns:1fr/);
});

function leaderboardFixture(api) {
  const source = leaderboard.replace(/^import .*;\n/gm, "").replace(/^export /gm, "");
  class Element {
    constructor(tag, text = "", className = "") {
      this.tag = tag; this.textContent = String(text); this.className = className;
      this.children = []; this.parent = null; this.dataset = {}; this.attributes = {};
      this.isConnected = false;
    }
    append(...nodes) { for (const node of nodes) if (node) { node.parent = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const node of this.children) node.parent = null; this.children = []; this.append(...nodes); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, action) { if (name === "click") this.action = action; }
    get text() { return this.textContent + this.children.map(child => child.text).join(""); }
  }
  const root = new Element("section"); root.isConnected = true;
  const find = (node, predicate) => {
    if (predicate(node)) return node;
    for (const child of node.children) {
      const match = find(child, predicate);
      if (match) return match;
    }
    return null;
  };
  const context = vm.createContext({
    api, state: { user: { username: "alice" } },
    el: (tag, text, classes) => new Element(tag, text, classes),
    button: (text, action, classes) => { const node = new Element("button", text, classes); node.action = action; return node; },
    emptyState: (title, description, icon) => new Element("div", `${title}${description}${icon}`, "empty-state"),
  });
  vm.runInContext(source, context);
  return {
    root,
    mount: (options) => vm.runInContext("mountLeaderboard(root, options)", Object.assign(context, { root, options })),
    find: predicate => find(root, predicate),
  };
}

const codingPayload = {
  boards: {
    coding_checkins: [{ rank: 1, username: "alice", value: 2 }],
    coding_solved: [{ rank: 1, username: "alice", value: 4 }],
  },
  me: { coding_checkins: 1, coding_solved: 1 },
  period: { label: "11.14 — 11.20" },
};

test("coding leaderboard requests its scope and renders both cards", async () => {
  const paths = [];
  const fixture = leaderboardFixture(async path => { paths.push(path); return codingPayload; });
  await fixture.mount({ scope: "coding" });
  assert.deepEqual(paths, ["/leaderboard?scope=coding"]);
  assert.equal(fixture.find(node => node.className.includes("leaderboard-card-coding_checkins"))?.text.includes("算法带刷打卡"), true);
  assert.equal(fixture.find(node => node.className.includes("leaderboard-card-coding_solved"))?.text.includes("算法带刷通过"), true);
  assert.equal(fixture.root.text.includes("null"), false);
});

test("long ranking lists retain every row inside a keyboard-focusable scroll area", async () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({ rank: index + 1, username: `user-${index + 1}`, value: 12 - index }));
  const payload = { boards: { coding_checkins: rows, coding_solved: rows }, period: { label: "11.14 — 11.20" } };
  const fixture = leaderboardFixture(async () => payload);
  await fixture.mount({ scope: "coding" });
  const list = fixture.find(node => node.className === "leaderboard-rows");
  assert.ok(list);
  assert.equal(list.attributes.role, "list");
  assert.equal(list.tabIndex, 0);
  assert.equal(list.attributes["aria-label"], "排行榜排名，可滚动查看更多");
  assert.equal(list.children.filter(node => node.attributes.role === "listitem").length, 12);
});

test("leaderboard error keeps retry and return actions available", async () => {
  const fixture = leaderboardFixture(async () => { const error = new Error("登录状态已过期"); error.status = 401; throw error; });
  let returned = false;
  await fixture.mount({ scope: "training", onBack: () => { returned = true; } });
  const back = fixture.find(node => node.tag === "button" && node.textContent === "返回练习");
  assert.ok(back);
  assert.ok(fixture.find(node => node.tag === "button" && node.textContent === "重新加载"));
  back.action();
  assert.equal(returned, true);
});
