(() => {
  if (window.__scuLuoguBridgeInstalled) return;
  window.__scuLuoguBridgeInstalled = true;
  const appOrigin = location.origin;
  window.addEventListener("message", async event => {
    if (event.source !== window || event.origin !== appOrigin || event.data?.source !== "scu-luogu-bridge") return;
    const { type, requestId, payload } = event.data;
    if (!requestId || !["PING", "SUBMIT"].includes(type)) return;
    try {
      const result = await chrome.runtime.sendMessage({ type: "SCU_BRIDGE_REQUEST", request: requestId, action: type, payload });
      if (result?.error) {
        window.postMessage({ source: "scu-luogu-bridge-result", requestId, error: result.error }, appOrigin);
        return;
      }
      window.postMessage({ source: "scu-luogu-bridge-result", requestId, payload: result }, appOrigin);
    } catch (error) {
      window.postMessage({ source: "scu-luogu-bridge-result", requestId, error: error.message }, appOrigin);
    }
  });
  chrome.runtime.onMessage.addListener(message => {
    if (message?.type !== "SCU_LUOGU_STATUS") return;
    window.dispatchEvent(new CustomEvent("scu-luogu-status", { detail: message.payload }));
  });
})();
