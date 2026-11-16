import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/home.js", import.meta.url), "utf8");
const reminderSource = source
  .slice(source.indexOf("export async function showPendingAnnouncementReminder()"), source.indexOf("export function setupHome()"))
  .replace("export async function showPendingAnnouncementReminder()", "async function showPendingAnnouncementReminder()");

function reminderContext({ items, adminMode = false, dialogOpen = false }) {
  const context = {
    state: { token: "session-1", adminMode },
    notices: [], reminderCheckRevision: 0,
    $(id) { assert.equal(id, "announcementDialog"); return { open: dialogOpen }; },
    api: async () => items,
    openAnnouncement(item) { context.opened = item; },
  };
  vm.createContext(context);
  vm.runInContext(`${reminderSource}\nshowPendingAnnouncementReminderPromise = showPendingAnnouncementReminder();`, context);
  return context;
}

test("opens the first published announcement pending confirmation for this account", async () => {
  const context = reminderContext({ items: [
    { id: 1, reminder_pending: false },
    { id: 2, reminder_pending: true },
    { id: 3, reminder_pending: true },
  ] });
  await context.showPendingAnnouncementReminderPromise;
  assert.equal(context.opened.id, 2);
  assert.equal(context.notices.length, 3);
});

test("does not open a reminder for administrators or over an already-open dialog", async () => {
  for (const options of [{ items: [{ id: 1, reminder_pending: true }], adminMode: true },
    { items: [{ id: 1, reminder_pending: true }], dialogOpen: true }]) {
    const context = reminderContext(options);
    await context.showPendingAnnouncementReminderPromise;
    assert.equal(context.opened, undefined);
  }
});
