"""
Premium Bandai (p-bandai.com) retailer module.

Two modes:
  1. Item monitor — watches a specific product code for stock changes
  2. Series watcher — polls a series/shop listing for new or newly-available products

How to find a product code:
  - Go to the product page: p-bandai.com/us/item/N2888744001
  - The code is the last segment of the URL: N2888744001

How to find series/shop IDs:
  - One Piece card shop series ID: 03-002, shop ID: 05-0004
  - Digimon series ID: 03-042

Watchlist entry formats:

  Single item:
  {
    "name": "Digimon Card Game Tamer's Evolution Card Set [PB-24]",
    "retailer": "premium_bandai",
    "identifier": "N2884128001",
    "url": "https://p-bandai.com/us/item/N2884128001"
  }

  Series watcher (alerts on new/available products):
  {
    "name": "One Piece Card Game — New Drops",
    "retailer": "premium_bandai_series",
    "identifier": "series:03-002|shop:05-0004",
    "url": "https://p-bandai.com/us/series/onepiece-series?_f_shops=05-0004&_f_series=03-002"
  }

  {
    "name": "Digimon Card Game — New Drops",
    "retailer": "premium_bandai_series",
    "identifier": "series:03-042",
    "url": "https://p-bandai.com/us/series/digimon-series?_f_series=03-042"
  }
"""

import re
import requests
from .base import RetailerBase, StockResult

PBANDAI_BASE = "https://p-bandai.com"

# Alert on pre-orders and lottery/drawing openings
AVAILABLE_FLAGS = {"PRE-ORDER", "LOTTERY", "DRAW", "DRAWING"}


