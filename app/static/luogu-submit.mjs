/** Retry only an explicitly rejected captcha after a human supplies its answer. */
export async function submitWithLuoguVerification(payload, { send, requestCaptcha }) {
  const submission = { ...payload };
  let response = await send(submission);
  let hint = "";
  while (response?.captcha_required) {
    const captcha = await requestCaptcha(response, hint);
    if (!captcha) throw new Error("已取消验证码，本次提交未被洛谷受理。");
    response = await send({ ...submission, captcha });
    hint = "验证码未通过，请输入新图片中的字符。";
  }
  return response;
}
