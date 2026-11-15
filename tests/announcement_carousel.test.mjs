import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../app/static/home.js", import.meta.url), "utf8");
const render = source.slice(source.indexOf("function renderNotices(root)"), source.indexOf("function navigate(view"));

class Node {
  constructor(tag, text = "", className = "") {
    Object.assign(this, { tag, textContent: text, className, childNodes: [], attributes: {}, style: {} });
  }
  append(...nodes) { this.childNodes.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = value; }
}

function renderAnnouncements(notices) {
  const context = {
    notices,
    announcementIndex: 0,
    announcementsUnavailable: false,
    el: (...args) => new Node(...args),
    button: (text, action, className) => Object.assign(new Node("button", text, className), { action }),
    openAnnouncement() {},
    openAnnouncementList() {},
    refreshHome() {},
  };
  vm.createContext(context);
  vm.runInContext(render, context);
  const root = new Node("main");
  context.renderNotices(root);
  return root.childNodes[0];
}

test("a single announcement stays readable without a moving duplicate", () => {
  const band = renderAnnouncements([{ title: "平台功能与奖励规则说明" }]);
  const viewport = band.childNodes[1];
  assert.equal(viewport.childNodes[0].textContent, "平台功能与奖励规则说明");
  assert.equal(band.childNodes.length, 2);
  assert.equal(viewport.attributes["aria-live"], "polite");
});

test("multiple announcements have keyboard-accessible previous and next controls", () => {
  const band = renderAnnouncements([{ title: "第一条公告" }, { title: "第二条公告" }]);
  const viewport = band.childNodes[1];
  const controls = band.childNodes[2];
  assert.equal(viewport.childNodes[0].textContent, "第一条公告");
  assert.equal(controls.childNodes[0].textContent, "1 / 2");
  assert.equal(controls.childNodes[2].attributes["aria-label"], "下一条公告");
  controls.childNodes[2].action();
  assert.equal(viewport.childNodes[0].textContent, "第二条公告");
  assert.equal(controls.childNodes[0].textContent, "2 / 2");
  controls.childNodes[1].action();
  assert.equal(viewport.childNodes[0].textContent, "第一条公告");
});
