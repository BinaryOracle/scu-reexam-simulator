import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/home.js", import.meta.url), "utf8");
const refreshSource = source
  .slice(source.indexOf("export async function refreshHome()"), source.indexOf("export async function showPendingAnnouncementReminder()"))
  .replace("export async function refreshHome()", "async function refreshHome()");

test("home paints its primary actions before the optional announcement request resolves", async () => {
  let resolveAnnouncements;
  const announcements = new Promise(resolve => { resolveAnnouncements = resolve; });
  const context = vm.createContext({
    notices: [],
    announcementIndex: 0,
    announcementsUnavailable: false,
    announcementRequestRevision: 0,
    showPendingAnnouncementReminder: () => { context.reminderCalls += 1; },
    reminderCalls: 0,
    state: { token: "session-1" },
    api: () => announcements,
    renderHome: () => { context.renderCount += 1; },
    renderCount: 0,
  });
  vm.runInContext(`${refreshSource}\nrefreshHomePromise = refreshHome();`, context);
  assert.equal(context.renderCount, 1);
  resolveAnnouncements([{ title: "公告" }]);
  await context.refreshHomePromise;
  assert.equal(context.renderCount, 2);
  assert.deepEqual(context.notices, [{ title: "公告" }]);
  assert.equal(context.reminderCalls, 1);
});
