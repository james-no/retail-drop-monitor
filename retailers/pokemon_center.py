"""
Pokémon Center retailer module — two strategies working together.

STRATEGY 1: Product availability check
  Polls the product's JSON endpoint for live stock status.
  Pokemon Center's platform exposes product data as JSON if you know where to look.
  We parse their availability response directly.

STRATEGY 2: Sitemap watcher (the "before anyone else" feature)
  Pokemon Center adds new product URLs to their XML sitemap before the drop page
  goes fully live. By watching the sitemap for NEW urls that weren't there last
  check, you get an alert the moment a product is registered — sometimes minutes
  before the drop is announced anywhere.

How to find the product identifier:
  - Go to the product page on pokemoncenter.com
  - The URL contains the product ID: pokemoncenter.com/product/[ID]/[slug]
  - Example: "290-86189" from .../product/290-86189/pokemon-tcg-...

Watchlist entry format:
  {
    "name": "Pokemon TCG Prismatic Evolutions ETB",
    "retailer": "pokemon_center",
    "identifier": "290-86189",
    "url": "https://www.pokemoncenter.com/product/290-86189/..."
  }

For sitemap watching, add a special entry:
  {
    "name": "Pokemon Center Sitemap — watch for new drops",
    "retailer": "pokemon_center_sitemap",
    "identifier": "sitemap",
    "url": "https://www.pokemoncenter.com/sitemap.xml",
    "keywords": ["elite trainer", "booster box", "premium"]   <-- optional filter
  }
"""

import re
import requests
import xml.etree.ElementTree as ET
from .base import RetailerBase, StockResult

BASE = "https://www.pokemoncenter.com"

HEADERS = {
    **RetailerBase.BASE_HEADERS,
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.pokemoncenter.com/",
}

# Phrases Pokémon Center shows on its "site is down for maintenance" page
MAINTENANCE_SIGNALS = [
    "scheduled maintenance",
    "performing maintenance",
    "currently performing",
    "check back soon",
    "down for maintenance",
]


def _is_maintenance_page(html_lower: str) -> bool:
    return any(sig in html_lower for sig in MAINTENANCE_SIGNALS)


