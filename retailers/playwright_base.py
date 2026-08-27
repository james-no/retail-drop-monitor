"""
Shared headless Chromium browser for retailer checks that need JavaScript.

Uses a single persistent browser process with per-request isolated contexts
(separate cookies/storage per check) so checks don't cross-contaminate.
Thread-safe — multiple retailer threads can call fetch_page() concurrently.
"""

import threading
from playwright.sync_api import sync_playwright, Browser, BrowserContext, TimeoutError as PWTimeout

_lock = threading.Lock()
_pw = None
_browser: Browser | None = None

# Minimal stealth: hide the webdriver flag that Amazon/Best Buy check for
STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    window.chrome = { runtime: {} };
"""

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def get_browser() -> Browser:
    """Return the shared browser, launching it if needed."""
    global _pw, _browser
    with _lock:
        if _browser is None or not _browser.is_connected():
            if _pw is None:
                _pw = sync_playwright().start()
            _browser = _pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-infobars",
                ],
            )
    return _browser


def new_context() -> BrowserContext:
    """Create a fresh isolated browser context with stealth headers."""
    ctx = get_browser().new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
        timezone_id="America/Los_Angeles",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script(STEALTH_SCRIPT)
    return ctx


def fetch_page(url: str, wait_until: str = "domcontentloaded", timeout_ms: int = 30_000) -> str:
    """
    Load *url* in a fresh browser context, wait for the page to settle,
    and return the fully-rendered HTML.

    Raises playwright.sync_api.TimeoutError on timeout.
    Raises RuntimeError on navigation failure (4xx/5xx).
    Closes the page and context before returning.
    """
    ctx = new_context()
    page = ctx.new_page()
    try:
        resp = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if resp and resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}")
        html = page.content()
        return html
    finally:
        page.close()
        ctx.close()


def fetch_element_text(url: str, selector: str, timeout_ms: int = 30_000) -> tuple[str, str]:
    """
    Load *url* and wait for *selector* to appear.
    Returns (element_text, full_page_html).
    Raises TimeoutError if selector never appears within timeout_ms.
    """
    ctx = new_context()
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector(selector, timeout=timeout_ms)
        text = page.locator(selector).first.inner_text(timeout=5_000)
        html = page.content()
        return text, html
    finally:
        page.close()
        ctx.close()
