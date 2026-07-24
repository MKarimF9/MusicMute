const SAMPLE_RATE = 44100;
const CHANNELS = 2;
const WS_URL = "ws://localhost:8765";

const PREBUFFER_S = 0.15; // cushion against WS/inference jitter, at the cost of a bit of latency

let audioContext = null;
let mediaStream = null;
let ws = null;
let nextPlaybackTime = null; // null until the first chunk arrives
let currentSettings = null; // set at the start of each startCapture() call

// Set to true for Stage-2 verification (capture/playback loopback, no server).
const LOOPBACK_NO_SERVER = false;

// Settings are loaded by background.js and passed in via the start-capture
// message; the server itself is also started by background.js (via the
// native messaging host) before that message is sent -- offscreen documents
// only have access to a restricted subset of extension APIs and can't use
// chrome.storage or chrome.runtime.connectNative directly.
async function startCapture(streamId, settings) {
  currentSettings = settings;

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
  });

  audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
  nextPlaybackTime = null; // set on first scheduled chunk, with a prebuffer cushion

  await audioContext.audioWorklet.addModule("worklet-capture.js");

  const source = audioContext.createMediaStreamSource(mediaStream);
  const captureNode = new AudioWorkletNode(audioContext, "capture-processor", {
    processorOptions: { blockSize: currentSettings.block_size },
  });

  // Tap only — captureNode's own output is muted (gain 0) before reaching
  // destination, so the original unprocessed audio is never audible. It's
  // still routed through a GainNode to destination because Web Audio only
  // pulls/processes nodes that are reachable from the destination; a fully
  // disconnected AudioWorkletNode would simply never run process().
  source.connect(captureNode);
  const muteNode = audioContext.createGain();
  muteNode.gain.value = 0;
  captureNode.connect(muteNode).connect(audioContext.destination);

  captureNode.port.onmessage = (event) => {
    const interleaved = event.data; // Float32Array, length BLOCK_SIZE * CHANNELS

    if (LOOPBACK_NO_SERVER) {
      schedulePlayback(interleaved);
      return;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(interleaved.buffer);
    }
  };

  if (!LOOPBACK_NO_SERVER) {
    connectWebSocket();
  }
}

function connectWebSocket() {
  ws = new WebSocket(WS_URL);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    ws.send(JSON.stringify({
      sample_rate: SAMPLE_RATE,
      channels: CHANNELS,
      ...currentSettings, // block_size, max_buffer_size, back, overlap, music_threshold_on/off
    }));
  };

  ws.onmessage = (event) => {
    const interleaved = new Float32Array(event.data);
    schedulePlayback(interleaved);
  };

  ws.onerror = (err) => console.error("MusicMute WS error", err);

  ws.onclose = () => {
    // A dropped/failed connection must release the tab capture, otherwise a
    // retry hits "Cannot capture a tab with an active stream".
    console.warn("MusicMute WS closed — stopping capture");
    stopCapture();
    chrome.runtime.sendMessage({ type: "capture-stopped" }).catch(() => {});
  };
}

function schedulePlayback(interleaved) {
  const frames = interleaved.length / CHANNELS;
  const buffer = audioContext.createBuffer(CHANNELS, frames, SAMPLE_RATE);
  const left = buffer.getChannelData(0);
  const right = buffer.getChannelData(1);
  for (let i = 0; i < frames; i++) {
    left[i] = interleaved[i * 2];
    right[i] = interleaved[i * 2 + 1];
  }

  const src = audioContext.createBufferSource();
  src.buffer = buffer;
  src.connect(audioContext.destination); // only node allowed to reach speakers

  const now = audioContext.currentTime;
  if (nextPlaybackTime === null || nextPlaybackTime < now) {
    // First chunk, or we fell behind (e.g. after a pause/stall) — resync
    // with a fresh prebuffer cushion instead of racing to catch up.
    nextPlaybackTime = now + PREBUFFER_S;
  }
  src.start(nextPlaybackTime);
  nextPlaybackTime += frames / SAMPLE_RATE;
}

function stopCapture() {
  if (ws) {
    ws.close();
    ws = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((t) => t.stop());
    mediaStream = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "start-capture") {
    startCapture(message.streamId, message.settings)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
        console.error("MusicMute: startCapture failed", err);
        stopCapture();
        sendResponse({ ok: false, error: String(err) });
      });
    return true; // async response
  }
  if (message.type === "stop-capture") {
    stopCapture();
    sendResponse({ ok: true });
  }
  if (message.type === "flag") {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "flag" }));
    } else {
      console.warn("MusicMute: flag requested but not connected to server");
    }
  }
});
