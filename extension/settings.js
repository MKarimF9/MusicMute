// Shared default values + chrome.storage helpers for the tunable quality/
// latency settings, used by both popup.js (the sliders) and offscreen.js
// (which reads the current values to include in the WS handshake).
//
// Keep DEFAULT_SETTINGS in sync with server/ws_server.py's module constants.

const DEFAULT_SETTINGS = {
  block_size: 2048,
  max_buffer_size: 16000,
  back: 1024,
  overlap: 512,
  music_threshold_on: 0.35,
  music_threshold_off: 0.20,
  // "auto" (detector decides) / "passthrough" (always original audio) /
  // "filter" (always vocals-only) -- an escape hatch for content the
  // detector gets wrong, e.g. reverb-heavy a cappella vocals/nasheed/
  // recitation misread as having accompaniment.
  force_mode: "auto",
};

const SETTINGS_STORAGE_KEY = "musicmute_settings";

function loadSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get([SETTINGS_STORAGE_KEY], (result) => {
      resolve({ ...DEFAULT_SETTINGS, ...(result[SETTINGS_STORAGE_KEY] || {}) });
    });
  });
}

function saveSettings(settings) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [SETTINGS_STORAGE_KEY]: settings }, resolve);
  });
}

function settingsInvariantError(settings) {
  const required = settings.block_size + settings.back + settings.overlap;
  if (settings.max_buffer_size < required) {
    return `Max Buffer (${settings.max_buffer_size}) must be >= Block Size + Back + Overlap (${required})`;
  }
  return null;
}
