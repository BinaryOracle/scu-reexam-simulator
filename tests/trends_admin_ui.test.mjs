import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/trends.js", import.meta.url), "utf8");
const periodControlsSource = source
  .slice(source.indexOf("function periodControls()"), source.indexOf("function sourceList("));
const buildPageSource = source
  .slice(source.indexOf("function buildPage()"), source.indexOf("export async function refreshTrends()"));
const periodsSource = source.slice(source.indexOf("const periods ="), source.indexOf("let selectedTrend"));

class Node {
  constructor(tag, text = "", className = "") {
    this.tag = tag;
    this.textContent = text;
    this.className = className;
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this.attributes = {};
    this.classList = { toggle() {} };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
}

function buildPage(adminMode) {
  const root = new Node("main");
  const context = vm.createContext({
    $, el: (tag, text, className) => new Node(tag, text, className),
    button: (text, action, className) => {
      const node = new Node("button", text, className);
      node.action = action;
      return node;
    },
    state: { adminMode },
    Option: class Option extends Node {
      constructor(text, value) { super("option", text); this.value = value; }
    },
    root,
    loadPeriod: async () => {},
  });
  vm.runInContext(`${periodsSource}\n${periodControlsSource}\n${buildPageSource}\nbuildPage();`, context);
  return root;

  function $(id) {
    if (id === "trendsContent") return root;
    throw new Error(`Unexpected element lookup: ${id}`);
  }
}

test("trend management controls are visible only in admin mode", () => {
  const adminPage = buildPage(true);
  const userPage = buildPage(false);
  const adminPanel = adminPage.children.find(node => node.id === "trendAdminPanel");
  const userPanel = userPage.children.find(node => node.id === "trendAdminPanel");

  assert.equal(adminPanel.hidden, false);
  assert.equal(userPanel.hidden, true);
});

test("trend tabs offer only current week, month and year with week selected", () => {
  const page = buildPage(false);
  const filter = page.children.find(node => node.className === "trend-filter-row");
  const tabs = filter.children[0].children;
  assert.deepEqual(tabs.map(node => node.textContent), ["当周趋势", "当月趋势", "当年趋势"]);
  assert.equal(tabs[0].attributes["aria-selected"], "true");
});
