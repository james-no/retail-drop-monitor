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

import re

import requests
from .base import RetailerBase, StockResult

# Best Buy's internal product availability API (used by their website, no key needed)
AVAILABILITY_URL = "https://www.bestbuy.com/api/tcfr/product-badging/v1/pcmcat-pc/us/en/badging"


class BestBuy(RetailerBase):
    default_poll_interval = 120  # API gets rate-limited at 30s; 2-min interval reduces noise

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
                # SKU not in response — API format may have changed; silent retry
                return StockResult(
                    available=False,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note=None,
                )

            return StockResult(
                available=available,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=price,
                note="In stock — GO GO GO" if available else None,
            )

        except requests.RequestException:
            # Don't fall back to the product page — it's also blocked/slow and
            # the 15s timeout just slows the entire monitor loop.
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note=None,  # silent — API being blocked is expected noise
            )

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

        except requests.exceptions.Timeout:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="Best Buy rate-limiting — will retry next poll",
            )
        except Exception as e:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="Best Buy check blocked — will retry next poll",
            )


def _bb_product_name(url: str) -> str:
    """Extract a human-readable product name from a Best Buy product URL."""
    try:
        # URL: .../product/pokemon-tcg-30th-celebration-etb/JJG2TLXXXX
        slug = url.split("/product/")[-1].rsplit("/", 1)[0]
        return slug.replace("-", " ").title()
    except Exception:
        return url


class BestBuySearch(RetailerBase):
    """
    Watches a Best Buy search results page for new products.

    Alerts when a new product URL matching the configured keywords appears
    in the search results — catches 30th Anniversary products being added
    to Best Buy's catalog before they go individually live.

    Uses the same monotonically growing seen-set pattern as PokemonCenterSitemap:
    once a product URL is seen it is never "unseen", so transient search result
    changes don't produce false alerts.

    Watchlist entry format:
      {
        "name": "Best Buy — Pokemon 30th Anniversary Search",
        "retailer": "best_buy_search",
        "identifier": "bb-pokemon-30th-search",
        "url": "https://www.bestbuy.com/site/searchpage.jsp?id=pcat17071&st=pokemon%2030",
        "keywords": ["30th-celebration", "30th-anniversary", "celebration"]
      }
    """

    default_poll_interval = 300  # 5 min — search page, not an individual SKU

    HEADERS = {
        **RetailerBase.BASE_HEADERS,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.bestbuy.com/",
    }

    def __init__(self):
        self._ever_seen: set = set()   # product URLs ever found — grows only, never shrinks
        self._min_fetch_size: int = 0  # partial-fetch guard
        self._initialized = False

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]
        keywords = [kw.lower() for kw in item.get("keywords", [])]

        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except requests.exceptions.Timeout:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="Search page request timed out — will retry",
            )
        except Exception:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="Search page check blocked — will retry",
            )

        # Extract all /product/... hrefs (relative or absolute)
        raw_links = re.findall(
            r'href="((?:https://www\.bestbuy\.com)?/product/[^"?#]+)"',
            html,
        )
        # Normalise to full URLs and deduplicate
        all_urls: set[str] = set()
        for link in raw_links:
            if link.startswith("/"):
                link = "https://www.bestbuy.com" + link
            all_urls.add(link.rstrip("/"))

        # Apply keyword filter against the URL slug (which is the product name)
        def _matches(u: str) -> bool:
            if not keywords:
                return True
            slug = u.split("/product/")[-1].lower()
            return any(kw in slug for kw in keywords)

        matching: set[str] = {u for u in all_urls if _matches(u)}

        if not matching:
            # Could be a bad fetch — don't update state
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="No matching products in search results — page may have changed",
            )

        # First run: seed the seen-set and set the partial-fetch floor
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

        # Partial-fetch guard: if far fewer matching results than usual, skip update
        if len(matching) < self._min_fetch_size:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note=(
                    f"Only {len(matching)} matching product(s) returned "
                    f"(expected ≥{self._min_fetch_size}) — search may have timed out, skipping"
                ),
            )

        new_urls = matching - self._ever_seen
        self._ever_seen |= matching  # monotonically grow

        if new_urls:
            lines = [
                f"[NEW] {_bb_product_name(u)}\n  → {u}"
                for u in sorted(new_urls)
            ]
            note = "\n".join(lines)
            alert_url = sorted(new_urls)[0]  # link to first new product
            return StockResult(
                available=True,
                retailer="Best Buy Search",
                product_name=f"NEW on Best Buy: {len(new_urls)} new 30th product(s) detected",
                url=alert_url,
                price=None,
                note=note,
            )

        return StockResult(
            available=False,
            retailer="Best Buy Search",
            product_name=name,
            url=url,
            price=None,
            note=None,
        )
