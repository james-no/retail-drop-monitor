"""
Plaza Japan retailer module — BigCommerce Stencil store.

Watches the Pokemon TCG booster box category page for:
  - NEW products that weren't there last check
  - RESTOCK: products that were listed as "Pre-Order" or "Sold Out"
    that are now showing "Add to Cart"

How it works:
  Plaza Japan runs on BigCommerce Stencil. Their category pages embed
  product data directly in the HTML — each product card contains a
  cart link (cart.php?action=add&product_id=XXXXX) and the button text
  reveals availability ("Add to Cart" = in stock, "Pre-Order Now" /
  "Sold Out" = not immediately available).

  We parse that HTML on every poll using BeautifulSoup, build a dict of
  {product_id: {name, url, in_stock}}, compare to the previous snapshot,
  and fire when something changes.

Watchlist entry format:
  {
    "name": "Plaza Japan — Pokemon TCG",
    "retailer": "plaza_japan",
    "identifier": "pokemon-tcg",
    "url": "https://www.plazajapan.com/pokemon/pokemon-card-game-booster-boxes/",
    "keywords": ["elite trainer", "booster box", "espeon", "umbreon"]
  }
"""

import re
import requests

try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

from .base import RetailerBase, StockResult

BASE = "https://www.plazajapan.com"

HEADERS = {
    **RetailerBase.BASE_HEADERS,
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Referer": "https://www.plazajapan.com/",
}

# Text in the page that signals a product is immediately purchasable
IN_STOCK_SIGNALS = ["add to cart", "buy now"]

# Text that means it exists but isn't available yet
OUT_OF_STOCK_SIGNALS = ["pre-order", "sold out", "out of stock", "notify me"]


def _parse_products_bs4(html: str) -> dict:
    """
    Parse product listings with BeautifulSoup.

    BigCommerce Stencil category pages list products in article or li elements.
    Each product has a cart link like:
      href="/cart.php?action=add&product_id=211786"
    and a title link like:
      href="/4582292603221/"

    Returns {product_id: {"name": str, "url": str, "in_stock": bool}}
    """
    soup = BeautifulSoup(html, "html.parser")
    products = {}

    # Find all cart/add-to-cart links — each one anchors a unique product
    cart_links = soup.find_all("a", href=re.compile(r"cart\.php.*product_id=(\d+)"))
    for link in cart_links:
        m = re.search(r"product_id=(\d+)", link["href"])
        if not m:
            continue
        product_id = m.group(1)
        link_text = link.get_text(strip=True).lower()
        in_stock = any(sig in link_text for sig in IN_STOCK_SIGNALS)

        # Walk up the DOM to find the product card container
        card = link.find_parent(
            lambda tag: tag.name in ("article", "li", "div")
            and any(
                cls in (tag.get("class") or [])
                for cls in ("product", "listItem", "card", "productGrid")
            )
        )
        if card is None:
            # Fallback: just go up 4 levels
            card = link.parent
            for _ in range(4):
                if card and card.parent:
                    card = card.parent

        # Extract product name and URL from the title link inside the card
        name = ""
        url = ""
        if card:
            # Title link: the first <a> inside the card that has an href pointing to a product
            title_link = card.find(
                "a",
                href=re.compile(r"^/\d+|^https://www\.plazajapan\.com/\w"),
            )
            if title_link and "cart.php" not in title_link.get("href", ""):
                raw_href = title_link["href"]
                url = raw_href if raw_href.startswith("http") else BASE + raw_href
                name = title_link.get_text(strip=True)

        if not name:
            name = f"Product #{product_id}"
        if not url:
            url = f"{BASE}/cart.php?action=add&product_id={product_id}"

        # Don't overwrite an in-stock record with an out-of-stock one
        # (same product can appear twice on a page with different buttons)
        if product_id not in products or in_stock:
            products[product_id] = {"name": name, "url": url, "in_stock": in_stock}

    # Also catch hidden form inputs (some BC themes use forms instead of links)
    forms = soup.find_all("form", action=re.compile(r"cart\.php"))
    for form in forms:
        pid_input = form.find("input", {"name": "product_id"})
        if not pid_input:
            continue
        product_id = pid_input.get("value", "").strip()
        if not product_id or product_id in products:
            continue

        submit_btn = form.find("button") or form.find("input", {"type": "submit"})
        btn_text = (submit_btn.get_text(strip=True) if submit_btn else "").lower()
        in_stock = any(sig in btn_text for sig in IN_STOCK_SIGNALS)

        card = form.find_parent(lambda tag: tag.name in ("article", "li", "div"))
        name, url = "", ""
        if card:
            title_link = card.find("a", href=re.compile(r"^/\d+|^https://www\.plazajapan"))
            if title_link and "cart.php" not in title_link.get("href", ""):
                raw_href = title_link["href"]
                url = raw_href if raw_href.startswith("http") else BASE + raw_href
                name = title_link.get_text(strip=True)

        if not name:
            name = f"Product #{product_id}"
        if not url:
            url = BASE

        products[product_id] = {"name": name, "url": url, "in_stock": in_stock}

    return products


