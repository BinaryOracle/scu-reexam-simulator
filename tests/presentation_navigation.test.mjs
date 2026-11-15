import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/static/presentation.js", import.meta.url), "utf8");

test("fullscreen slide clicks advance and wheel direction controls slide navigation", () => {
  assert.match(source, /可点击或使用滚轮、方向键翻页/);
  assert.match(source, /viewer\.addEventListener\(["']click["'][\s\S]*?show\(page \+ 1\)/);
  assert.match(source, /const inFullscreen = \(\) => Boolean\(document\.fullscreenElement\?\.contains\(viewer\)\)/);
  assert.match(source, /viewer\.addEventListener\(["']wheel["'][\s\S]*?!inFullscreen\(\)/);
  assert.match(source, /event\.deltaY > 0 \? 1 : -1/);
  assert.match(source, /event\.preventDefault\(\)/);
  assert.match(source, /passive: false/);
});
