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
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

from retailers import RETAILER_MAP
from alerts import fire_all

# Load .env file (Discord webhook, Twilio credentials, Best Buy API key)
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


def run_monitor(config: dict, release_mode: bool = False):
    """Main polling loop."""
    watchlist = config["watchlist"]
    settings = config.get("settings", {})

    normal_interval = settings.get("poll_interval_seconds", 60)
    release_interval = settings.get("release_mode_interval_seconds", 10)
    poll_interval = release_interval if release_mode else normal_interval

    # Track which items are already known to be in stock
    # so we don't spam alerts every poll cycle
    alerted: set = set()

    retailer_instances = build_retailer_instances(watchlist)

    mode_label = "🚀 RELEASE MODE" if release_mode else "📡 Normal mode"
    print(f"\n{'='*60}")
    print(f"  Retail Drop Monitor — {mode_label}")
    print(f"  Watching {len(watchlist)} item(s) · Polling every {poll_interval}s")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    while True:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Checking {len(watchlist)} item(s)...")

        for item in watchlist:
            retailer_key = item.get("retailer")
            retailer = retailer_instances.get(retailer_key)
            if not retailer:
                continue

            item_id = f"{retailer_key}:{item.get('identifier', item.get('name', ''))}"

            try:
                result = retailer.check_availability(item)
            except Exception as e:
                print(f"  ⚠️  Error checking {item.get('name', '?')}: {e}")
                continue

            status_icon = "✅" if result.available else "⬜"
            price_str = f"${result.price:.2f}" if result.price else ""
            print(f"  {status_icon} [{result.retailer}] {result.product_name} {price_str}")

            if result.note and not result.available:
                print(f"     → {result.note}")

            # Fire alerts if newly in stock
            if result.available and item_id not in alerted:
                alerted.add(item_id)
                fire_all(result)
            elif not result.available and item_id in alerted:
                # Item went back out of stock — reset so we alert again next drop
                alerted.discard(item_id)
                print(f"  ↩️  [{result.retailer}] {result.product_name} is back out of stock")

        print(f"  Next check in {poll_interval}s...\n")
        time.sleep(poll_interval)


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
