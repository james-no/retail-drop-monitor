"""
Best Buy retailer module.

Uses curl_cffi to mimic Chrome's exact TLS fingerprint, bypassing Akamai
bot detection which blocks both plain requests and headless browsers at the
HTTP/2 protocol level.

Install: pip install curl_cffi

How to find the SKU for any Best Buy product:
  - Go to the product page
  - The SKU is in the URL: bestbuy.com/site/[name]/[SKU].p

Watchlist entry format:
  {
    "name": "Pokemon TCG 30th Celebration ETB",
    "retailer": "best_buy",
    "identifier": "6685559",
    "url": "https://www.bestbuy.com/site/pokemon-tcg.../6685559.p"
  }
"""

import re
from .base import RetailerBase, StockResult

AVAILABILITY_URL = "https://www.bestbuy.com/api/tcfr/product-badging/v1/pcmcat-pc/us/en/badging"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bestbuy.com/",
}


def _cffi_get(url, *, params=None, headers=None, timeout=15):
    """GET using curl_cffi with Chrome TLS fingerprint."""
    from curl_cffi import requests as cf
    return cf.get(
        url,
        params=params,
        headers=headers or HEADERS,
        impersonate="chrome120",
        timeout=timeout,
    )


class BestBuy(RetailerBase):
    default_poll_interval = 120

    def check_availability(self, item: dict) -> StockResult:
        sku = item["identifier"]
        url = item["url"]
        name = item["name"]

        # Try the JSON API first — lightweight, no full page load
        try:
            resp = _cffi_get(
                AVAILABILITY_URL,
                params={"skus": sku},
                headers={**HEADERS, "Accept": "application/json"},
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
        except ImportError:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="curl_cffi not installed — run: pip install curl_cffi",
            )
        except Exception:
            pass  # API blocked — fall through to page scrape

        # API failed — scrape the product page directly
        return self._page_check(item)

    def _page_check(self, item: dict) -> StockResult:
        name = item["name"]
        url = item["url"]

        try:
            resp = _cffi_get(url, timeout=20)
            if resp.status_code != 200:
                return StockResult(
                    available=False,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note=None,
                )
            html = resp.text.lower()

            if "add to cart" in html or "check stores" in html:
                return StockResult(
                    available=True,
                    retailer="Best Buy",
                    product_name=name,
                    url=url,
                    price=None,
                    note="In stock — GO GO GO",
                )
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note=None,
            )
        except ImportError:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note="curl_cffi not installed — run: pip install curl_cffi",
            )
        except Exception as e:
            return StockResult(
                available=False,
                retailer="Best Buy",
                product_name=name,
                url=url,
                price=None,
                note=None,
            )


def _bb_product_name(url: str) -> str:
    try:
        slug = url.split("/site/")[-1].rsplit("/", 1)[0]
        return slug.replace("-", " ").title()
    except Exception:
        return url


class BestBuySearch(RetailerBase):
    """
    Watches a Best Buy search results page for new 30th Anniversary products.

    Watchlist entry format:
      {
        "name": "Best Buy — Pokemon 30th Anniversary Search",
        "retailer": "best_buy_search",
        "identifier": "bb-pokemon-30th-search",
        "url": "https://www.bestbuy.com/site/searchpage.jsp?id=pcat17071&st=pokemon%2030",
        "keywords": ["30th-celebration", "30th-anniversary", "celebration"]
      }
    """

    default_poll_interval = 300

    def __init__(self):
        self._ever_seen: set = set()
        self._min_fetch_size: int = 0
        self._initialized = False

    def check_availability(self, item: dict) -> StockResult:
        url = item["url"]
        name = item["name"]
        keywords = [kw.lower() for kw in item.get("keywords", [])]

        try:
            resp = _cffi_get(url, timeout=20)
            if resp.status_code != 200:
                return StockResult(
                    available=False,
                    retailer="Best Buy Search",
                    product_name=name,
                    url=url,
                    price=None,
                    note=None,
                )
            html = resp.text
        except ImportError:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note="curl_cffi not installed — run: pip install curl_cffi",
            )
        except Exception:
            return StockResult(
                available=False,
                retailer="Best Buy Search",
                product_name=name,
                url=url,
                price=None,
                note=None,
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
                note=None,
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
                note=None,
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