class PokemonCenter(RetailerBase):
    """Checks availability of a known product."""
    default_poll_interval = 30  # Pokemon Center drops are time-sensitive

    def check_availability(self, item: dict) -> StockResult:
        product_id = item["identifier"]
        url = item["url"]
        name = item["name"]

        # Pokemon Center exposes product data in a JSON endpoint
        api_url = f"{BASE}/api/2.0/product/{product_id}"

        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=10)

            if resp.status_code == 404:
                # Product not live yet — not an error, just not available
                return StockResult(
                    available=False,
                    retailer="Pokémon Center",
                    product_name=name,
                    url=url,
                    price=None,
                    note="Product page not live yet",
                )

            resp.raise_for_status()
            data = resp.json()

            # Navigate their response structure
            # The exact keys depend on their API version; we check several common patterns
            available = False
            price = None

            # Pattern A: top-level availability flag
            if "available" in data:
                available = bool(data["available"])

            # Pattern B: variants array (for products with sizes/editions)
            elif "variants" in data:
                variants = data.get("variants", [])
                available = any(v.get("available", False) for v in variants)

            # Pattern C: inventory_quantity
            elif "inventory_quantity" in data:
                available = data["inventory_quantity"] > 0

            # Try to get price
            if "price" in data:
                price = data["price"]
            elif "variants" in data and data["variants"]:
                price = data["variants"][0].get("price")
                if price:
                    price = float(price) / 100  # Shopify returns cents

            product_name = data.get("title", name)

            return StockResult(
                available=available,
                retailer="Pokémon Center",
                product_name=product_name,
                url=url,
                price=price,
                note="In stock — GO GO GO" if available else None,
            )

        except requests.RequestException as e:
            # Fall back to HTML check on API failure
            return self._html_fallback(item, str(e))

    def _html_fallback(self, item: dict, error_note: str) -> StockResult:
        """
        If the JSON API fails, load the actual page and check for
        out-of-stock indicators in the HTML. Less precise but works as backup,
        and is generally less likely to get rate-limited than the API during
        a high-traffic drop.
        """
        try:
            resp = requests.get(item["url"], headers=HEADERS, timeout=15)

            # A blocked/rate-limited request often comes back as a 403/429/503
            # with a "Pardon Our Interruption" style page, not real product HTML
            if resp.status_code in (403, 429, 503):
                return StockResult(
                    available=False,
                    retailer="Pokémon Center",
                    product_name=item["name"],
                    url=item["url"],
                    price=None,
                    note=(
                        f"API failed ({error_note}); HTML check got HTTP {resp.status_code} "
                        f"— likely rate-limited/blocked, not a real stock signal"
                    ),
                )

            html = resp.text
            html_lower = html.lower()

            if _is_maintenance_page(html_lower):
                return StockResult(
                    available=False,
                    retailer="Pokémon Center",
                    product_name=item["name"],
                    url=item["url"],
                    price=None,
                    note=(
                        f"API failed ({error_note}); Pokémon Center is down for "
                        f"scheduled maintenance — not a real stock signal, check back later"
                    ),
                )

            block_signals = [
                "pardon our interruption",
                "access denied",
                "are you a human",
                "captcha",
                "request blocked",
                "reference #",
            ]
            if any(sig in html_lower for sig in block_signals):
                return StockResult(
                    available=False,
                    retailer="Pokémon Center",
                    product_name=item["name"],
                    url=item["url"],
                    price=None,
                    note=(
                        f"API failed ({error_note}); HTML page looks like a "
                        f"block/CAPTCHA page, not a real stock signal"
                    ),
                )

            # Most reliable: structured product data (schema.org) embedded in the page
            schema_match = re.search(r'"availability"\s*:\s*"([^"]+)"', html, re.IGNORECASE)
            if schema_match:
                availability = schema_match.group(1).lower()
                available = any(
                    s in availability for s in ("instock", "limitedavailability", "preorder")
                )
                if available:
                    note = f"In stock — GO GO GO (HTML structured data: {availability})"
                else:
                    note = f"API failed ({error_note}); HTML structured data shows: {availability}"
                return StockResult(
                    available=available,
                    retailer="Pokémon Center",
                    product_name=item["name"],
                    url=item["url"],
                    price=None,
                    note=note,
                )

            # Fall back to plain-text button/label signals
            sold_out_signals = ["sold out", "out of stock", "currently unavailable", "notify me when"]
            in_stock_signals = ["add to cart", "add to bag"]

            if any(sig in html_lower for sig in sold_out_signals):
                available = False
                note = f"API failed ({error_note}); HTML shows sold out / notify me"
            elif any(sig in html_lower for sig in in_stock_signals):
                available = True
                note = "In stock — GO GO GO (HTML fallback, found 'add to cart/bag')"
            else:
                # Ambiguous — treat as unavailable to avoid false alerts,
                # but say so explicitly instead of staying silent
                available = False
                note = (
                    f"API failed ({error_note}); HTML check inconclusive "
                    f"(page may be a block/CAPTCHA page during high traffic — verify manually)"
                )

            return StockResult(
                available=available,
                retailer="Pokémon Center",
                product_name=item["name"],
                url=item["url"],
                price=None,
                note=note,
            )
        except requests.exceptions.Timeout:
            return StockResult(
                available=False,
                retailer="Pokémon Center",
                product_name=item["name"],
                url=item["url"],
                price=None,
                note=f"API failed ({error_note}); HTML fallback also timed out",
            )
        except requests.RequestException as e:
            return StockResult(
                available=False,
                retailer="Pokémon Center",
                product_name=item["name"],
                url=item["url"],
                price=None,
                note=f"Both API and HTML check failed — API: {error_note} | HTML: {e}",
            )


