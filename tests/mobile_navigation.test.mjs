import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
  assert.match(appSource, /item\?\.scrollIntoView\(\{\s*behavior:\s*"instant",\s*block:\s*"nearest",\s*inline:\s*"nearest"\s*\}\)/);
});
