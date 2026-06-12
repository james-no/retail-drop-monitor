"""
Target retailer module.

Uses Target's internal inventory API — the same endpoint their website and
mobile app use. Returns JSON directly, no HTML parsing, no JavaScript needed.

How to find a TCIN (Target's product ID):
  - Go to the product page on Target.com
  - Look in the URL: target.com/p/[name]/-/A-[TCIN]
  - Or open DevTools → Network → filter for "fulfillment" to see the API call

Watchlist entry format:
  {
    "name": "Pokemon TCG Prismatic Evolutions ETB",
    "retailer": "target",
    "identifier": "89484558",         <-- TCIN from product URL
    "url": "https://www.target.com/p/..."
  }
"""

import requests
from .base import RetailerBase, StockResult

# This is Target's public API key used by their website.
# It's embedded in every target.com page request and is not secret.
TARGET_API_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"


class Target(RetailerBase):
    default_poll_interval = 45

    API_BASE = "https://api.target.com/products/v3"

    # Extra headers that match what the Target website sends
    HEADERS = {
        **RetailerBase.BASE_HEADERS,
        "Accept": "application/json",
        "Origin": "https://www.target.com",
        "Referer": "https://www.target.com/",
    }

    def check_availability(self, item: dict) -> StockResult:
        tcin = item["identifier"]
        url = item["url"]
        name = item["name"]

        params = {
            "key": TARGET_API_KEY,
            "store_id": "3991",       # Seattle-area store; change if you want local pickup info
            "zip": "98101",
            "state": "WA",
            "latitude": "47.60",
            "longitude": "-122.33",
            "scheduled_delivery_store_id": "3991",
            "pricing_store_id": "3991",
        }

        try:
            resp = requests.get(
                f"{self.API_BASE}/{tcin}/fulfillment_summary",
                params=params,
                headers=self.HEADERS,
                timeout=10,
            )

            if resp.status_code == 404:
                # Product not found on Target's API — treat as out of stock, not an error
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Not found in Target's inventory API",
                )

            resp.raise_for_status()
            data = resp.json()

            # Dig into the fulfillment options
            product = data.get("product", {})
            fulfillment = product.get("fulfillment", {})
            shipping = fulfillment.get("shipping_options", {})
            availability = shipping.get("availability_status")

            if availability is None:
                # Response came back but didn't have the shape we expect —
                # surface that instead of silently treating it as unavailable
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note=(
                        "Unexpected API response — no shipping availability_status found "
                        f"(top-level keys: {list(data.keys())}, "
                        f"product keys: {list(product.keys())}, "
                        f"fulfillment keys: {list(fulfillment.keys())})"
                    ),
                )

            # Statuses that mean "you can actually buy/preorder this right now".
            # PRE_ORDER_SELLABLE = preorder window is open and sellable.
            AVAILABLE_STATUSES = {
                "IN_STOCK",
                "LIMITED_STOCK",
                "LIMITED_STOCK_SEE_DETAILS",
                "AVAILABLE",
                "PRE_ORDER_SELLABLE",
                "PREORDER_SELLABLE",
                "BACKORDER",
            }

            available = availability in AVAILABLE_STATUSES

            # Try to get price from the price summary block
            price_block = product.get("price", {})
            price = price_block.get("current_retail")

            # Always report the raw status so it's clear what Target is
            # currently returning (e.g. PRE_ORDER_UNSELLABLE vs OUT_OF_STOCK
            # vs UNAVAILABLE) instead of going silent when not available.
            readable = availability.replace("_", " ").title()
            note = (
                f"In stock/preorder open — GO GO GO (status: {readable})"
                if available
                else f"Not available yet (Target status: {readable})"
            )

            return StockResult(
                available=available,
                retailer="Target",
                product_name=name,
                url=url,
                price=price,
                note=note,
            )

        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Target",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )
