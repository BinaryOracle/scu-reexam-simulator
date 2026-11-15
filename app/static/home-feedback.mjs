/** Choose concise recovery copy for home-layout loading failures. */
export function homeLayoutErrorMessage(error) {
  if (error?.status === 401) return "登录状态已失效，请重新登录后再试。";
  if (error?.status === 403) return "当前账号暂不可访问备考内容，请联系管理员确认权限。";
  if (error instanceof TypeError) return "网络连接失败，请检查网络后重试。";
  return "备考内容暂时无法加载，请稍后重试。";
}
