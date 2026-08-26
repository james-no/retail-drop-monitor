"""
Plaza Japan retailer module.

Watches a Plaza Japan category page for new product listings.
Alerts when a product link appears that wasn't there before (monotonic seen-set).
First poll silently seeds the seen-set so only genuinely new products trigger alerts.

Watchlist entry format:
  {
    "name": "Plaza Japan — Pokemon",
    "retailer": "plaza_japan",
    "identifier": "plaza-pokemon",
    "url": "https://www.plazajapan.com/pokemon/"
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
    "Referer": "https://www.plazajapan.com/",
}

# Matches product page URLs — Plaza Japan product pages use numeric JAN codes
# e.g. /4521329284767/ or slugs under a category like /pokemon/product-name/
PRODUCT_LINK_RE = re.compile(
    r'href="((?:https://www\.plazajapan\.com)?/(?:\d{8,13}|[a-z0-9][a-z0-9\-]+/[a-z0-9][a-z0-9\-]+)/)"',
    re.IGNORECASE,
)


def _fetch_product_links(url: str) -> set:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    links = set()
    for href in PRODUCT_LINK_RE.findall(resp.text):
        if not href.startswith("http"):
            href = "https://www.plazajapan.com" + href
        links.add(href.rstrip("/"))
    return links


class PlazaJapan(RetailerBase):
    default_poll_interval = 60

    def __init__(self):
        self._ever_seen: set = set()
        self._initialized: bool = False

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]
        keywords = [kw.lower() for kw in item.get("keywords", [])]

        try:
            links = _fetch_product_links(url)
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )

        if not links:
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name=name,
                url=url,
                price=None,
                note="No product links found on page",
            )

        # Apply keyword filter if configured
        def _matches(link: str) -> bool:
            if not keywords:
                return True
            return any(kw in link.lower() for kw in keywords)

        matching = {l for l in links if _matches(l)}

        if not self._initialized:
            self._ever_seen = set(matching)
            self._initialized = True
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name=name,
                url=url,
                price=None,
                note=f"Initialized — tracking {len(matching)} product(s)",
            )

        new_links = matching - self._ever_seen
        self._ever_seen |= matching

        if new_links:
            note = f"{len(new_links)} new product(s): " + " | ".join(sorted(new_links)[:3])
            return StockResult(
                available=True,
                retailer="Plaza Japan",
                product_name=f"NEW on Plaza Japan: {len(new_links)} product(s)",
                url=sorted(new_links)[0],
                price=None,
                note=note,
            )

        return StockResult(
            available=False,
            retailer="Plaza Japan",
            product_name=name,
            url=url,
            price=None,
            note=None,
        )
