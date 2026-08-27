import http.server
import pathlib
import socketserver
import threading
import urllib.parse

import pytest
from playwright.async_api import async_playwright


ROOT = pathlib.Path(__file__).parent.parent
EXTENSION_ROOT = ROOT / "vendor" / "pattern-highlighter" / "chrome"


def _page_html(kind: str) -> str:
    if kind == "reset":
        body = """
        <main>
          <h1>Flash sale</h1>
          <p>Deal price: 19,99 €</p>
          <button>Buy now</button>
          <div id="countdown">02:00</div>
        </main>
        <script>
          let target = Date.now() + 120000;
          function tick() {
            let remaining = target - Date.now();
            if (remaining <= 0) {
              target = Date.now() + 120000;
              remaining = target - Date.now();
            }
            const seconds = Math.max(0, Math.floor(remaining / 1000));
            document.getElementById("countdown").textContent =
              String(Math.floor(seconds / 60)).padStart(2, "0") + ":" +
              String(seconds % 60).padStart(2, "0");
          }
          tick();
          setInterval(tick, 1000);
        </script>
        """
    elif kind == "expires":
        body = """
        <main>
          <h1>Flash sale</h1>
          <p>Deal price: 19,99 €</p>
          <button>Buy now</button>
          <div id="countdown">02:00</div>
        </main>
        <script>
          const target = Date.now() + 120000;
          function tick() {
            const remaining = target - Date.now();
            if (remaining <= 0) {
              document.getElementById("countdown").textContent = "Abgelaufen";
              return;
            }
            document.getElementById("countdown").textContent = "02:00";
          }
          tick();
          setInterval(tick, 1000);
        </script>
        """
    elif kind == "removed":
        body = """
        <main>
          <h1>Flash sale</h1>
          <p>Deal price: 19,99 €</p>
          <button>Buy now</button>
          <div id="countdown">02:00</div>
        </main>
        <script>
          const target = Date.now() + 120000;
          function tick() {
            if (Date.now() >= target) {
              document.querySelector("main").innerHTML = "<h1>Sale ended</h1><p>Not available anymore.</p>";
              return;
            }
            document.getElementById("countdown").textContent = "02:00";
          }
          tick();
          setInterval(tick, 1000);
        </script>
        """
    else:
        raise AssertionError(f"unknown page kind: {kind}")

    return f"""<!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <script src="/extension/scripts/countdown-clock-shim.js"></script>
    </head>
    <body>{body}</body>
    </html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/extension/"):
            relative = path.removeprefix("/extension/")
            file_path = EXTENSION_ROOT / relative
            if not file_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            content_type = "application/javascript" if file_path.suffix == ".js" else "application/json"
            payload = file_path.read_bytes()
            if relative == "data/consent-rules.json":
                payload = b"[]"
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.end_headers()
            self.wfile.write(payload)
            return

        kind = path.strip("/") or "reset"
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_page_html(kind).encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A003 - BaseHTTPRequestHandler API
        return


@pytest.fixture
def local_extension_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


async def _run_extension_page(origin: str, kind: str) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page()
        await page.add_init_script(
            """
            window.__kaliMessages = [];
            window.chrome = {
              i18n: {
                getMessage: (key, args) => key === "infoNumberPatternsFound"
                  ? `${args && args[0] || "0"} pattern(s) detected.`
                  : key
              },
              runtime: {
                getURL: (path) => `${location.origin}/extension/${path}`,
                sendMessage: (message, callback) => {
                  if (message && message.action === "getActivationState") {
                    return Promise.resolve({ isEnabled: true });
                  }
                  window.__kaliMessages.push(message);
                  window.__kaliLastResults = message;
                  if (typeof callback === "function") {
                    setTimeout(() => callback({ success: true }), 0);
                  }
                  return Promise.resolve({ success: true });
                }
              }
            };
            """
        )
        await page.goto(f"{origin}/{kind}", wait_until="domcontentloaded")
        await page.add_script_tag(path=str(EXTENSION_ROOT / "scripts" / "content.js"))
        await page.wait_for_function("window.__kaliLastResults !== undefined", timeout=10000)
        count = await page.locator(".__ph__countdown").count()
        await browser.close()
        return count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_count"),
    [
        ("reset", 1),
        ("expires", 0),
        ("removed", 0),
    ],
)
async def test_extension_only_marks_clock_verified_countdowns(local_extension_server, kind, expected_count):
    assert await _run_extension_page(local_extension_server, kind) == expected_count
