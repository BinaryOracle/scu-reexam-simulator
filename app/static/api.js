/** Authenticated API access for the standalone application. */
export const state = {
  token: sessionStorage.getItem("token"),
  user: null,
  adminMode: /^\/admin\/?$/.test(location.pathname),
};
export async function api(path, options = {}) {
  const headers = { ...options.headers };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response
    .json()
    .catch(() => ({ detail: "服务返回了无法读取的响应" }));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? "请检查输入内容是否完整、格式是否正确"
      : data.detail || "请求失败，请稍后重试";
    const error = new Error(detail);
    error.status = response.status;
    if (response.status === 429) {
      const seconds = Number(response.headers.get("Retry-After"));
      error.retryAfterSeconds = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60;
    }
    if (path !== "/login" && !path.startsWith("/auth/") && response.status === 401)
      window.dispatchEvent(new Event("session-expired"));
    if (response.status === 403)
      window.dispatchEvent(new Event("access-denied"));
    throw error;
  }
  return data;
}
export async function audioBlob(path) {
  const response = await fetch(`/api${path}`, {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (!response.ok) throw new Error("录音读取失败，请刷新后重试");
  return response.blob();
}
