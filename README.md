# Retail Drop Monitor

**Multi-retailer stock alert system that fires the moment a product goes live — before Twitter bots, before NowInStock, before everyone else.**

Hits each retailer's **internal inventory API directly** (the same endpoint their mobile apps use), returning structured JSON with no HTML parsing and no JavaScript execution. Traditional scrapers get blocked by Akamai Bot Manager within minutes. This doesn't.

---

## What makes this different

| Approach | How it works | Bot detection risk |
|---|---|---|
| HTML scraping | Loads product page, checks button text | **High** — Akamai/Cloudflare fingerprints TLS + checks for JS execution |
| This project | Calls the retailer's internal JSON API | **Low** — same endpoint as their mobile app |

---

## Features

- **Pokémon Center sitemap watcher** — monitors 33,000+ product URLs for new additions before the drop page goes public. You get the URL the moment it's registered — minutes before any announcement.
- **Pokémon Center product check** — polls the `/api/2.0/product/{id}` endpoint with HTML fallback
- **Best Buy** — queries their internal product badging API, no developer key required
- **Target** — hits Target's internal fulfillment API (same endpoint as the Target app)
- **Walmart** — extracts inventory data from the server-rendered `__NEXT_DATA__` JSON block
- **3-channel alerts** — Discord webhook (phone + desktop), macOS native notification, and audio alarm fire simultaneously
- **Release mode** — `--release-mode` flag switches to 10-second polling during known drop windows
- **Smart deduplication** — alerts once when in-stock, resets when it goes back out. No spam.
- **Auto-restart** — macOS LaunchAgent keeps it running 24/7, restarts on crash, starts at login

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/james-no/retail-drop-monitor.git
cd retail-drop-monitor
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in:
- **Discord webhook URL** — Server Settings → Integrations → Webhooks → New Webhook → Copy URL

> **Note:** Twilio SMS credentials are optional. Discord covers phone alerts well enough via the mobile app.

> **Tip:** `.env` is a hidden file. Press **Cmd + Shift + .** in Finder to toggle hidden files.

### 3. Configure your watchlist

Edit `config.json`. Each item needs:

| Field | Description |
|---|---|
| `name` | Display name for alerts |
| `retailer` | `pokemon_center`, `pokemon_center_sitemap`, `best_buy`, `target`, `walmart` |
| `identifier` | Product ID for that retailer (see below) |
| `url` | Direct product page URL |

**Finding product IDs:**

| Retailer | Where to find the ID | Example |
|---|---|---|
| Pokémon Center | URL: `.../product/290-86189/...` | `290-86189` |
| Best Buy | URL: `.../6609999.p` | `6609999` |
| Target | URL: `.../A-1011206804` | `1011206804` |
| Walmart | URL: `.../ip/name/7534009817` | `7534009817` |

**Sitemap watcher** (special entry for catching unannounced drops):

```json
{
  "name": "Pokemon Center Sitemap — watch for new drops",
  "retailer": "pokemon_center_sitemap",
  "identifier": "sitemap",
  "url": "https://www.pokemoncenter.com/sitemap.xml",
  "keywords": ["elite-trainer", "booster-box", "premium-collection"]
}
```

The `keywords` array is optional — if set, only new URLs containing those strings will trigger an alert.

### 4. Test your alerts

```bash
python monitor.py --test-alerts
```

Fires a test notification through all configured channels without checking any products.

### 5. Run

```bash
# Normal mode — checks every 60 seconds
python monitor.py

# Release mode — checks every 10 seconds (use during known drop windows)
python monitor.py --release-mode
```

---

## Auto-start on Mac login

```bash
# Install the LaunchAgent
cp ~/Documents/retail-drop-monitor/com.jamesno.retaildropmonitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jamesno.retaildropmonitor.plist
launchctl start com.jamesno.retaildropmonitor
```

**Verify it's running:**
```bash
launchctl list | grep retaildropmonitor
# Output: <PID>  0  com.jamesno.retaildropmonitor
# Exit code 0 = clean. Anything else = check the log.
```

**Watch the log:**
```bash
tail -f ~/Documents/retail-drop-monitor/monitor.log
```

**Stop / remove:**
```bash
launchctl stop com.jamesno.retaildropmonitor
launchctl unload ~/Library/LaunchAgents/com.jamesno.retaildropmonitor.plist
```

---

## Architecture

```
monitor.py
  ├── Loads config.json (watchlist + settings)
  ├── Instantiates one retailer client per unique retailer type
  └── Polling loop:
        For each item in watchlist:
          → retailer.check_availability(item) → StockResult
          → If available AND not already alerted:
               → alerts.fire_all(result)
                    ├── Discord webhook (rich embed with price + buy link)
                    ├── macOS notification (osascript, zero dependencies)
                    └── Sound alarm (afplay Hero.aiff × 5)

retailers/
  ├── base.py              — RetailerBase + StockResult dataclass
  ├── pokemon_center.py    — Product API + sitemap index watcher
  ├── best_buy.py          — Internal badging API + HTML fallback
  ├── target.py            — Internal fulfillment API
  └── walmart.py           — __NEXT_DATA__ JSON extraction

alerts/
  ├── discord_webhook.py   — Rich embed with @everyone ping
  ├── mac_notification.py  — osascript native notification
  ├── twilio_sms.py        — Optional SMS (skips if not configured)
  └── sound.py             — afplay system sound
```

---

## Why the sitemap watcher matters

Pokémon Center registers new products in their XML sitemap **before** the drop page goes live. The sitemap watcher catches the URL the moment it appears — before the page is publicly reachable, before any Twitter account posts about it, before queue traffic peaks.

When the alert fires, you have the URL ready. When the page opens, you're ahead of the crowd.

---

## Disclaimer

For personal use only — to buy products at retail price. Not for scalping or reselling.
