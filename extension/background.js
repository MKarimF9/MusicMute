// MV3 service worker: cannot touch media/Web Audio APIs directly, so it just
// brokers a tabCapture stream id to the offscreen document, which does the work.
//
// Settings are also loaded here (not in offscreen.js) and passed along with
// the stream id -- offscreen documents don't have access to chrome.storage,
// only a subset of extension APIs.
importScripts("settings.js");

const OFFSCREEN_URL = "offscreen.html";
let activeTabId = null;
// Lazily connected; lives in the service worker because offscreen documents
// can't use chrome.runtime.connectNative. Note: MV3 can terminate an idle
// service worker (~30s with no activity), which would drop this port and
// (via host.py's stdin-EOF cleanup) stop the server even mid-capture -- an
// open port's own activity should reset that idle timer in practice, but if
// this turns out to be a real problem, a chrome.alarms-based keepalive is
// the fix.
let nativePort = null;

const NATIVE_HOST_NAME = "com.musicmute.host";
const NATIVE_START_TIMEOUT_MS = 130000; // generous: first-run model download can be slow

// Ask the native messaging host to make sure the server is running. Resolves
// once it's up (or already was); resolves "not auto-launched" (not rejects)
// if the host isn't installed at all (one-time setup never run), so callers
// fall back to just attempting the WebSocket connection directly, same as
// before this feature existed. The host only spawns the process -- quality/
// latency settings are applied separately, via the WS handshake.
function ensureServerRunning() {
  return new Promise((resolve) => {
    let port;
    try {
      port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
    } catch (err) {
      console.warn("MusicMute: native host unavailable, skipping auto-launch", err);
      resolve({ ok: true, autoLaunch: false });
      return;
    }

    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => finish({ ok: true, autoLaunch: false }), NATIVE_START_TIMEOUT_MS);

    port.onMessage.addListener((msg) => {
      if (msg.state === "running") {
        finish({ ok: true, autoLaunch: true });
      } else if (msg.state === "error") {
        finish({ ok: false, autoLaunch: true, error: msg.message });
      }
    });
    port.onDisconnect.addListener(() => {
      // Native host manifest missing, or host crashed before replying --
      // fall back to assuming a manually-launched server might be running.
      if (chrome.runtime.lastError) {
        console.warn("MusicMute: native host disconnected", chrome.runtime.lastError.message);
      }
      nativePort = null;
      finish({ ok: true, autoLaunch: false });
    });

    nativePort = port;
    port.postMessage({ type: "start" });
  });
}

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

  const startResult = await ensureServerRunning();
  if (!startResult.ok) {
    throw new Error(`Server failed to start: ${startResult.error}`);
  }

  const streamId = await chrome.tabCapture.getMediaStreamId({
    targetTabId: tab.id,
  });
  const settings = await loadSettings();

  // Don't mark active until the offscreen document confirms capture actually
  // started — getUserMedia can still fail asynchronously after this point.
  const response = await chrome.runtime.sendMessage({ type: "start-capture", streamId, settings });
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
    // No-op here — handled directly by offscreen.js, which owns the
    // WebSocket. Listed explicitly so it's clear this isn't an unhandled
    // message type.
    return false;
  }
  if (message.type === "stop-server") {
    // Explicit "reclaim GPU/RAM now" action from the popup, independent of
    // whether audio capture is currently running.
    if (nativePort) {
      nativePort.postMessage({ type: "stop" });
    } else {
      console.warn("MusicMute: stop-server requested but no native host connection");
    }
    return false;
  }
  return true;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === activeTabId) stop();
});
