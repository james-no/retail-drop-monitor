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
    # Third-party only — Amazon itself doesn't have stock
    "available from these sellers",
    "see all buying options",
    "new & used",
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

    def __init__(self):
        # Per-ASIN backoff: when bot-checked, skip polls for 5 minutes
        self._bot_blocked_until: dict = {}

    def check_availability(self, item: dict) -> StockResult:
        import time
        asin = item.get("identifier", "")
        url = item.get("url") or f"{BASE}/dp/{asin}"
        name = item.get("name", f"Amazon product {asin}")

        # Skip if this ASIN is still in its bot-check cooldown
        if time.time() < self._bot_blocked_until.get(asin, 0):
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=None,  # silent skip during cooldown
            )

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

            # Bot/CAPTCHA detection — set a 5-minute cooldown for this ASIN
            if any(sig in html_lower for sig in BLOCK_SIGNALS):
                self._bot_blocked_until[asin] = time.time() + 300
                return StockResult(
                    available=False,
                    retailer="Amazon",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Amazon returned a bot-check page — cooling down 5 min",
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

            # Only trust the #availability buy box div.
            # Never scan the full page — "add to cart" / "in stock" appear
            # everywhere in carousels, descriptions, and recommendations.
            avail_match = re.search(
                r'id="availability"[^>]*>(.*?)</div>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if avail_match:
                avail_block = avail_match.group(1).lower()
                # Strip HTML tags to get plain text
                avail_text = re.sub(r'<[^>]+>', ' ', avail_block).strip()
                # Explicit unavailable — stop here
                if any(sig in avail_text for sig in OUT_OF_STOCK_SIGNALS):
                    return StockResult(
                        available=False,
                        retailer="Amazon",
                        product_name=name,
                        url=url,
                        price=price,
                        note=None,
                    )
                # Check all in-stock signals (covers preorders, buy now, ships on, etc.)
                matched = next((sig for sig in IN_STOCK_SIGNALS if sig in avail_text), None)
                if matched:
                    note = "Pre-order is LIVE on Amazon — GO NOW" if "pre" in matched or "ships on" in matched or "order" in matched else "In stock on Amazon — GO GO GO"

                    # Check if item requires Amazon/Pokemon direct (not marketplace)
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
                        # If merchant info is present and not Amazon/Pokemon, skip
                        if merchant_text and not sold_by_amazon:
                            return StockResult(
                                available=False,
                                retailer="Amazon",
                                product_name=name,
                                url=url,
                                price=price,
                                note=f"In stock but sold by third party ({merchant_text[:60]}) — skipping",
                            )

                    # Price cap check
                    max_price = item.get("max_price")
                    if max_price and price and price > max_price:
                        return StockResult(
                            available=False,
                            retailer="Amazon",
                            product_name=name,
                            url=url,
                            price=price,
                            note=f"In stock but price ${price:.2f} exceeds limit ${max_price:.2f} — skipping",
                        )

                    return StockResult(
                        available=True,
                        retailer="Amazon",
                        product_name=name,
                        url=url,
                        price=price,
                        note=note,
                    )

            # No #availability div found or status unclear — treat as unavailable.
            return StockResult(
                available=False,
                retailer="Amazon",
                product_name=name,
                url=url,
                price=None,
                note=None,
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
