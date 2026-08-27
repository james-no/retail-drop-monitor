"""
Amazon retailer module — uses a headless browser to bypass bot detection.

Amazon embeds availability data inside the #availability div. We load the
full rendered page via Playwright so JS executes and the real content appears,
then extract the text from that div.

How to find the ASIN:
  - Open the product page on amazon.com
  - The URL contains /dp/XXXXXXXXXX — that 10-char string is the ASIN
  - Example: amazon.com/dp/B0XXXXXXXX → ASIN is B0XXXXXXXX

Watchlist entry format:
  {
    "name": "Pokemon TCG 30th Celebration Ultra Premium Collection",
    "retailer": "amazon",
    "identifier": "B0XXXXXXXX",
    "url": "https://www.amazon.com/dp/B0XXXXXXXX"
  }

Optional per-item filters:
  "max_price": 100           -- skip if price exceeds this
  "amazon_direct_only": true -- skip if not sold by Amazon or Pokemon Company
"""

import re
import time

from .base import RetailerBase, StockResult

BASE = "https://www.amazon.com"

IN_STOCK_SIGNALS = [
    "in stock",
    "add to cart",
    "buy now",
    "pre-order now",
    "preorder now",
    "order now",
    "ships on",
    "ships from and sold by amazon",
    "available for pre-order",
]

OUT_OF_STOCK_SIGNALS = [
    "currently unavailable",
    "temporarily out of stock",
    "out of stock",
    "we don't know when or if this item will be back in stock",
    "sign up to be notified",
    "available from these sellers",
    "see all buying options",
    "new & used",
]

BLOCK_SIGNALS = [
    "robot check",
    "captcha",
    "sorry, we just need to make sure you",
    "automated access",
    "to discuss automated access",
]


class Amazon(RetailerBase):
    """Checks Amazon product availability using a headless browser."""
    default_poll_interval = 90

    def __init__(self):
        # Per-ASIN cooldown: after a bot-check, skip polls for 5 minutes
        self._bot_blocked_until: dict = {}

    def check_availability(self, item: dict) -> StockResult:
        asin = item.get("identifier", "")
        url = item.get("url") or f"{BASE}/dp/{asin}"
        name = item.get("name", f"Amazon product {asin}")

        # Skip if still in bot-check cooldown
        if time.time() < self._bot_blocked_until.get(asin, 0):
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=None,  # silent during cooldown
            )

        try:
            from .playwright_base import fetch_page
            from playwright.sync_api import TimeoutError as PWTimeout
        except ImportError:
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note="Playwright not installed — run: pip install playwright && playwright install chromium",
            )

        try:
            html = fetch_page(url, wait_until="domcontentloaded", timeout_ms=30_000)
        except Exception as e:
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=f"Page load error: {e}",
            )

        html_lower = html.lower()

        # Bot/CAPTCHA detection — set 5-minute cooldown for this ASIN
        if any(sig in html_lower for sig in BLOCK_SIGNALS):
            self._bot_blocked_until[asin] = time.time() + 300
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note="Amazon bot-check — cooling down 5 min",
            )

        # Extract actual product title
        title_match = re.search(
            r'id="productTitle"[^>]*>\s*([^<]{5,200})\s*<',
            html, re.IGNORECASE,
        )
        if title_match:
            name = title_match.group(1).strip()

        # Extract price
        price = None
        price_match = re.search(
            r'class="[^"]*a-price[^"]*"[^>]*>.*?<span[^>]*>\$([0-9,]+\.[0-9]{2})',
            html, re.IGNORECASE | re.DOTALL,
        )
        if price_match:
            try:
                price = float(price_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # Only trust the #availability div — never scan the full page
        avail_match = re.search(
            r'id="availability"[^>]*>(.*?)</div>',
            html, re.IGNORECASE | re.DOTALL,
        )
        if not avail_match:
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=None,
            )

        avail_text = re.sub(r'<[^>]+>', ' ', avail_match.group(1)).lower().strip()

        # Explicit out of stock
        if any(sig in avail_text for sig in OUT_OF_STOCK_SIGNALS):
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=price,
                note=None,
            )

        # In-stock or preorder signal
        matched = next((sig for sig in IN_STOCK_SIGNALS if sig in avail_text), None)
        if matched:
            is_preorder = "pre" in matched or "ships on" in matched or "order" in matched
            note = "Pre-order is LIVE on Amazon — GO NOW" if is_preorder else "In stock on Amazon — GO GO GO"

            # Seller filter
            amazon_direct_only = item.get("amazon_direct_only", False)
            if amazon_direct_only:
                merchant_match = re.search(
                    r'id="merchant-info"[^>]*>(.*?)</div>',
                    html, re.IGNORECASE | re.DOTALL,
                )
                merchant_text = ""
                if merchant_match:
                    merchant_text = re.sub(r'<[^>]+>', ' ', merchant_match.group(1)).lower().strip()
                sold_by_amazon = any(s in merchant_text for s in [
                    "amazon.com", "amazon", "pokemon", "the pokemon company"
                ])
                if merchant_text and not sold_by_amazon:
                    return StockResult(
                        available=False,
                        retailer="Amazon",
                        product_name=name,
                        url=url,
                        price=price,
                        note=f"Sold by third party ({merchant_text[:60]}) — skipping",
                    )

            # Price cap filter
            max_price = item.get("max_price")
            if max_price and price and price > max_price:
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=price,
                    note=f"Price ${price:.2f} exceeds limit ${max_price:.2f} — skipping",
                )

            return StockResult(
                available=True,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=price,
                note=note,
            )

        return StockResult(
            available=False,
            retailer="Amazon",
            product_name=name,
            url=url,
            price=None,
            note=None,
        )
