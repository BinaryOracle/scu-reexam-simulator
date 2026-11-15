/** Derive countdown and elapsed progress from the same clock reading, in epoch seconds. */
export function contestTiming(contest, now = Date.now() / 1000) {
  const phase = now < contest.starts ? "upcoming" : now > contest.ends ? "ended" : "running";
  const remaining = Math.max(0, Math.ceil((phase === "upcoming" ? contest.starts : contest.ends) - now));
  const duration = contest.ends - contest.starts;
  const percent = Math.min(100, Math.max(0, (now - contest.starts) / duration * 100));
  const hours = Math.floor(remaining / 3600);
  const minutes = Math.floor(remaining % 3600 / 60);
  const clock = [hours, minutes, remaining % 60].map(value => String(value).padStart(2, "0")).join(":");
  return { phase, percent, clock, urgent: phase === "running" && remaining <= 300 };
}

/** Finished contests remain open for review; upcoming problems stay private to administrators. */
export function canOpenContestProblems(contest, now = Date.now() / 1000, isAdmin = false) {
  return isAdmin || now >= contest.starts;
}
