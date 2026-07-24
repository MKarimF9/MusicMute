// MV3 service worker: cannot touch media/Web Audio APIs directly, so it just
// brokers a tabCapture stream id to the offscreen document, which does the work.

const OFFSCREEN_URL = "offscreen.html";
let activeTabId = null;

async function ensureOffscreenDocument() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
  });
  if (existing.length > 0) return;

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ["USER_MEDIA"],
    justification: "Capture and process the active tab's audio for vocal isolation.",
  });
}

async function start(tab) {
  await ensureOffscreenDocument();

  const streamId = await chrome.tabCapture.getMediaStreamId({
    targetTabId: tab.id,
  });

  // Don't mark active until the offscreen document confirms capture actually
  // started — getUserMedia can still fail asynchronously after this point.
  const response = await chrome.runtime.sendMessage({ type: "start-capture", streamId });
  if (!response || !response.ok) {
    throw new Error(response?.error || "offscreen document failed to start capture");
  }

  activeTabId = tab.id;
  chrome.action.setBadgeText({ text: "ON" });
  chrome.action.setBadgeBackgroundColor({ color: "#2ecc71" });
}

async function stop() {
  chrome.runtime.sendMessage({ type: "stop-capture" }).catch(() => {});
  chrome.action.setBadgeText({ text: "" });
  activeTabId = null;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "toggle") {
    (async () => {
      if (activeTabId) {
        await stop();
      } else {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab) {
          try {
            await start(tab);
          } catch (err) {
            console.error("MusicMute: failed to start capture", err);
            activeTabId = null;
            chrome.action.setBadgeText({ text: "" });
            sendResponse({ active: false, error: String(err) });
            return;
          }
        }
      }
      sendResponse({ active: !!activeTabId });
    })();
    return true;
  }
  if (message.type === "get-status") {
    sendResponse({ active: !!activeTabId });
  }
  if (message.type === "capture-stopped") {
    // Offscreen doc released capture on its own (e.g. WS dropped) — sync badge/state.
    activeTabId = null;
    chrome.action.setBadgeText({ text: "" });
  }
  if (message.type === "flag") {
    // No-op here — handled directly by offscreen.js, which owns the WebSocket.
    // Listed explicitly so it's clear this isn't an unhandled message type.
    return false;
  }
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === activeTabId) stop();
});
