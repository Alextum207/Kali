// TODO: keep in sync with background.js BACKEND_BASE_URL.
const BACKEND_BASE_URL = "http://localhost:8000";

const STATUS_KEY = "kaliScanStatus";

const scanBtn = document.getElementById("scanBtn");
const statusEl = document.getElementById("status");
const resultLink = document.getElementById("resultLink");
const knopfAnim = document.getElementById("knopfAnim");

function render(status) {
  if (!status) {
    statusEl.textContent = "";
    resultLink.style.display = "none";
    scanBtn.disabled = false;
    return;
  }

  scanBtn.disabled = status.state === "running";
  resultLink.style.display = "none";

  switch (status.state) {
    case "running":
      statusEl.textContent = `Scan läuft: ${status.url}`;
      break;
    case "done":
      statusEl.textContent = `Scan gestartet für: ${status.url}`;
      if (status.scanId != null) {
        resultLink.href = `${BACKEND_BASE_URL}/scans/${status.scanId}`;
        resultLink.style.display = "block";
      }
      break;
    case "captcha_required":
      statusEl.textContent = `Captcha auf ${status.captchaUrl} erkannt. Bitte dort lösen, dann nochmal auf "Scan starten" klicken.`;
      break;
    case "error":
      statusEl.textContent = `Fehler: ${status.error}`;
      break;
    default:
      statusEl.textContent = "";
  }
}

// Show whatever status was last recorded (survives popup close/reopen).
chrome.storage.local.get(STATUS_KEY).then((data) => render(data[STATUS_KEY]));

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes[STATUS_KEY]) {
    render(changes[STATUS_KEY].newValue);
  }
});

scanBtn.addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) {
    statusEl.textContent = "Keine aktive Tab-URL gefunden.";
    return;
  }
  scanBtn.disabled = true;
  knopfAnim.style.display = "block";
  knopfAnim.currentTime = 0;
  knopfAnim.play();
  chrome.runtime.sendMessage({ type: "START_SCAN", url: tab.url });
});

knopfAnim.addEventListener("ended", () => {
  knopfAnim.style.display = "none";
});
