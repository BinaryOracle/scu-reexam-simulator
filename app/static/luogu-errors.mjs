/** Format Luogu bridge failures into actionable user-facing messages. */
export function formatLuoguSubmitError(error) {
  const message = typeof error === "string" ? error : error?.message;
  if (!message) return "洛谷提交失败，请稍后重试。";
  if (!/captcha|验证码|人机验证|安全验证/i.test(message)) return message;
  const problemUrl = message.match(/https:\/\/www\.luogu\.com\.cn\/problem\/[A-Z0-9]+/i)?.[0];
  if (problemUrl) return `洛谷暂时未接受这次提交，需要完成安全验证。请打开本题页面：${problemUrl}，按页面提示处理后回到知序重试。`;
  if (/已为你打开洛谷题目页/.test(message)) return "洛谷暂时未接受这次提交，需要完成安全验证。已打开本题的洛谷页面，请按页面提示处理后回到知序重试。";
  return "洛谷暂时未接受这次提交，需要完成安全验证。请切换到洛谷页面，按页面提示处理后回到知序重试。";
}

/** Return whether the installed extension predates guided captcha recovery. */
export function isLuoguExtensionOutdated(version) {
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) return true;
  const current = version.split(".").map(Number);
  const minimum = [1, 0, 2];
  for (let index = 0; index < minimum.length; index++) {
    if (current[index] !== minimum[index]) return current[index] < minimum[index];
  }
  return false;
}