class PokemonCenterSitemap(RetailerBase):
    """
    Watches the Pokemon Center sitemap for NEW and RESTOCKED product URLs.
    Fires an alert when a URL appears that wasn't there last check (new drop),
    or when a URL that previously disappeared comes back (restock).
    This is your early-warning system — sitemap updates before pages go live.
    """
    default_poll_interval = 30

    def __init__(self):
        self._known_urls: set = set()       # last snapshot
        self._disappeared_urls: set = set() # URLs that vanished; candidates for restock alert
        self._initialized = False

    def _fetch_all_product_urls(self, sitemap_url: str) -> tuple:
        """
        Handles both sitemap indexes and regular sitemaps.
        Pokemon Center uses a sitemap index — sitemap.xml links to
        multiple child sitemaps. We follow all of them and collect
        every product URL across all child sitemaps.

        Uses a short 8s timeout so failures are detected fast — a slow
        or down Pokemon Center during a drop triggers the alert immediately.

        Returns (urls_or_None, error_message_or_None)
        """
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        try:
            resp = requests.get(sitemap_url, headers=HEADERS, timeout=8)
            if resp.status_code != 200:
                return None, f"HTTP {resp.status_code} fetching sitemap (possible bot-block)"
            resp.raise_for_status()

            if _is_maintenance_page(resp.text.lower()):
                return None, "Pokémon Center is down for scheduled maintenance"

            root = ET.fromstring(resp.content)

            # Check if this is a sitemap INDEX (links to other sitemaps)
            child_sitemaps = root.findall("sm:sitemap/sm:loc", ns)
            if child_sitemaps:
                # Follow each child sitemap and collect product URLs
                all_product_urls = set()
                child_errors = []
                for loc in child_sitemaps:
                    child_url = loc.text.strip() if loc.text else ""
                    if not child_url:
                        continue
                    try:
                        child_resp = requests.get(child_url, headers=HEADERS, timeout=8)
                        if child_resp.status_code != 200:
                            child_errors.append(f"HTTP {child_resp.status_code}")
                            continue
                        child_root = ET.fromstring(child_resp.content)
                        for url_loc in child_root.findall(".//sm:loc", ns):
                            url = url_loc.text.strip() if url_loc.text else ""
                            if url.startswith("https://www.pokemoncenter.com/product/"):
                                all_product_urls.add(url)
                    except Exception as e:
                        child_errors.append(str(e))
                        continue  # Skip failed child sitemaps, keep going

                if not all_product_urls and child_errors:
                    return None, f"All child sitemaps failed: {child_errors[0]}"
                return all_product_urls, None

            # Regular sitemap — collect product URLs directly
            current_urls = set()
            for loc in root.findall(".//sm:loc", ns):
                url = loc.text.strip() if loc.text else ""
                if url.startswith("https://www.pokemoncenter.com/product/"):
                    current_urls.add(url)
            return current_urls, None

        except requests.exceptions.Timeout:
            return None, "Request timed out"
        except requests.exceptions.ConnectionError as e:
            return None, f"Connection error: {e}"
        except ET.ParseError as e:
            return None, f"Failed to parse sitemap XML (likely got an HTML block page): {e}"
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    def check_availability(self, item: dict) -> StockResult:
        keywords = item.get("keywords", [])
        sitemap_url = item.get("url", f"{BASE}/sitemap.xml")

        try:
            current_urls, fetch_error = self._fetch_all_product_urls(sitemap_url)
            if current_urls is None:
                return StockResult(
                    available=False,
                    retailer="Pokémon Center (Sitemap)",
                    product_name="Sitemap fetch failed",
                    url=sitemap_url,
                    price=None,
                    note=f"Could not retrieve sitemap — {fetch_error}",
                )

            if not self._initialized:
                # First run — just record what exists, don't alert on everything
                self._known_urls = current_urls
                self._initialized = True
                return StockResult(
                    available=False,
                    retailer="Pokémon Center (Sitemap)",
                    product_name="Sitemap baseline recorded",
                    url=sitemap_url,
                    price=None,
                    note=f"Tracking {len(current_urls)} product URLs",
                )

            # URLs that just appeared (never seen before)
            new_urls = current_urls - self._known_urls
            # URLs that disappeared last cycle but are back now (restock)
            restocked_urls = current_urls & self._disappeared_urls
            # URLs that just vanished this cycle — track for future restock detection
            vanished_now = self._known_urls - current_urls
            self._disappeared_urls = (self._disappeared_urls | vanished_now) - current_urls
            self._known_urls = current_urls

            if not new_urls and not restocked_urls:
                return StockResult(
                    available=False,
                    retailer="Pokémon Center (Sitemap)",
                    product_name="No new products detected",
                    url=sitemap_url,
                    price=None,
                    note=None,
                )

            def _matches(url):
                if not keywords:
                    return True
                return any(kw.lower() in url.lower() for kw in keywords)

            def _product_name(url):
                """Extract a readable product name from the URL slug."""
                # URL format: /product/290-86189/pokemon-tcg-30th-celebration-...
                parts = url.rstrip("/").split("/")
                slug = parts[-1] if parts else ""
                # Remove leading product ID segment if the slug looks like an ID
                if re.match(r"^\d{3}-\d+$", slug):
                    slug = parts[-2] if len(parts) >= 2 else slug
                return slug.replace("-", " ").title()

            matching_new = [u for u in new_urls if _matches(u)]
            matching_restock = [u for u in restocked_urls if _matches(u)]
            all_matching = matching_new + matching_restock

            if all_matching:
                label_parts = []
                if matching_new:
                    label_parts.append(f"{len(matching_new)} new")
                if matching_restock:
                    label_parts.append(f"{len(matching_restock)} restocked")
                label = " + ".join(label_parts)

                lines = []
                for u in matching_new:
                    lines.append(f"[NEW] {_product_name(u)}\n  → {u}")
                for u in matching_restock:
                    lines.append(f"[RESTOCK] {_product_name(u)}\n  → {u}")

                return StockResult(
                    available=True,
                    retailer="Pokémon Center (Sitemap)",
                    product_name=f"DETECTED: {label} product(s)",
                    url=all_matching[0],
                    price=None,
                    note="\n".join(lines),
                )

            skipped = len(new_urls) + len(restocked_urls)
            return StockResult(
                available=False,
                retailer="Pokémon Center (Sitemap)",
                product_name=f"{skipped} URL(s) — no keyword match",
                url=sitemap_url,
                price=None,
                note=None,
            )

        except Exception as e:
            return StockResult(
                available=False,
                retailer="Pokémon Center (Sitemap)",
                product_name="Sitemap check failed",
                url=sitemap_url,
                price=None,
                note=str(e),
            )
