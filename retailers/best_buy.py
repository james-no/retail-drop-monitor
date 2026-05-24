"""
Best Buy retailer module.

Uses Best Buy's internal product API — the same endpoint their website uses
to fetch product data. No API key or signup required.

How to find the SKU for any Best Buy product:
  - Go to the product page
  - The SKU is in the URL: bestbuy.com/site/[name]/[SKU].p
  - Or look for "SKU:" on the product page itself

Watchlist entry format:
  {
    "name": "Pokemon TCG Prismatic Evolutions ETB",
    "retailer": "best_buy",
    "identifier": "6609999",          <-- Best Buy SKU
    "url": "https://www.bestbuy.com/site/..."
  }
"""

import requests
from .base import RetailerBase, StockResult

# Best Buy's internal product availability API (used by their website, no key needed)
AVAILABILITY_URL = "https://www.bestbuy.com/api/tcfr/product-badging/v1/pcmcat-pc/us/en/badging"


class BestBuy(RetailerBase):
    default_poll_interval = 30

    HEADERS = {
        **RetailerBase.BASE_HEADERS,
        "Accept": "application/json",
        "Origin": "https://www.bestbuy.com",
        "Referer": "https://www.bestbuy.com/",
    }

    def check_availability(self, item: dict) -> StockResult:
        sku = item["identifier"]
        url = item["url"]
        name = item["name"]

        # Best Buy's internal badging API — returns add-to-cart availability per SKU
        params = {
            "skus": sku,
        }

        try:
            resp = requests.get(
                AVAILABILITY_URL,
                params=params,
                headers=self.HEADERS,
                timeout=10,
            )

            if resp.status_code == 404:
                return StockResult(
                    available=False,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Product not found",
                )

            resp.raise_for_status()
            data = resp.json()

            # The response is a list of product objects keyed by SKU
            # Try to find our SKU in the response
            products = data if isinstance(data, list) else data.get("products", [])

            available = False
            price = None

            for product in products:
                if str(product.get("sku", "")) == str(sku):
                    # Best Buy uses "addToCartEligible" or "availabilityStatus"
                    available = (
                        product.get("addToCartEligible", False)
                        or product.get("availabilityStatus") == "Available"
                    )
                    price = product.get("regularPrice") or product.get("salePrice")
                    break
            else:
                # SKU not in response — fall back to page scrape
                return self._page_fallback(item)

            return StockResult(
                available=available,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=price,
                note="In stock — GO GO GO" if available else None,
            )

        except requests.RequestException:
            return self._page_fallback(item)

    def _page_fallback(self, item: dict) -> StockResult:
        """
        Fallback: load the product page and look for add-to-cart / sold-out signals.
        Best Buy renders some availability data server-side so this works without JS.
        """
        name = item["name"]
        url = item["url"]

        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=15)
            html = resp.text.lower()

            if "add to cart" in html or "check stores" in html:
                available = True
            elif "sold out" in html or "unavailable" in html:
                available = False
            else:
                available = False

            return StockResult(
                available=available,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="HTML fallback" if available else None,
            )

        except Exception as e:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note=f"All checks failed: {e}",
            )
