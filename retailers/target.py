"""
Target retailer module.

Uses Target's "Redsky" internal aggregation API — the same backend
target.com's own product pages call to render stock/fulfillment info.
Returns JSON directly, no HTML parsing, no JavaScript needed.

The old `api.target.com/products/v3/.../fulfillment_summary` endpoint this
module used to call appears to be retired/non-functional — it was returning
a response shape that didn't match what the code expected, so every check
silently fell through to "unavailable" with no useful detail. This version
calls `redsky.target.com/.../product_fulfillment_v1`, which is documented by
several community stock-bot projects and returns a nested
`data.product.fulfillment.shipping_options` block with both a status string
AND a quantity figure.

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

# Redsky API key seen embedded in target.com's own page requests, and used
# by multiple public stock-bot projects (e.g. redsky_discordhook). Not a
# user-specific secret — same key works across products/IPs per those
# projects, but Target can rotate or rate-limit it at any time.
REDSKY_API_KEY = "ff457966e64d5e877fdbad070f276d18ecec4a01"

REDSKY_BASE = "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"

# Statuses that mean "you can actually buy/preorder this right now".
# PRE_ORDER_SELLABLE = preorder window is open and sellable.
AVAILABLE_STATUSES = {
    "IN_STOCK",
    "LIMITED_STOCK",
    "LIMITED_STOCK_SEE_DETAILS",
    "PRE_ORDER_SELLABLE",
    "PREORDER_SELLABLE",
    "BACKORDER",
}


class Target(RetailerBase):
    default_poll_interval = 45

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
            "key": REDSKY_API_KEY,
            "tcin": tcin,
        }

        try:
            resp = requests.get(
                REDSKY_BASE,
                params=params,
                headers=self.HEADERS,
                timeout=10,
            )

            if resp.status_code == 404:
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Not found in Target's Redsky API (TCIN may be wrong or delisted)",
                )

            if resp.status_code in (403, 429, 503):
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note=f"Redsky API returned HTTP {resp.status_code} — likely rate-limited/blocked",
                )

            resp.raise_for_status()
            data = resp.json()

            # A bad/expired API key comes back as a 200 with an "errors" array
            if "errors" in data:
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note=f"Redsky API error response: {data['errors']}",
                )

            # Real shape is {"data": {"product": {...}}} — NOT top-level "product"
            product = data.get("data", {}).get("product", {})
            if not product:
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note=f"Unexpected Redsky response — no product data (top-level keys: {list(data.keys())})",
                )

            fulfillment = product.get("fulfillment", {})
            shipping = fulfillment.get("shipping_options", {})
            availability = shipping.get("availability_status")
            qty = shipping.get("available_to_promise_quantity")
            reason = shipping.get("reason_code")

            if availability is None:
                return StockResult(
                    available=False,
                    retailer="Target",
                    product_name=name,
                    url=url,
                    price=None,
                    note=(
                        "No shipping availability_status in response "
                        f"(fulfillment keys: {list(fulfillment.keys())})"
                    ),
                )

            available = availability in AVAILABLE_STATUSES
            readable = availability.replace("_", " ").title()

            qty_str = ""
            if qty is not None:
                qty_str = f", {qty} available to ship" if qty else ", 0 available to ship"

            reason_str = f" ({reason})" if reason and not available else ""

            if available:
                note = f"In stock/preorder open — GO GO GO (status: {readable}{qty_str})"
            else:
                note = f"Not available yet (Target status: {readable}{qty_str}{reason_str})"

            return StockResult(
                available=available,
                retailer="Target",
                product_name=name,
                url=url,
                price=None,
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
