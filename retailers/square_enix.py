"""
Square Enix Store (na.store.square-enix-games.com) retailer module.

This is a BigCommerce storefront. There's no public JSON product API like
Shopify's, so we load the product page HTML directly and read the
`og:availability` meta tag, which BigCommerce sets reliably based on the
product's actual stock status. As a fallback we also check for visible
"SOLD OUT" / "CURRENTLY UNAVAILABLE" text vs. an active pre-order/add-to-cart
button.

How to add a product:
  - Go to the product page on na.store.square-enix-games.com
  - Use the full product page URL as both `identifier` and `url`

Watchlist entry format:
  {
    "name": "Final Fantasy Resonance Collector's Edition Goods Box",
    "retailer": "square_enix",
    "identifier": "final-fantasy-resonance-collector_s-edition-goods-box",
    "url": "https://na.store.square-enix-games.com/final-fantasy-resonance-collector_s-edition-goods-box"
  }
"""

import re
import requests
from .base import RetailerBase, StockResult

BASE = "https://na.store.square-enix-games.com"

HEADERS = {
    **RetailerBase.BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/",
}

# og:availability values that mean "not buyable right now"
UNAVAILABLE_AVAILABILITY = {"out of stock", "outofstock", "soldout", "sold out"}

# Visible page text signals (checked in this priority order)
UNAVAILABLE_TEXT_SIGNALS = ["currently unavailable", "out of stock", "sold out", "notify me when"]
AVAILABLE_TEXT_SIGNALS = ["pre-order now", "add to cart", "buy now"]


class SquareEnix(RetailerBase):
    """Checks a Square Enix Store (BigCommerce) product page for stock."""

    default_poll_interval = 60

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)

            if resp.status_code in (403, 429, 503):
                return StockResult(
                    available=False,
                    retailer="Square Enix Store",
                    product_name=name,
                    url=url,
                    price=None,
                    note=f"HTTP {resp.status_code} — likely rate-limited/blocked, not a real stock signal",
                )

            resp.raise_for_status()
            html = resp.text
            html_lower = html.lower()

            # Most reliable: og:availability meta tag (attribute order can vary)
            availability = None
            match = re.search(
                r'<meta[^>]+(?:property|name)=["\']og:availability["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:availability["\']',
                    html, re.IGNORECASE,
                )
            if match:
                availability = match.group(1).strip().lower()

            # Price, if present
            price = None
            price_match = re.search(
                r'<meta[^>]+(?:property|name)=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE,
            )
            if price_match:
                try:
                    price = float(price_match.group(1))
                except ValueError:
                    pass

            text_unavailable = any(sig in html_lower for sig in UNAVAILABLE_TEXT_SIGNALS)
            text_available = any(sig in html_lower for sig in AVAILABLE_TEXT_SIGNALS)

            if availability is not None and availability in UNAVAILABLE_AVAILABILITY:
                available = False
                note = f"Out of stock (availability: {availability})"
            elif text_unavailable:
                available = False
                note = "Page shows sold out / currently unavailable / notify me"
            elif availability is not None:
                available = True
                note = f"In stock — GO GO GO (availability: {availability})"
            elif text_available:
                available = True
                note = "In stock — GO GO GO (pre-order/add-to-cart button active)"
            else:
                available = False
                note = "Could not determine stock status — page layout may have changed, verify manually"

            return StockResult(
                available=available,
                retailer="Square Enix Store",
                product_name=name,
                url=url,
                price=price,
                note=note,
            )

        except requests.exceptions.Timeout:
            return StockResult(
                available=False,
                retailer="Square Enix Store",
                product_name=name,
                url=url,
                price=None,
                note="Request timed out",
            )
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Square Enix Store",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )
