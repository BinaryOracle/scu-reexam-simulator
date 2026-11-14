/** Reads the active top-level view from the current hash route. */
export function readAppRoute(hash, allowedViews, fallback) {
  const raw = String(hash || "").replace(/^#/, "");
  if (!raw.startsWith("view=")) return fallback;
  const route = raw.slice("view=".length);
  const view = route.split("/")[0];
  return allowedViews.includes(view) ? view : fallback;
}

/** Identifies a hash that belongs to the app router rather than a document anchor. */
export function isAppRouteHash(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  return !raw || raw.startsWith("view=");
}

/** Writes an app route without changing the current pathname or query. */
export function writeAppRoute(route, { history = window.history, location = window.location, replace = false } = {}) {
  const value = String(route || "").replace(/^#+/, "").replace(/^\/+/, "");
  const url = new URL(location.href);
  url.hash = value ? `view=${value}` : "";
  if (url.hash === location.hash) return false;
  const state = { ...(history.state || {}), appRoute: value };
  const method = replace ? "replaceState" : "pushState";
  history[method](state, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}

/** Changes the top-level view while preserving an existing nested route for that view. */
export function writeAppViewRoute(view, allowedViews, options = {}) {
  const location = options.location || window.location;
  if (readAppRoute(location.hash, allowedViews, null) === view) return false;
  return writeAppRoute(view, options);
}
