"""
retail-drop-monitor — main entry point

Runs a polling loop across all items in config.json.
When a product goes in stock, fires all configured alerts simultaneously.

Usage:
  python monitor.py                  # Normal mode (uses poll_interval from config)
  python monitor.py --release-mode   # Fast mode (10s polls — use during known drops)
  python monitor.py --test-alerts    # Fire all alerts once to verify setup

Requirements:
  pip install -r requirements.txt
  Copy .env.example to .env and fill in your credentials.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

PST = ZoneInfo("America/Los_Angeles")
from dotenv import load_dotenv

from retailers import RETAILER_MAP
from alerts import fire_all
from alerts import discord_webhook

# Substrings that indicate a check failed to actually run (network error,
# blocked, timeout, parse failure, etc.) rather than a normal "not in stock".
FAILURE_MARKERS = ("error", "failed", "timed out", "could not retrieve", "maintenance")

# How much to randomly vary each item's polling interval, as a fraction of
# its base interval (e.g. 0.15 = +/- 15%). Keeps requests from settling into
# a predictable lockstep cadence.
JITTER_FRACTION = 0.15

# Minimum/maximum gap (seconds) enforced between two checks hitting the same
# retailer back-to-back, even if their schedules land in the same tick. This
# is the actual "stagger" — it spreads out a burst of due items for one
# retailer instead of firing them all in the same instant.
INTER_ITEM_DELAY_RANGE = (1.5, 5.0)

# How often the scheduler wakes up to see what's due.
TICK_SECONDS = 1.0

# How many consecutive failed checks an item needs before we send a
# "check is failing" alert. A single timeout/blip is normal noise; only
# a run of these means the check is actually broken.
CONSECUTIVE_FAILURE_THRESHOLD = 3

# How often to post a "still alive" heartbeat to Discord, so a silent
# monitor (crashed, or quietly failing every check) doesn't go unnoticed.
HEARTBEAT_INTERVAL_SECONDS = 3 * 60 * 60


def _is_failure(result) -> bool:
    text = f"{result.product_name} {result.note or ''}".lower()
    return any(marker in text for marker in FAILURE_MARKERS)

# Load .env file (Discord webhook, Twilio credentials)
load_dotenv()

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    """Load and validate config.json."""
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ config.json not found at {CONFIG_FILE}")
        print("   Copy config.example.json to config.json and fill it in.")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    watchlist = config.get("watchlist", [])
    if not watchlist:
        print("⚠️  Watchlist is empty. Add items to config.json.")
        sys.exit(1)

    return config


def build_retailer_instances(watchlist: list) -> dict:
    """
    Instantiate one retailer object per unique retailer type.
    This is more efficient than creating a new instance per-check.
    """
    instances = {}
    for item in watchlist:
        retailer_key = item.get("retailer")
        if not retailer_key:
            print(f"⚠️  Item missing 'retailer' field: {item.get('name', '?')}")
            continue
        if retailer_key not in instances:
            RetailerClass = RETAILER_MAP.get(retailer_key)
            if not RetailerClass:
                print(f"⚠️  Unknown retailer: '{retailer_key}' — skipping")
                continue
            try:
                instances[retailer_key] = RetailerClass()
            except EnvironmentError as e:
                print(f"⚠️  Could not initialize {retailer_key}: {e}")
    return instances


def test_alerts():
    """Fire a test alert through all channels to verify everything is configured."""
    from retailers.base import StockResult
    test_result = StockResult(
        available=True,
        retailer="TEST",
        product_name="Pokemon TCG — Test Alert (ignore this)",
        url="https://www.pokemoncenter.com",
        price=49.99,
        note="This is a test. All systems go.",
    )
    print("\n🧪 Firing test alerts through all channels...")
    fire_all(test_result)
    print("\n✅ Test complete. Check Discord, your phone, and listen for the alarm.")


def _item_id(item: dict) -> str:
    retailer_key = item.get("retailer")
    return f"{retailer_key}:{item.get('identifier', item.get('name', ''))}"


def _base_interval(item: dict, retailer, release_mode: bool, release_interval: int) -> float:
    """
    The "ideal" interval for this item, before jitter.

    - Release mode: use the global release interval, unless the item
      explicitly overrides it via "release_poll_interval_seconds".
    - Normal mode: use the item's own "poll_interval_seconds" if set,
      otherwise fall back to the retailer module's default_poll_interval.
      This is what makes polling per-retailer — Pokemon Center/Best Buy
      get hit more often than the slower, stricter retailers like Walmart.
    """
    if release_mode:
        return item.get("release_poll_interval_seconds", release_interval)
    return item.get(
        "poll_interval_seconds",
        getattr(retailer, "default_poll_interval", 60),
    )


def _jittered(interval: float) -> float:
    """Apply +/- JITTER_FRACTION randomness so checks don't lock into a
    perfectly predictable cadence (and so multiple items with the same
    base interval drift apart over time)."""
    spread = interval * JITTER_FRACTION
    return max(1.0, interval + random.uniform(-spread, spread))


def _in_drop_window(windows: list) -> bool:
    """
    Returns True if the current local time falls inside any configured
    drop_window. Windows are defined in config.json settings.drop_windows:
      {"days": ["friday", "saturday"], "start": "09:00", "end": "18:00"}
    Times are local machine time (24h format).
    """
    if not windows:
        return False
    now = datetime.now(PST)
    day_name = now.strftime("%A").lower()
    current_time = now.strftime("%H:%M")
    for window in windows:
        days = [d.lower() for d in window.get("days", [])]
        start = window.get("start", "00:00")
        end = window.get("end", "23:59")
        if day_name in days and start <= current_time <= end:
            return True
    return False


def run_monitor(config: dict, release_mode: bool = False):
    """
    Main polling loop.

    Each watchlist item is scheduled independently based on its retailer's
    polling interval (see _base_interval), with random jitter applied.
    Items start at a random offset within their first interval so the whole
    watchlist doesn't fire in one synchronized burst, and if multiple items
    for the *same* retailer become due at the same tick, a short randomized
    delay is inserted between their requests (INTER_ITEM_DELAY_RANGE) so we
    never hammer one site with simultaneous requests.
    """
    watchlist = config["watchlist"]
    settings = config.get("settings", {})
    release_interval = settings.get("release_mode_interval_seconds", 10)
    drop_windows = settings.get("drop_windows", [])

    # Track which items are already known to be in stock
    # so we don't spam alerts every poll cycle
    alerted: set = set()

    # Track which items are currently in a "failing" state (sitemap/API
    # errors, timeouts, etc.) so we alert once on failure and once on recovery
    failing: set = set()

    # Consecutive failed-check counters per item, so a single transient
    # blip doesn't trigger a "FAILING" alert (see CONSECUTIVE_FAILURE_THRESHOLD)
    failure_counts: dict = {}

    # Last time we posted a heartbeat to Discord
    last_heartbeat = time.monotonic()

    retailer_instances = build_retailer_instances(watchlist)

    # Build the per-item schedule. `next_check[item_id]` is a monotonic
    # timestamp; items start at a random point within their first interval
    # so retailers naturally fan out instead of all firing at t=0.
    now = time.monotonic()
    next_check: dict = {}
    valid_items = []
    for item in watchlist:
        retailer_key = item.get("retailer")
        retailer = retailer_instances.get(retailer_key)
        if not retailer:
            continue
        valid_items.append(item)
        item_id = _item_id(item)
        base = _base_interval(item, retailer, release_mode, release_interval)
        next_check[item_id] = now + random.uniform(0, base)

    RETAILER_LABELS = {
        "amazon": "Amazon",
        "best_buy": "Best Buy",
        "target": "Target",
        "walmart": "Walmart",
        "pokemon_center": "Pokemon Center",
        "pokemon_center_sitemap": "Pokemon Center",
        "premium_bandai": "Bandai",
        "premium_bandai_series": "Bandai",
        "plaza_japan": "Plaza Japan",
        "square_enix": "Square Enix",
    }

    mode_label = "🚀 RELEASE MODE" if release_mode else "📡 Normal mode"
    print(f"\n{'='*60}")
    print(f"  Retail Drop Monitor — {mode_label}")
    print(f"  Watching {len(valid_items)} item(s)")

    # Group items by retailer label for cleaner display
    from collections import defaultdict
    grouped = defaultdict(list)
    for item in valid_items:
        retailer_key = item.get("retailer")
        retailer = retailer_instances.get(retailer_key)
        base = _base_interval(item, retailer, release_mode, release_interval)
        label = RETAILER_LABELS.get(retailer_key, retailer_key)
        grouped[label].append((item, base))

    for label, entries in grouped.items():
        print(f"\n  {label.upper()}")
        for item, base in entries:
            print(f"    · {item.get('name', '?')} — ~{base:.0f}s")
            print(f"      {item.get('url', '')}")

    print(f"\n  Press Ctrl+C to stop")
    print(f"{'-'*60}")
    print(f"  Quick reference:")
    print(f"    cd ~/Documents/retail-drop-monitor")
    print(f"    source venv/bin/activate             # do this first, every new terminal")
    print(f"    python3 monitor.py                  # normal mode (this)")
    print(f"    python3 monitor.py --release-mode   # 10s polling during a known drop")
    print(f"    python3 monitor.py --test-alerts    # fire a test alert on all channels")
    print(f"{'='*60}\n")

    # Tracks the last time each retailer key was actually hit, so we can
    # space out same-tick checks for the same retailer.
    last_retailer_check: dict = {}

    while True:
        now = time.monotonic()
        due_items = [item for item in valid_items if next_check[_item_id(item)] <= now]

        # Check due items in schedule order so the oldest-overdue goes first
        due_items.sort(key=lambda item: next_check[_item_id(item)])

        # Auto release mode — kick into fast polling during configured drop windows
        effective_release = release_mode or _in_drop_window(drop_windows)

        for item in due_items:
            retailer_key = item.get("retailer")
            retailer = retailer_instances.get(retailer_key)
            item_id = _item_id(item)

            # Stagger: if we just hit this same retailer, wait a bit before
            # the next request to it.
            last_hit = last_retailer_check.get(retailer_key)
            if last_hit is not None:
                gap = random.uniform(*INTER_ITEM_DELAY_RANGE)
                elapsed = time.monotonic() - last_hit
                if elapsed < gap:
                    time.sleep(gap - elapsed)

            timestamp = datetime.now(PST).strftime("%m/%d %H:%M:%S PST")

            try:
                result = retailer.check_availability(item)
            except Exception as e:
                print(f"[{timestamp}]   ⚠️  Error checking {item.get('name', '?')}: {e}")
                failure_counts[item_id] = failure_counts.get(item_id, 0) + 1
                if (
                    item_id not in failing
                    and failure_counts[item_id] >= CONSECUTIVE_FAILURE_THRESHOLD
                ):
                    failing.add(item_id)
                    discord_webhook.send_status_alert(
                        retailer=retailer_key,
                        product_name=item.get("name", "?"),
                        url=item.get("url", ""),
                        note=f"Unhandled error (x{failure_counts[item_id]}): {e}",
                        recovered=False,
                    )
                last_retailer_check[retailer_key] = time.monotonic()
                base = _base_interval(item, retailer, effective_release, release_interval)
                next_check[item_id] = time.monotonic() + _jittered(base)
                continue

            price_str = f"${result.price:.2f}" if result.price else ""
            if result.available:
                print(f"[{timestamp}]   ✅ [{result.retailer}] {result.product_name} {price_str}")
                if result.note:
                    print(f"     → {result.note}")

            # Track failure/recovery transitions and alert once on each.
            # A single bad check just increments a counter — only
            # CONSECUTIVE_FAILURE_THRESHOLD in a row triggers an alert, so
            # one timeout/blip doesn't page anyone.
            is_fail = _is_failure(result)
            was_failing = item_id in failing

            if is_fail:
                failure_counts[item_id] = failure_counts.get(item_id, 0) + 1
            else:
                failure_counts[item_id] = 0

            if (
                is_fail
                and not was_failing
                and failure_counts[item_id] >= CONSECUTIVE_FAILURE_THRESHOLD
            ):
                failing.add(item_id)
                print(f"[{timestamp}]   🚨 [{result.retailer}] {item.get('name', '?')} check is now FAILING")
                discord_webhook.send_status_alert(
                    retailer=result.retailer,
                    product_name=item.get("name", result.product_name),
                    url=result.url,
                    note=f"{result.note} (failed {failure_counts[item_id]}x in a row)",
                    recovered=False,
                )
            elif not is_fail and was_failing:
                failing.discard(item_id)
                print(f"[{timestamp}]   ✅ [{result.retailer}] {item.get('name', '?')} check has RECOVERED")
                discord_webhook.send_status_alert(
                    retailer=result.retailer,
                    product_name=item.get("name", result.product_name),
                    url=result.url,
                    note="Check is working normally again.",
                    recovered=True,
                )

            # Fire alerts if newly in stock
            if result.available and item_id not in alerted:
                alerted.add(item_id)
                # For sitemap detections, send an extra direct Discord ping
                # so the new product notification is never lost after a failure alert
                if retailer_key == "pokemon_center_sitemap":
                    discord_webhook.send_status_alert(
                        retailer="Pokémon Center (Sitemap)",
                        product_name="NEW PRODUCT DETECTED — go now",
                        url=result.url,
                        note=result.note,
                        recovered=False,
                    )
                fire_all(result)
            elif not result.available and item_id in alerted:
                # Item went back out of stock — reset so we alert again next drop
                alerted.discard(item_id)
                print(f"  ↩️  [{result.retailer}] {result.product_name} is back out of stock")

            # Reschedule — re-check drop window each time so fast polling
            # kicks in or out automatically as time windows open/close
            effective_release = release_mode or _in_drop_window(drop_windows)
            last_retailer_check[retailer_key] = time.monotonic()
            base = _base_interval(item, retailer, effective_release, release_interval)
            next_check[item_id] = time.monotonic() + _jittered(base)

        # Periodic "still alive" heartbeat — catches the monitor having
        # silently died or hung without anyone noticing for a day.
        if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            pst_hour = datetime.now(PST).hour
            if not (2 <= pst_hour < 6) and not (13 <= pst_hour < 17):
                discord_webhook.send_heartbeat(valid_items, failing)
            last_heartbeat = time.monotonic()

        time.sleep(TICK_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Retail Drop Monitor")
    parser.add_argument(
        "--release-mode",
        action="store_true",
        help="Poll every 10 seconds (use during known drop windows)",
    )
    parser.add_argument(
        "--test-alerts",
        action="store_true",
        help="Fire a test alert through all channels and exit",
    )
    args = parser.parse_args()

    if args.test_alerts:
        test_alerts()
        return

    config = load_config()

    try:
        run_monitor(config, release_mode=args.release_mode)
    except KeyboardInterrupt:
        print("\n\n👋 Monitor stopped.")


if __name__ == "__main__":
    main()
