"""
Base class all retailer modules inherit from.
Each retailer must implement check_availability() and return a standard result dict.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class StockResult:
    """Standardized result returned by every retailer module."""
    available: bool           # True if in stock / add-to-cart is live
    retailer: str             # e.g. "Best Buy"
    product_name: str         # Human-readable name from watchlist
    url: str                  # Direct product URL
    price: Optional[float]    # Price if we can read it, else None
    note: Optional[str]       # Extra context (e.g. "ships in 3–5 days")


class RetailerBase(ABC):
    """Abstract base — every retailer module subclasses this."""

    # How long to wait between requests to this retailer (seconds).
    # Subclasses can override to be more or less aggressive.
    default_poll_interval: int = 60

    # Standard headers that make requests look like a real browser.
    BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/html, */*",
    }

    @abstractmethod
    def check_availability(self, item: dict) -> StockResult:
        """
        Check whether the item is in stock.

        Args:
            item: One entry from the watchlist config, e.g.:
                  { "name": "...", "retailer": "best_buy",
                    "identifier": "6609999", "url": "https://..." }

        Returns:
            StockResult
        """
        pass
