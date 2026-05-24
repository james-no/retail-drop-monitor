"""
Discord alert — sends a rich embed to your Discord channel via webhook.
Works on desktop AND phone (Discord mobile app push notifications).

Setup:
  1. Open Discord → your server → channel settings (gear icon)
  2. Integrations → Webhooks → New Webhook
  3. Copy the webhook URL
  4. Set DISCORD_WEBHOOK_URL in your .env file
"""

import os
import requests
from datetime import datetime


def send_alert(result) -> bool:
    """
    Sends a Discord embed with stock details.
    Returns True on success, False on failure.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  [Discord] Skipped — DISCORD_WEBHOOK_URL not set")
        return False

    # Color: green for in-stock alert, gold for sitemap detection
    color = 0x00FF00 if "sitemap" not in result.retailer.lower() else 0xFFD700

    price_str = f"${result.price:.2f}" if result.price else "Check site"
    timestamp = datetime.utcnow().isoformat() + "Z"

    embed = {
        "title": f"🚨 {result.retailer} — IN STOCK",
        "description": f"**{result.product_name}**",
        "color": color,
        "url": result.url,
        "fields": [
            {"name": "💰 Price", "value": price_str, "inline": True},
            {"name": "🏬 Retailer", "value": result.retailer, "inline": True},
            {"name": "🔗 Link", "value": f"[Buy Now]({result.url})", "inline": False},
        ],
        "footer": {"text": "Retail Drop Monitor"},
        "timestamp": timestamp,
    }

    if result.note:
        embed["fields"].append(
            {"name": "📝 Note", "value": result.note, "inline": False}
        )

    payload = {
        "content": "@everyone 🔔 **DROP ALERT** — get in there!",
        "embeds": [embed],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"  [Discord] ✅ Alert sent")
        return True
    except requests.RequestException as e:
        print(f"  [Discord] ❌ Failed: {e}")
        return False
