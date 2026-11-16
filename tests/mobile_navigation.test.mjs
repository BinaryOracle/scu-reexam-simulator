import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const [appSource, styleSource] = await Promise.all([
  readFile(new URL("../app/static/app.js", import.meta.url), "utf8"),
  readFile(new URL("../app/static/style.css", import.meta.url), "utf8"),
]);

test("mobile user navigation keeps readable fixed-width items and reveals the active page", () => {
  const navigationMarker = styleSource.indexOf("body:not(.admin-mode) .sidebar-nav-group");
  const navigationStart = styleSource.lastIndexOf(".sidebar nav {", navigationMarker);
  const navigationEnd = styleSource.indexOf(".sidebar-bottom {", navigationStart);
  const navigation = styleSource.slice(navigationStart, navigationEnd);
  assert.match(navigation, /\.sidebar nav \{[\s\S]*?overflow-x:\s*auto/);
  assert.match(navigation, /\.nav-item \{[\s\S]*?flex:\s*0 0 66px;[\s\S]*?min-width:\s*66px;/);
  assert.match(navigation, /body:not\(\.admin-mode\) \.sidebar-nav-parent > \.nav-item \{\s*flex:\s*0 0 66px;\s*min-width:\s*66px;/);
  assert.match(appSource, /const navigation = item\?\.closest\("nav"\)/);
  assert.match(appSource, /navigation\.scrollBy\(\{ left: delta, behavior: "instant" \}\)/);
  assert.match(styleSource, /\.admin-mode \.sidebar nav \{[\s\S]*?scroll-snap-type:\s*none/);
  assert.match(styleSource, /\.admin-mode \.sidebar nav \{[\s\S]*?padding-right:\s*12px/);
});

test("reveals either clipped edge without moving an already visible navigation item", () => {
  let bounds = { left: 324, right: 396 };
  const scrolls = [];
  const navigation = {
    getBoundingClientRect: () => ({ left: 20, right: 370 }),
    scrollBy: value => scrolls.push(value.left),
  };
  const item = { closest: () => navigation, getBoundingClientRect: () => bounds };
  const context = vm.createContext({
    window: { matchMedia: () => ({ matches: true }) },
    document: { querySelector: () => item },
  });
  const start = appSource.indexOf("function revealActiveNavigation()");
  const end = appSource.indexOf("function configureContestNavigation()", start);
  vm.runInContext(appSource.slice(start, end), context);
  context.revealActiveNavigation();
  bounds = { left: 10, right: 82 };
  context.revealActiveNavigation();
  bounds = { left: 30, right: 102 };
  context.revealActiveNavigation();
  assert.deepEqual(scrolls, [26, -10]);
});
