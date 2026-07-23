const btn = document.getElementById("toggle");

function render(active) {
  btn.textContent = active ? "Stop" : "Start";
  btn.className = active ? "on" : "off";
}

chrome.runtime.sendMessage({ type: "get-status" }, (res) => render(res?.active));

btn.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "toggle" }, (res) => render(res?.active));
});
