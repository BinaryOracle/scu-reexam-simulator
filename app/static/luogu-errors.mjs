/** Format Luogu bridge failures into actionable user-facing messages. */
export function formatLuoguSubmitError(error) {
  const message = typeof error === "string" ? error : error?.message;
  if (!message) return "洛谷提交失败，请稍后重试。";
  if (/浏览器插件未响应|插件未响应/.test(message))
    return "没有收到洛谷插件响应。请确认扩展已启用且本站来源已配置，再检测洛谷登录状态；仍无法连接时请打开插件配置教程。";
  if (/已取消验证码|未接受该验证码/.test(message)) return message;
  if (!/captcha|验证码|人机验证|安全验证/i.test(message)) return message;
  return "洛谷暂时未接受这次提交，需要完成安全验证。请切换到洛谷页面，按页面提示处理后回到知序重试。";
}

/** Return whether the installed shared judge extension predates multi-platform support. */
export function isJudgeExtensionOutdated(version) {
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) return true;
  const current = version.split(".").map(Number);
  const minimum = [1, 3, 0];
  for (let index = 0; index < minimum.length; index++) {
    if (current[index] !== minimum[index]) return current[index] < minimum[index];
  }
  return false;
}
