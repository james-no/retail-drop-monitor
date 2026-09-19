"""
Plaza Japan retailer module — two modes:

1. PlazaJapan (category watcher):
   Watches a category page for new product listings. Alerts when a product
   link appears that wasn't there before. First poll silently seeds the
   seen-set so you only get alerts on genuinely new products.

   Watchlist entry:
     { "retailer": "plaza_japan", "url": "https://www.plazajapan.com/pokemon/" }

2. PlazaJapanProduct (specific product checker):
   Watches a single product page for an "Add to Cart" button. Alerts
   the moment the item becomes purchasable.

   Watchlist entry:
     { "retailer": "plaza_japan_product", "url": "https://www.plazajapan.com/4521329462189/" }
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

IN_STOCK_SIGNALS = [
    "add to cart",
    "add to bag",
    "カートに入れる",
    "buy now",
    "purchase",
]

OUT_OF_STOCK_SIGNALS = [
    "sold out",
    "out of stock",
    "この商品は完売",
    "unavailable",
    "notify me when available",
]

# Matches product page URLs — Plaza Japan product pages use numeric JAN codes
PRODUCT_LINK_RE = re.compile(
    r'href="((?:https://www\.plazajapan\.com)?/(?:\d{8,13}|[a-z0-9][a-z0-9\-]+/[a-z0-9][a-z0-9\-]+)/)"',
    re.IGNORECASE,
)


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _fetch_product_links(url: str) -> set:
    html = _get(url)
    links = set()
    for href in PRODUCT_LINK_RE.findall(html):
        if not href.startswith("http"):
            href = "https://www.plazajapan.com" + href
        links.add(href.rstrip("/"))
    return links


def _extract_title(html: str) -> str:
    """Pull the page <title> or og:title as the product name."""
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if m:
        return m.group(1).split("|")[0].strip()
    return ""


def _extract_price(html: str) -> float | None:
    """Extract price from common Plaza Japan price patterns."""
    m = re.search(r'\$([0-9,]+\.[0-9]{2})', html)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


class PlazaJapanProduct(RetailerBase):
    """
    Watches a specific Plaza Japan product page for stock availability.
    Alerts when an 'Add to Cart' button appears.
    """
    default_poll_interval = 60

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]

        try:
            html = _get(url)
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name=name,
                url=url,
                price=None,
                note=f"Request error: {e}",
            )

        html_lower = html.lower()
        title = _extract_title(html) or name
        price = _extract_price(html)

        # Explicit out-of-stock wins
        if any(sig in html_lower for sig in OUT_OF_STOCK_SIGNALS):
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name=title,
                url=url,
                price=price,
                note=None,
            )

        if any(sig in html_lower for sig in IN_STOCK_SIGNALS):
            return StockResult(
                available=True,
                retailer="Plaza Japan",
                product_name=title,
                url=url,
                price=price,
                note="In stock on Plaza Japan — GO GO GO",
            )

        return StockResult(
            available=False,
            retailer="Plaza Japan",
            product_name=title,
            url=url,
            price=price,
            note=None,
        )


class PlazaJapan(RetailerBase):
    """Watches a Plaza Japan category page for new product listings."""
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

        def _matches(link: str) -> bool:
            if not keywords:
                return True
            return any(kw in link.lower() for kw in keywords)

        matching = {lnk for lnk in links if _matches(lnk)}

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
