"""
Amazon retailer module — checks product availability by scraping the product page.

Amazon embeds structured availability data in the HTML. We look for:
  - "Add to Cart" / "Buy Now" → in stock
  - "Currently unavailable" / "Temporarily out of stock" → not available
  - "Available from these sellers" → third-party only (usually marked unavailable)

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
"""

import re
import requests
from .base import RetailerBase, StockResult

BASE = "https://www.amazon.com"

# Amazon is very bot-aware — use a realistic browser UA
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.amazon.com/",
    "DNT": "1",
}

IN_STOCK_SIGNALS = [
    "add to cart",
    "buy now",
    "in stock",
    "only",  # "only X left in stock"
]

OUT_OF_STOCK_SIGNALS = [
    "currently unavailable",
    "temporarily out of stock",
    "out of stock",
    "we don't know when or if this item will be back in stock",
    "sign up to be notified",
]

BLOCK_SIGNALS = [
    "robot check",
    "captcha",
    "sorry, we just need to make sure you",
    "automated access",
]


class Amazon(RetailerBase):
    """Checks if an Amazon product is available to add to cart."""
    default_poll_interval = 90  # Amazon rate-limits aggressively; don't hammer it

    def check_availability(self, item: dict) -> StockResult:
        asin = item.get("identifier", "")
        url = item.get("url") or f"{BASE}/dp/{asin}"
        name = item.get("name", f"Amazon product {asin}")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)

            if resp.status_code == 503:
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=None,
                    note="HTTP 503 — Amazon is rate-limiting (will retry next poll)",
                )

            if resp.status_code == 404:
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Product page not found (may not be live yet)",
                )

            if resp.status_code not in (200, 301, 302):
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=None,
                    note=f"HTTP {resp.status_code}",
                )

            html = resp.text
            html_lower = html.lower()

            # Bot/CAPTCHA detection
            if any(sig in html_lower for sig in BLOCK_SIGNALS):
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Amazon returned a bot-check page — not a real stock signal",
                )

            # Try to get the actual product title from the page
            title_match = re.search(
                r'id="productTitle"[^>]*>\s*([^<]{5,200})\s*<',
                html,
                re.IGNORECASE,
            )
            if title_match:
                name = title_match.group(1).strip()

            # Try to extract price
            price = None
            price_match = re.search(
                r'class="[^"]*a-price[^"]*"[^>]*>.*?<span[^>]*>\$([0-9,]+\.[0-9]{2})',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if price_match:
                try:
                    price = float(price_match.group(1).replace(",", ""))
                except ValueError:
                    pass

            # Check availability signals
            if any(sig in html_lower for sig in OUT_OF_STOCK_SIGNALS):
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=price,
                    note=None,
                )

            if any(sig in html_lower for sig in IN_STOCK_SIGNALS):
                return StockResult(
                    available=True,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=price,
                    note="In stock on Amazon — GO GO GO",
                )

            # Ambiguous — page loaded but we can't tell stock status
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note="Page loaded but availability unclear — verify manually",
            )

        except requests.exceptions.Timeout:
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note="Request timed out",
            )
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=f"Error: {e}",
            )
