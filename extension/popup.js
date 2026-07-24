const btn = document.getElementById("toggle");
const flagBtn = document.getElementById("flag");
const statusEl = document.getElementById("status");
const stopServerBtn = document.getElementById("stop-server");
const resetBtn = document.getElementById("reset-defaults");
const warningEl = document.getElementById("settings-warning");

const SETTINGS_FIELDS = [
  "block_size", "max_buffer_size", "back", "overlap",
  "music_threshold_on", "music_threshold_off",
];
const modeSelect = document.getElementById("force_mode");

function render(active) {
  btn.textContent = active ? "Stop" : "Start";
  btn.className = active ? "on" : "off";
}

function renderSettings(settings) {
  for (const field of SETTINGS_FIELDS) {
    document.getElementById(field).value = settings[field];
    document.getElementById(`val-${field}`).textContent = settings[field];
  }
  modeSelect.value = settings.force_mode;
  validateSettings(settings);
}

function readSettingsFromInputs() {
  const settings = { force_mode: modeSelect.value };
  for (const field of SETTINGS_FIELDS) {
    const raw = document.getElementById(field).value;
    settings[field] = field.startsWith("music_threshold") ? parseFloat(raw) : parseInt(raw, 10);
  }
  return settings;
}

function validateSettings(settings) {
  const error = settingsInvariantError(settings);
  warningEl.style.display = error ? "block" : "none";
  warningEl.textContent = error || "";
  return !error;
}

async function onSliderChange() {
  const settings = readSettingsFromInputs();
  for (const field of SETTINGS_FIELDS) {
    document.getElementById(`val-${field}`).textContent = settings[field];
  }
  validateSettings(settings);
  await saveSettings(settings);
}

(async () => {
  const settings = await loadSettings();
  renderSettings(settings);
})();

for (const field of SETTINGS_FIELDS) {
  const input = document.getElementById(field);
  input.addEventListener("input", () => {
    document.getElementById(`val-${field}`).textContent =
      field.startsWith("music_threshold") ? parseFloat(input.value) : parseInt(input.value, 10);
  });
  input.addEventListener("change", onSliderChange);
}

resetBtn.addEventListener("click", async () => {
  await saveSettings(DEFAULT_SETTINGS);
  renderSettings(DEFAULT_SETTINGS);
});

modeSelect.addEventListener("change", async () => {
  await saveSettings(readSettingsFromInputs());
});

chrome.runtime.sendMessage({ type: "get-status" }, (res) => render(res?.active));

btn.addEventListener("click", () => {
  statusEl.textContent = "Starting…";
  chrome.runtime.sendMessage({ type: "toggle" }, (res) => {
    render(res?.active);
    statusEl.textContent = res?.error ? res.error : "";
  });
});

flagBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "flag" });
  const original = flagBtn.textContent;
  flagBtn.textContent = "Flagged!";
  setTimeout(() => { flagBtn.textContent = original; }, 1200);
});

stopServerBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "stop-server" });
  const original = stopServerBtn.textContent;
  stopServerBtn.textContent = "Stopped";
  setTimeout(() => { stopServerBtn.textContent = original; }, 1200);
});
