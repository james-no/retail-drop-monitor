"""
Premium Bandai (p-bandai.com) retailer module.

Series watcher — polls a series/shop listing page for new products.
Alerts when a product URL appears that wasn't seen before (monotonic seen-set).
On first boot it silently seeds the seen-set so it only alerts on *new* drops,
not everything currently in the catalog.

Watchlist entry format:
  {
    "name": "One Piece Card Game — New Drops",
    "retailer": "premium_bandai_series",
    "identifier": "onepiece",
    "url": "https://p-bandai.com/us/series/onepiece-series?_f_shops=05-0004&_f_series=03-002"
  }
"""

import re
import requests
from .base import RetailerBase, StockResult

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

# Matches product URLs like /us/item/N2888744001
PRODUCT_LINK_RE = re.compile(r'/us/item/([A-Z0-9]+)', re.IGNORECASE)


def _fetch_product_codes(url: str) -> set:
    """GET the series page and extract all product codes from href links."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return set(PRODUCT_LINK_RE.findall(resp.text))


class PremiumBandaiSeries(RetailerBase):
    """
    Watches a p-bandai.com series listing page for new products.
    Fires when a product code appears that wasn't there on the previous poll.
    First poll silently seeds the seen-set (no false-positive alerts on startup).
    """

    default_poll_interval = 60

    def __init__(self):
        self._ever_seen: set = set()
        self._initialized: bool = False

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]

        try:
            codes = _fetch_product_codes(url)
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )

        if not codes:
            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note="No products found on page — may be JS-rendered or blocked",
            )

        if not self._initialized:
            # Seed the seen-set on first run — don't alert on existing products
            self._ever_seen = codes
            self._initialized = True
            return StockResult(
                available=False,
                retailer="Premium Bandai",
                product_name=name,
                url=url,
                price=None,
                note=f"Initialized — tracking {len(codes)} existing product(s)",
            )

        new_codes = codes - self._ever_seen
        self._ever_seen |= codes

        if new_codes:
            links = [f"https://p-bandai.com/us/item/{c}" for c in list(new_codes)[:3]]
            note = f"{len(new_codes)} new product(s): " + " | ".join(links)
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
            note=f"Tracking {len(self._ever_seen)} product(s), none new",
        )


# Keep PremiumBandai alias in case it's referenced anywhere
PremiumBandai = PremiumBandaiSeries
