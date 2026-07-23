const btn = document.getElementById("toggle");
const flagBtn = document.getElementById("flag");

function render(active) {
  btn.textContent = active ? "Stop" : "Start";
  btn.className = active ? "on" : "off";
}

chrome.runtime.sendMessage({ type: "get-status" }, (res) => render(res?.active));

btn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "toggle" }, (res) => render(res?.active));
});

flagBtn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "flag" });
  const original = flagBtn.textContent;
  flagBtn.textContent = "Flagged!";
  setTimeout(() => { flagBtn.textContent = original; }, 1200);
});
