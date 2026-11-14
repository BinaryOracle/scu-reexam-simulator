import assert from "node:assert/strict";
import test from "node:test";
import { isAppRouteHash, readAppRoute, writeAppRoute, writeAppViewRoute } from "../app/static/view-route.mjs";

test("reads a view while ignoring nested contest route segments", () => {
  assert.equal(readAppRoute("#view=contest/42/workspace/8", ["home", "contest"], "home"), "contest");
});

test("falls back when a route is not available to the current user", () => {
  assert.equal(readAppRoute("#view=users", ["home", "contest"], "home"), "home");
  assert.equal(readAppRoute("", ["home", "contest"], "home"), "home");
  assert.equal(readAppRoute("#mainContent", ["home", "contest"], "home"), "home");
  assert.equal(isAppRouteHash("#mainContent"), false);
  assert.equal(isAppRouteHash("#view=home"), true);
});

test("pushes app routes while preserving the site path and query", () => {
  const calls = [];
  const location = { href: "https://example.test/admin?source=direct", hash: "" };
  const history = {
    state: { session: 7 },
    pushState(...args) { calls.push(["push", ...args]); location.hash = new URL(args[2], location.href).hash; },
    replaceState(...args) { calls.push(["replace", ...args]); location.hash = new URL(args[2], location.href).hash; },
  };

  assert.equal(writeAppRoute("announcementsAdmin", { history, location }), true);
  assert.deepEqual(calls[0], ["push", { session: 7, appRoute: "announcementsAdmin" }, "", "/admin?source=direct#view=announcementsAdmin"]);
  assert.equal(writeAppRoute("announcementsAdmin", { history, location }), false);
});

test("replaces invalid or initial routes without adding a history entry", () => {
  const calls = [];
  const location = { href: "http://localhost/admin", hash: "" };
  const history = { state: null, pushState() { calls.push("push"); }, replaceState(...args) { calls.push(args); } };
  writeAppRoute("users", { history, location, replace: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][2], "/admin#view=users");
});

test("keeps a nested route when restoring its top-level view", () => {
  const calls = [];
  const location = { href: "http://localhost/#view=contest/42/workspace/8", hash: "#view=contest/42/workspace/8" };
  const history = { state: null, pushState() { calls.push("push"); }, replaceState() { calls.push("replace"); } };
  assert.equal(writeAppViewRoute("contest", ["home", "contest"], { history, location, replace: true }), false);
  assert.deepEqual(calls, []);
});
