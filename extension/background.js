// Kali extension service worker.
//
// Flow: popup sends START_SCAN with the active tab's URL -> we read that
// site's cookies -> hand both off to the backend -> track status in
// chrome.storage.local so the popup can show progress even if it was
// closed and reopened mid-scan.

// TODO: point this at the real backend once deployed (env-specific).
const BACKEND_BASE_URL = "http://localhost:8000";

const STATUS_KEY = "kaliScanStatus";

async function setStatus(status) {
  await chrome.storage.local.set({ [STATUS_KEY]: status });
}

async function startScan(url) {
  await setStatus({ state: "running", url, error: null, scanId: null });

  let cookies;
  try {
    cookies = await chrome.cookies.getAll({ url });
  } catch (err) {
    await setStatus({ state: "error", url, error: String(err), scanId: null });
    return;
  }

  try {
    // Server injects these cookies into a Playwright BrowserContext via
    // context.add_cookies(...) before running run_site_scan() — see
    // docs/superpowers/specs/2026-08-20-chrome-extension-cookie-handoff-design.md.
    // Returns { scan_id } on success, or 409 { detail: { error:
    // "captcha_required", url } } if the start page itself is captcha-gated
    // (only the start page is checked, not pages deeper in the crawl — a
    // headless mid-crawl captcha can't be solved by the user anyway).
    const response = await fetch(`${BACKEND_BASE_URL}/scans/extension`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, cookies }),
    });

    if (response.status === 409) {
      const data = await response.json();
      if (data.detail?.error === "captcha_required") {
        await setStatus({ state: "captcha_required", url, captchaUrl: data.detail.url, error: null, scanId: null });
        return;
      }
    }
    if (!response.ok) {
      throw new Error(`Backend antwortete mit Status ${response.status}`);
    }

    const data = await response.json();
    await setStatus({ state: "done", url, error: null, scanId: data.scan_id ?? null });
  } catch (err) {
    await setStatus({ state: "error", url, error: String(err), scanId: null });
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_SCAN") {
    startScan(message.url).then(() => sendResponse({ ok: true }));
    return true; // keep the message channel open for the async response
  }
  return false;
});
