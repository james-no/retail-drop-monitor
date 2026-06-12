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

Optional: local store stock
  Add a "store_id" (and optionally "zip"/"state") to also check whether a
  specific store has it on the shelf, in addition to shippable stock:
  {
    "name": "...",
    "retailer": "target",
    "identifier": "89484558",
    "url": "https://www.target.com/p/...",
    "store_id": "696",      <-- Target store number (target.com/sl/.../<id>)
    "zip": "98233",
    "state": "WA"
  }
  This is based on the documented pdp_fulfillment_v1 request shape (see
  https://gist.github.com/LumaDevelopment/f2a34a202fed6ab5a7f3a31282834943),
  which adds store_id/store_positions_store_id/pricing_store_id/zip/state
  params and returns a "store_options" array with per-store
  "order_pickup" and "in_store_only" availability.
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

# Same idea, but for the per-store "order_pickup" / "in_store_only" blocks
# inside fulfillment.store_options.
STORE_AVAILABLE_STATUSES = {
    "IN_STOCK",
    "LIMITED_STOCK",
    "LIMITED_STOCK_SEE_DETAILS",
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

        # If a store_id is configured, also ask Redsky for that store's
        # local pickup/shelf availability (in addition to shipping).
        store_id = item.get("store_id")
        if store_id:
            params.update({
                "store_id": store_id,
                "store_positions_store_id": store_id,
                "has_store_positions_store_id": "true",
                "pricing_store_id": store_id,
                "has_pricing_store_id": "true",
                "is_bot": "false",
            })
            if item.get("zip"):
                params["zip"] = item["zip"]
            if item.get("state"):
                params["state"] = item["state"]

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

            shipping_available = availability in AVAILABLE_STATUSES
            readable = availability.replace("_", " ").title()

            qty_str = ""
            if qty is not None:
                qty_str = f", {qty} available to ship" if qty else ", 0 available to ship"

            reason_str = f" ({reason})" if reason and not shipping_available else ""

            shipping_note = (
                f"Shippable — GO GO GO (status: {readable}{qty_str})"
                if shipping_available
                else f"Not shippable (Target status: {readable}{qty_str}{reason_str})"
            )

            # --- Local store stock (only present if store_id was requested) ---
            store_available = False
            store_note = None
            if store_id:
                store_note, store_available = self._parse_store_option(
                    fulfillment, store_id
                )

            available = shipping_available or store_available

            if store_note:
                note = f"{shipping_note} | {store_note}"
            else:
                note = shipping_note

            if available:
                note = f"GO GO GO — {note}"

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

    @staticmethod
    def _parse_store_option(fulfillment: dict, store_id: str) -> tuple:
        """
        Pull this store's entry out of fulfillment.store_options and report
        on order pickup ("ship to store / order online, pick up in store")
        and in-store-only (on the shelf right now) availability.

        Returns (note_str, available_bool).
        """
        store_options = fulfillment.get("store_options", [])
        store = next(
            (s for s in store_options if str(s.get("location_id")) == str(store_id)),
            None,
        )

        if store is None:
            return (
                f"Store {store_id}: not in store_options response "
                f"({len(store_options)} store(s) returned — check store_id/zip/state)",
                False,
            )

        location_name = store.get("location_name", store_id)
        qty = store.get("location_available_to_promise_quantity")

        pickup_status = (store.get("order_pickup") or {}).get("availability_status")
        shelf_status = (store.get("in_store_only") or {}).get("availability_status")

        pickup_ok = pickup_status in STORE_AVAILABLE_STATUSES
        shelf_ok = shelf_status in STORE_AVAILABLE_STATUSES
        available = pickup_ok or shelf_ok

        parts = []
        if pickup_status:
            parts.append(f"pickup: {pickup_status.replace('_', ' ').title()}")
        if shelf_status:
            parts.append(f"on shelf: {shelf_status.replace('_', ' ').title()}")
        if qty is not None:
            parts.append(f"qty: {qty}")

        detail = ", ".join(parts) if parts else "no pickup/shelf data"
        return f"{location_name} (#{store_id}): {detail}", available
