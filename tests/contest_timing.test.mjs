import assert from "node:assert/strict";
import test from "node:test";
import { contestTiming, canOpenContestProblems } from "../app/static/contest-timing.mjs";

const contest = { starts: 1000, ends: 4600 };

test("shows time until start without consuming the contest progress", () => {
  const timing = contestTiming(contest, 700);
  assert.equal(timing.phase, "upcoming");
  assert.equal(timing.clock, "00:05:00");
  assert.equal(timing.percent, 0);
  assert.equal(timing.urgent, false);
});

test("updates elapsed progress and remaining time across the full contest", () => {
  assert.equal(contestTiming(contest, 1000).percent, 0);
  const middle = contestTiming(contest, 2800);
  assert.equal(middle.phase, "running");
  assert.equal(middle.percent, 50);
  assert.equal(middle.clock, "00:30:00");
  assert.equal(middle.urgent, false);
  assert.equal(contestTiming(contest, 4300).urgent, true);
  assert.equal(contestTiming(contest, 4599.2).clock, "00:00:01");
});

test("clamps the finished timeline and keeps the end-time submission boundary", () => {
  assert.equal(contestTiming(contest, 4600).phase, "running");
  const ended = contestTiming(contest, 4700);
  assert.equal(ended.phase, "ended");
  assert.equal(ended.percent, 100);
  assert.equal(ended.clock, "00:00:00");
  assert.equal(ended.urgent, false);
});

test("allows direct problem navigation during and after the contest, while protecting upcoming problems", () => {
  assert.equal(canOpenContestProblems(contest, 999), false);
  assert.equal(canOpenContestProblems(contest, 1000), true);
  assert.equal(canOpenContestProblems(contest, 4601), true);
  assert.equal(canOpenContestProblems(contest, 999, true), true);
});
