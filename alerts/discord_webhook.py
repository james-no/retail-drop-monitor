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

    # Color: green for solid in-stock, orange if the note suggests limited
    # stock (grab it fast, but it's not a full restock), gold for sitemap hits
    note_lower = (result.note or "").lower()
    if "sitemap" in result.retailer.lower():
        color = 0xFFD700
    elif "limited" in note_lower or "low stock" in note_lower:
        color = 0xFFA500
    else:
        color = 0x00FF00

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


def send_status_alert(retailer: str, product_name: str, url: str, note: str, recovered: bool) -> bool:
    """
    Sends a Discord embed reporting that a check started failing, or that
    it recovered after previously failing. Used so monitor problems don't
    sit silently in the terminal.

    Returns True on success, False on failure.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  [Discord] Skipped — DISCORD_WEBHOOK_URL not set")
        return False

    timestamp = datetime.utcnow().isoformat() + "Z"

    if recovered:
        title = f"✅ {retailer} — check recovered"
        color = 0x00FF00
        description = f"**{product_name}**\nThis check is working again."
    else:
        title = f"⚠️ {retailer} — check is failing"
        color = 0xFF0000
        description = f"**{product_name}**\nThe monitor cannot reliably check this item right now."

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "url": url,
        "fields": [
            {"name": "📝 Detail", "value": note or "(no detail)", "inline": False},
        ],
        "footer": {"text": "Retail Drop Monitor — status update"},
        "timestamp": timestamp,
    }

    # Add a content message so this triggers a phone push notification
    # even if the channel's notification settings are "Only @mentions"
    if recovered:
        content = "✅ Monitor check recovered"
    else:
        content = "@everyone ⚠️ Monitor check is failing — see below"

    payload = {"content": content, "embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"  [Discord] ✅ Status alert sent")
        return True
    except requests.RequestException as e:
        print(f"  [Discord] ❌ Status alert failed: {e}")
        return False


def send_heartbeat(items: list, failing: set) -> bool:
    """
    Sends a low-key "still running" heartbeat once a day. This is the only
    alert that doesn't @everyone — it's just a periodic confirmation that
    the monitor process is alive and looping, so a silent crash or a check
    that's been quietly failing below the alert threshold doesn't go
    unnoticed for days.

    Returns True on success, False on failure.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return False

    timestamp = datetime.utcnow().isoformat() + "Z"
    ok_count = len(items) - len(failing)

    description = f"Watching **{len(items)}** item(s) · {ok_count} OK"
    if failing:
        description += f" · {len(failing)} currently failing"

    embed = {
        "title": "💓 Retail Drop Monitor — heartbeat",
        "description": description,
        "color": 0x5865F2,
        "footer": {"text": "Posted once every 24h to confirm the monitor is alive"},
        "timestamp": timestamp,
    }

    payload = {"embeds": [embed]}

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"  [Discord] ✅ Heartbeat sent")
        return True
    except requests.RequestException as e:
        print(f"  [Discord] ❌ Heartbeat failed: {e}")
        return False
