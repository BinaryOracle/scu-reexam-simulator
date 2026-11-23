/** Authenticated API access for the standalone application. */
export const state = {
  token: sessionStorage.getItem("token"),
  user: null,
  adminMode: /^\/admin\/?$/.test(location.pathname),
};
/** Return the current account or report an expired workspace state. */
export function requireAuthenticatedUser(user = state.user) {
  if (!user || typeof user.username !== "string")
    throw new Error("登录状态已失效，请重新登录后再试。");
  return user;
}
const fieldLabels = {
  email: "邮箱",
  username: "用户名",
  password: "密码",
  current_password: "当前密码",
  new_password: "新密码",
  confirmation: "确认内容",
  code: "兑换码",
  quantity: "购买次数",
  credits: "积分数量",
  price_fen: "套餐价格",
  title: "标题",
  content: "内容",
};
function validationMessage(issue) {
  const message = String(issue.msg || "输入格式不正确");
  if (message === "Field required") return "必填";
  if (message.includes("valid integer")) return "请输入整数";
  if (message.includes("valid number")) return "请输入数字";
  if (message.includes("valid string")) return "请输入文本";
  if (message.includes("valid email")) return "邮箱格式不正确";
  const length = message.match(/at most (\d+) characters?/i);
  if (length) return `最多允许 ${length[1]} 个字符`;
  const minimum = message.match(/at least (\d+) characters?/i);
  if (minimum) return `至少需要 ${minimum[1]} 个字符`;
  const lowerBound = message.match(/greater than or equal to (.+)$/i);
  if (lowerBound) return `不能小于 ${lowerBound[1]}`;
  const upperBound = message.match(/less than or equal to (.+)$/i);
  if (upperBound) return `不能大于 ${upperBound[1]}`;
  return message;
}
function formatValidationErrors(issues) {
  const messages = issues.slice(0, 3).map(issue => {
    const location = Array.isArray(issue.loc) ? issue.loc.filter(part => !["body", "query", "path"].includes(part)) : [];
    const field = location.map(part => fieldLabels[part] || String(part)).join(" → ") || "请求内容";
    return `${field}：${validationMessage(issue)}`;
  });
  if (issues.length > messages.length) messages.push(`另有 ${issues.length - messages.length} 项需要修正`);
  return messages.join("；") || "请检查输入内容是否完整、格式是否正确";
}
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
      ? formatValidationErrors(data.detail)
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
