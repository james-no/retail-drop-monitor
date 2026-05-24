"""
Walmart retailer module.

Walmart server-side renders product pages, meaning the availability data is
embedded directly in the HTML as a JSON blob inside a <script id="__NEXT_DATA__">
tag. We extract and parse that JSON — no JavaScript execution needed.

This is more reliable than scraping button text because:
  - The JSON data is structured and predictable
  - It's the same data the page uses to render itself
  - It includes exact availability status strings, not just button labels

How to find the item ID:
  - Go to the Walmart product page
  - Look in the URL: walmart.com/ip/[product-name]/[ITEM_ID]
  - Example: "1234567890"

Watchlist entry format:
  {
    "name": "Pokemon TCG Prismatic Evolutions ETB",
    "retailer": "walmart",
    "identifier": "1234567890",
    "url": "https://www.walmart.com/ip/..."
  }
"""

import json
import re
import requests
from .base import RetailerBase, StockResult

HEADERS = {
    **RetailerBase.BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class Walmart(RetailerBase):
    default_poll_interval = 60  # More conservative — Walmart is the hardest to poll

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            html = resp.text

            # Extract the __NEXT_DATA__ JSON blob embedded in the page
            match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                html,
                re.DOTALL,
            )

            if not match:
                # Walmart may have returned a bot-check page
                return StockResult(
                    available=False,
                    retailer="Walmart",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Could not parse page — may have been blocked",
                )

            data = json.loads(match.group(1))

            # Navigate the deeply nested Walmart JSON structure
            # The path: props → pageProps → initialData → data → product → availabilityStatus
            try:
                product_data = (
                    data["props"]["pageProps"]["initialData"]["data"]["product"]
                )
                availability = product_data.get("availabilityStatus", "")
                price_info = product_data.get("priceInfo", {})
                price = price_info.get("currentPrice", {}).get("price")
                product_name = product_data.get("name", name)

                # Walmart status strings
                available = availability in ("IN_STOCK", "AVAILABLE", "LIMITED_AVAILABILITY")

                return StockResult(
                    available=available,
                    retailer="Walmart",
                    product_name=product_name,
                    url=url,
                    price=price,
                    note=availability.replace("_", " ").title() if available else None,
                )

            except (KeyError, TypeError):
                # JSON structure didn't match expected path — fall back to text search
                return self._text_fallback(html, name, url)

        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Walmart",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )

    def _text_fallback(self, html: str, name: str, url: str) -> StockResult:
        """Last resort: search the raw HTML for stock signals."""
        html_lower = html.lower()
        in_stock = any(s in html_lower for s in ["add to cart", "add to registry"])
        out_of_stock = any(s in html_lower for s in ["out of stock", "sold out", "unavailable"])

        if in_stock and not out_of_stock:
            available = True
        else:
            available = False

        return StockResult(
            available=available,
            retailer="Walmart",
            product_name=name,
            url=url,
            price=None,
            note="Text fallback — JSON parse failed",
        )