def _parse_products_regex(html: str) -> dict:
    """
    Fallback parser using regex only (when bs4 isn't installed).

    Finds all product_id occurrences in cart links and infers availability
    from the surrounding text window.
    """
    products = {}

    # Find all cart link regions: capture 200 chars of context around each match
    for m in re.finditer(r'product_id=(\d+)', html):
        product_id = m.group(1)
        if product_id in products:
            continue

        start = max(0, m.start() - 500)
        end = min(len(html), m.end() + 500)
        context = html[start:end].lower()

        in_stock = any(sig in context for sig in IN_STOCK_SIGNALS)

        # Try to extract a product name from an href just before the product_id
        name_match = re.search(
            r'href=["\'](?:https://www\.plazajapan\.com)?/[\w-]+/["\'][^>]*>([^<]{5,120})<',
            html[start : m.start()],
        )
        name = name_match.group(1).strip() if name_match else f"Product #{product_id}"

        # Try to get the clean product URL
        url_match = re.search(
            r'href=["\'](?:https://www\.plazajapan\.com)?(/[\w/-]+/?)["\']',
            html[start : m.start()],
        )
        if url_match:
            raw = url_match.group(1)
            url = raw if raw.startswith("http") else BASE + raw
        else:
            url = BASE

        products[product_id] = {"name": name, "url": url, "in_stock": in_stock}

    return products


class PlazaJapan(RetailerBase):
    """
    Watches a Plaza Japan category page for new or restocked products.

    On the first run, records the current product snapshot as a baseline.
    On subsequent runs, fires alerts when:
      - A product_id that wasn't there before appears (NEW)
      - A product that was not in-stock is now showing "Add to Cart" (RESTOCK)
    """
    default_poll_interval = 120  # 2 minutes — BigCommerce can be sensitive to hammering

    def __init__(self):
        # {product_id: {"name": str, "url": str, "in_stock": bool}}
        self._known: dict = {}
        self._initialized = False

    def _fetch_and_parse(self, url: str) -> tuple:
        """
        Fetch the category page and return (products_dict, error_str).
        products_dict: {product_id: {"name", "url", "in_stock"}}
        error_str: non-None if fetch failed
        """
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code}"
            resp.raise_for_status()

            if _BS4_AVAILABLE:
                products = _parse_products_bs4(resp.text)
            else:
                products = _parse_products_regex(resp.text)

            return products, None

        except requests.exceptions.Timeout:
            return None, "Request timed out"
        except requests.exceptions.ConnectionError as e:
            return None, f"Connection error: {e}"
        except requests.RequestException as e:
            return None, f"{type(e).__name__}: {e}"

    def check_availability(self, item: dict) -> StockResult:
        keywords = [kw.lower() for kw in item.get("keywords", [])]
        category_url = item.get("url", f"{BASE}/pokemon/pokemon-card-game-booster-boxes/")

        products, error = self._fetch_and_parse(category_url)

        if products is None:
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name="Page fetch failed",
                url=category_url,
                price=None,
                note=f"Could not retrieve category page — {error}",
            )

        if not self._initialized:
            self._known = products
            self._initialized = True
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name="Baseline recorded",
                url=category_url,
                price=None,
                note=f"Tracking {len(products)} product(s) on {category_url}",
            )

        def _matches(name: str) -> bool:
            if not keywords:
                return True
            name_lower = name.lower()
            return any(kw in name_lower for kw in keywords)

        new_products = []
        restocked = []

        for pid, info in products.items():
            name = info["name"]
            url = info["url"]
            in_stock = info["in_stock"]

            if pid not in self._known:
                # Brand-new product appeared on the page
                if _matches(name):
                    status = "IN STOCK" if in_stock else "pre-order/unlisted"
                    new_products.append((name, url, status, in_stock))
            else:
                # Product we've seen — check if it just became purchasable
                was_in_stock = self._known[pid]["in_stock"]
                if in_stock and not was_in_stock and _matches(name):
                    restocked.append((name, url))

        # Update our snapshot
        self._known = products

        if not new_products and not restocked:
            return StockResult(
                available=False,
                retailer="Plaza Japan",
                product_name="No changes detected",
                url=category_url,
                price=None,
                note=None,
            )

        # Build a combined result (alert fires for the most actionable item first)
        # Prioritize items that are actually in stock right now
        in_stock_hits = [p for p in new_products if p[3]] + restocked
        all_hits = in_stock_hits or [p[:3] for p in new_products]

        primary_name, primary_url = all_hits[0][0], all_hits[0][1]
        label_parts = []
        if new_products:
            label_parts.append(f"{len(new_products)} new")
        if restocked:
            label_parts.append(f"{len(restocked)} restocked")
        label = " + ".join(label_parts)

        lines = []
        for name, url, status, _ in new_products:
            lines.append(f"[NEW — {status}] {name} → {url}")
        for name, url in restocked:
            lines.append(f"[RESTOCK — NOW IN STOCK] {name} → {url}")

        return StockResult(
            available=True,
            retailer="Plaza Japan",
            product_name=f"DETECTED: {label} product(s)",
            url=primary_url,
            price=None,
            note="\n".join(lines),
        )
