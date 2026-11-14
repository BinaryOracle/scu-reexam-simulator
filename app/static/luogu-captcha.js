import { el } from "./ui.js?v=20261114-ui-v18";

/** Ask the user to enter an image captcha and release image memory on close. */
export function requestLuoguCaptcha(challenge, hint = "") {
  const supportedTypes = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  if (!supportedTypes.includes(challenge.captcha_mime_type) || !Array.isArray(challenge.captcha_image)
      || challenge.captcha_image.length < 1 || challenge.captcha_image.length > 100000
      || challenge.captcha_image.some(byte => !Number.isInteger(byte) || byte < 0 || byte > 255))
    throw new Error("无法显示洛谷验证码图片，请稍后重试。");
  return new Promise(resolve => {
    const previousFocus = document.activeElement;
    const dialog = el("dialog", "", "account-dialog luogu-captcha-dialog");
    const form = el("form");
    form.noValidate = true;
    const header = el("div", "", "dialog-header");
    const title = el("h2", "完成洛谷验证码");
    title.id = "luoguCaptchaTitle";
    const headerCopy = el("div");
    headerCopy.append(el("span", "LUOGU VERIFICATION", "eyebrow"), title);
    const close = el("button", "×", "icon-button");
    close.type = "button";
    close.setAttribute("aria-label", "关闭验证码");
    header.append(headerCopy, close);
    const body = el("div", "", "dialog-body luogu-captcha-body");
    const description = el("p", "洛谷需要人工验证。输入图片中的字符后，验证码会由浏览器直接发回洛谷。", "muted");
    const imageUrl = URL.createObjectURL(new Blob([
      Uint8Array.from(challenge.captcha_image),
    ], { type: challenge.captcha_mime_type }));
    const image = el("img", "", "luogu-captcha-image");
    image.src = imageUrl;
    image.alt = "洛谷验证码";
    const label = el("label", "验证码");
    label.htmlFor = "luoguCaptchaInput";
    const input = el("input");
    input.id = label.htmlFor;
    input.name = "captcha";
    input.type = "text";
    input.autocomplete = "off";
    input.autocapitalize = "characters";
    input.spellcheck = false;
    input.maxLength = 16;
    input.required = true;
    input.setAttribute("aria-label", "输入洛谷验证码");
    const error = el("p", hint, "form-error");
    error.id = "luoguCaptchaError";
    error.hidden = !hint;
    error.setAttribute("role", "alert");
    input.setAttribute("aria-describedby", error.id);
    image.addEventListener("error", () => {
      error.textContent = "验证码图片加载失败，请取消后重新提交。";
      error.hidden = false;
      submit.disabled = true;
    });
    body.append(description, error, image, label, input);
    const footer = el("div", "", "dialog-footer");
    const cancel = el("button", "取消", "button secondary");
    cancel.type = "button";
    const submit = el("button", "继续提交", "button primary");
    submit.type = "submit";
    submit.disabled = true;
    image.addEventListener("load", () => { submit.disabled = false; });
    footer.append(cancel, submit);
    form.append(header, body, footer);
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.append(form);
    let result = null;
    close.addEventListener("click", () => dialog.close());
    cancel.addEventListener("click", () => dialog.close());
    form.addEventListener("submit", event => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        error.textContent = "请输入图片中的验证码。";
        error.hidden = false;
        input.focus();
        return;
      }
      result = value;
      dialog.close();
    });
    dialog.addEventListener("close", () => {
      URL.revokeObjectURL(imageUrl);
      dialog.remove();
      resolve(result);
      requestAnimationFrame(() => {
        if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus({ preventScroll: true });
      });
    }, { once: true });
    (document.fullscreenElement || document.body).append(dialog);
    dialog.showModal();
    input.focus();
  });
}
