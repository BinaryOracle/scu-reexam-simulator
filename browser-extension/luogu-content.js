chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "SCU_LUOGU_PING") return false;
  const context = document.querySelector("#lentille-context");
  try {
    const data = JSON.parse(context?.textContent || "{}");
    sendResponse(data.user ? { loggedIn: true } : { loggedIn: false });
  } catch { sendResponse({ loggedIn: false }); }
  return false;
});