def _build_session() -> tuple[requests.Session, str]:
    """
    Create a requests session by hitting the p-bandai homepage to get a
    SESSION cookie, then extract the CSRF token from the page HTML.
    Returns (session, csrf_token).
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "X-G1-Area-Code": "us",
        "X-Requested-With": "XMLHttpRequest",
    })

    # Load the homepage to get SESSION cookie planted
    resp = session.get(f"{PBANDAI_BASE}/us", timeout=15)
    resp.raise_for_status()

    # CSRF token is typically in a <meta name="csrf-token"> tag or a JS variable
    csrf = ""
    match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\'](.*?)["\']', resp.text)
    if match:
        csrf = match.group(1)
    else:
        # Fallback: look for it in a JS assignment
        match = re.search(r'["\']?csrfToken["\']?\s*[=:]\s*["\']([A-Za-z0-9_\-]+)["\']', resp.text)
        if match:
            csrf = match.group(1)

    return session, csrf


class PremiumBandai(RetailerBase):
    """Monitors a specific p-bandai.com product by item code."""

    default_poll_interval = 60

    _session: requests.Session | None = None
    _csrf: str = ""

    def _get_session(self) -> tuple[requests.Session, str]:
        if self._session is None:
            self._session, self._csrf = _build_session()
        return self._session, self._csrf

    def check_availability(self, item: dict) -> StockResult:
        product_code = item["identifier"]
        url = item["url"]
        name = item["name"]

        session, csrf = self._get_session()

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": url,
            "X-G1-Area-Code": "us",
            "X-Requested-With": "XMLHttpRequest",
        }
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf

        # POST with the product object — matches exactly what the site sends
        payload = [{"areaProductNo": "", "productCode": product_code, "areaCode": "us"}]

        try:
            resp = session.post(
                f"{PBANDAI_BASE}/api/products/fillProductDetailFlags",
                json=payload,
                headers=headers,
                timeout=15,
            )

            # If session expired, rebuild once and retry
            if resp.status_code in (401, 403):
                self._session = None
                session, csrf = self._get_session()
                if csrf:
                    headers["X-CSRF-TOKEN"] = csrf
                resp = session.post(
                    f"{PBANDAI_BASE}/api/products/fillProductDetailFlags",
                    json=payload,
                    headers=headers,
                    timeout=15,
                )

            if resp.status_code == 404:
                return StockResult(
                    available=False,
                    retailer="Premium Bandai",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Product not found — check the item code",
                )

            resp.raise_for_status()
            products = resp.json()

            # Find this product in the response list
            product = next(
                (p for p in products if p.get("productCode") == product_code),
                None,
            )

            if not product:
                return StockResult(
                    available=False,
                    retailer="Premium Bandai",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Not found in API response",
                )

            flags = set(product.get("flags", []))
            available = bool(flags & AVAILABLE_FLAGS)

            price = None
            price_block = product.get("fixedListPrice", {})
            if price_block:
                try:
                    price = float(price_block.get("amount", 0))
                except (ValueError, TypeError):
                    pass

            active_flags = flags & AVAILABLE_FLAGS
            note = ", ".join(active_flags) if available else None

            return StockResult(
                available=available,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=price if price else None,
                note=note,
            )

        except requests.RequestException as e:
            # Reset session on connection errors so it's rebuilt next cycle
            self._session = None
            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )


class PremiumBandaiSeries(RetailerBase):
    """
    Watches a p-bandai.com series or shop listing for new/available products.

    identifier format:
      "series:03-042"              — watch a series by series ID
      "shop:05-0004"               — watch a shop by shop ID
      "series:03-002|shop:05-0004" — watch a series filtered by shop

    Alerts when a product that wasn't previously seen appears in the listing,
    or when a previously seen product changes to an available flag.
    """

    default_poll_interval = 60

    _session: requests.Session | None = None
    _csrf: str = ""
    _seen: dict  # item_key -> set of flags last seen

    def __init__(self):
        self._seen = {}

    def _get_session(self) -> tuple[requests.Session, str]:
        if self._session is None:
            self._session, self._csrf = _build_session()
        return self._session, self._csrf

    def _parse_identifier(self, identifier: str) -> tuple[str | None, str | None]:
        """Returns (series_id, shop_id) from the identifier string."""
        series_id = None
        shop_id = None
        for part in identifier.split("|"):
            part = part.strip()
            if part.startswith("series:"):
                series_id = part[len("series:"):]
            elif part.startswith("shop:"):
                shop_id = part[len("shop:"):]
        return series_id, shop_id

    def check_availability(self, item: dict) -> StockResult:
        identifier = item["identifier"]
        url = item["url"]
        name = item["name"]

        series_id, shop_id = self._parse_identifier(identifier)
        session, csrf = self._get_session()

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": url,
            "X-G1-Area-Code": "us",
            "X-Requested-With": "XMLHttpRequest",
        }
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf

        products = []

        try:
            # Fetch series content and/or shop content
            endpoints = []
            if series_id:
                endpoints.append(f"{PBANDAI_BASE}/api/products/content/series/{series_id}")
            if shop_id:
                endpoints.append(f"{PBANDAI_BASE}/api/products/content/shop/{shop_id}")

            for endpoint in endpoints:
                resp = session.get(endpoint, headers=headers, timeout=15)
                if resp.status_code in (401, 403):
                    self._session = None
                    session, csrf = self._get_session()
                    if csrf:
                        headers["X-CSRF-TOKEN"] = csrf
                    resp = session.get(endpoint, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                # Content endpoint returns a list or a dict with a products key
                if isinstance(data, list):
                    products.extend(data)
                elif isinstance(data, dict):
                    products.extend(data.get("products", data.get("items", [])))

            if not products:
                return StockResult(
                    available=False,
                    retailer="Premium Bandai",
                    product_name=name,
                    url=url,
                    price=None,
                    note="No products returned from series API",
                )

            # Check for new or newly-available products
            new_products = []
            for p in products:
                code = p.get("productCode", "")
                flags = set(p.get("flags", []))
                prev_flags = self._seen.get(code)

                is_available = bool(flags & AVAILABLE_FLAGS)

                if prev_flags is None:
                    # Brand new product we haven't seen before
                    if is_available:
                        new_products.append(p)
                elif not (prev_flags & AVAILABLE_FLAGS) and is_available:
                    # Was unavailable, now available
                    new_products.append(p)

                self._seen[code] = flags

            if new_products:
                names = [p.get("productName", {}).get("en", p.get("productCode", "?"))
                         for p in new_products[:3]]
                note = f"{len(new_products)} new/available: " + ", ".join(names)
                return StockResult(
                    available=True,
                    retailer="Premium Bandai",
                    product_name=name,
                    url=url,
                    price=None,
                    note=note,
                )

            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note=f"Tracking {len(products)} product(s), none newly available",
            )

        except requests.RequestException as e:
            self._session = None
            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )
