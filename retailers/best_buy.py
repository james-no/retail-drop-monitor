"""
Best Buy retailer module.

Uses a headless browser to load the product page and check availability.
Best Buy is React-rendered but availability signals (Add to Cart / Sold Out)
are present in the rendered DOM.

How to find the SKU for any Best Buy product:
  - Go to the product page
  - The SKU is in the URL: bestbuy.com/site/[name]/[SKU].p
  - Or look for "SKU:" on the product page itself

Watchlist entry format:
  {
    "name": "Pokemon TCG 30th Celebration ETB",
    "retailer": "best_buy",
    "identifier": "6685559",          <-- Best Buy SKU
    "url": "https://www.bestbuy.com/site/..."
  }
"""

import re
import requests

from .base import RetailerBase, StockResult

# Best Buy's internal product availability API (used by their website, no key needed)
AVAILABILITY_URL = "https://www.bestbuy.com/api/tcfr/product-badging/v1/pcmcat-pc/us/en/badging"

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.bestbuy.com",
    "Referer": "https://www.bestbuy.com/",
}


class BestBuy(RetailerBase):
    default_poll_interval = 120  # 2-min interval to stay under rate limits

    def check_availability(self, item: dict) -> StockResult:
        sku = item["identifier"]
        url = item["url"]
        name = item["name"]

        # Try the lightweight JSON API first (no browser needed)
        try:
            resp = requests.get(
                AVAILABILITY_URL,
                params={"skus": sku},
                headers=API_HEADERS,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                products = data if isinstance(data, list) else data.get("products", [])
                for product in products:
                    if str(product.get("sku", "")) == str(sku):
                        available = (
                            product.get("addToCartEligible", False)
                            or product.get("availabilityStatus") == "Available"
                        )
                        price = product.get("regularPrice") or product.get("salePrice")
                        return StockResult(
                            available=available,
                            retailer="Best Buy",
                            product_name=name,
                            url=url,
                            price=price,
                            note="In stock — GO GO GO" if available else None,
                        )
        except Exception:
            pass  # API blocked or changed — fall through to browser

        # API failed or SKU not in response — use headless browser
        return self._browser_check(item)

    def _browser_check(self, item: dict) -> StockResult:
        name = item["name"]
        url = item["url"]
        sku = item["identifier"]

        try:
            from .playwright_base import fetch_page
        except ImportError:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="Playwright not installed — run: pip install playwright && playwright install chromium",
            )

        try:
            # Use the canonical .p URL format if we have a numeric SKU
            page_url = url
            if sku.isdigit():
                page_url = f"https://www.bestbuy.com/site/product/{sku}.p?skuId={sku}"

            # Wait for networkidle so React finishes rendering availability
            html = fetch_page(page_url, wait_until="networkidle", timeout_ms=30_000)
            html_lower = html.lower()

            if "add to cart" in html_lower:
                # Try to extract price from the rendered page
                price = None
                price_match = re.search(
                    r'"priceView"[^}]*"customerPrice"\s*:\s*([0-9.]+)',
                    html,
                )
                if price_match:
                    try:
                        price = float(price_match.group(1))
                    except ValueError:
                        pass
                return StockResult(
                    available=True,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=price,
                    note="In stock — GO GO GO",
                )
            elif any(s in html_lower for s in ("sold out", "coming soon", "unavailable")):
                return StockResult(
                    available=False,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note=None,
                )
            else:
                return StockResult(
                    available=False,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note=None,
                )
        except Exception as e:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note=f"Browser check error: {e}",
            )


def _bb_product_name(url: str) -> str:
    """Extract a human-readable product name from a Best Buy product URL."""
    try:
        slug = url.split("/product/")[-1].rsplit("/", 1)[0]
        return slug.replace("-", " ").title()
    except Exception:
        return url


class BestBuySearch(RetailerBase):
    """
    Watches a Best Buy search results page for new products.
    Uses a headless browser so the React-rendered results actually appear.

    Watchlist entry format:
      {
        "name": "Best Buy — Pokemon 30th Anniversary Search",
        "retailer": "best_buy_search",
        "identifier": "bb-pokemon-30th-search",
        "url": "https://www.bestbuy.com/site/searchpage.jsp?id=pcat17071&st=pokemon%2030",
        "keywords": ["30th-celebration", "30th-anniversary", "celebration"]
      }
    """

    default_poll_interval = 300  # 5 min — search page, not a product SKU

    def __init__(self):
        self._ever_seen: set = set()
        self._min_fetch_size: int = 0
        self._initialized = False

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]
        keywords = [kw.lower() for kw in item.get("keywords", [])]

        try:
            from .playwright_base import fetch_page
        except ImportError:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="Playwright not installed — run: pip install playwright && playwright install chromium",
            )

        try:
            html = fetch_page(url, wait_until="networkidle", timeout_ms=45_000)
        except Exception as e:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note=f"Search page error: {e}",
            )

        raw_links = re.findall(
            r'href="((?:https://www\.bestbuy\.com)?/site/[^"?#]+)"',
            html,
        )
        all_urls: set = set()
        for link in raw_links:
            if link.startswith("/"):
                link = "https://www.bestbuy.com" + link
            all_urls.add(link.rstrip("/"))

        def _matches(u: str) -> bool:
            if not keywords:
                return True
            slug = u.split("/site/")[-1].lower()
            return any(kw in slug for kw in keywords)

        matching = {u for u in all_urls if _matches(u)}

        if not matching:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="No matching products in search results",
            )

        if not self._initialized:
            self._ever_seen = set(matching)
            self._min_fetch_size = max(1, len(matching) // 2)
            self._initialized = True
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note=f"Initialized — tracking {len(matching)} matching product(s)",
            )

        if len(matching) < self._min_fetch_size:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note=f"Only {len(matching)} results (expected ≥{self._min_fetch_size}) — skipping",
            )

        new_urls = matching - self._ever_seen
        self._ever_seen |= matching

        if new_urls:
            lines = [
                f"[NEW] {_bb_product_name(u)}\n  → {u}"
                for u in sorted(new_urls)
            ]
            return StockResult(
                available=True,
                retailer="Best Buy Search",
                product_name=f"NEW on Best Buy: {len(new_urls)} new 30th product(s) detected",
                url=sorted(new_urls)[0],
                price=None,
                note="\n".join(lines),
            )

        return StockResult(
            available=False,
            retailer="Best Buy Search",
            product_name=name,
            url=url,
            price=None,
            note=None,
        )
