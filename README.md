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

## Supported Retailers

| Retailer | Method | What it watches |
|---|---|---|
| **Target** | Internal fulfillment API (`api.target.com`) | Specific products by TCIN |
| **Pokémon Center** | Product API + sitemap index | Specific products + unannounced drops |
| **Best Buy** | Internal product badging API | Specific products by SKU |
| **Walmart** | `__NEXT_DATA__` JSON extraction | Specific products by item ID |
| **Premium Bandai** | Session-based `fillProductDetailFlags` API | Specific items, pre-orders, lottery openings |
| **Premium Bandai (Series)** | Series/shop content API | New arrivals across a full series or shop |

---

## Features

- **Target internal API** — hits the same fulfillment endpoint the Target app uses, no HTML parsing
- **Pokémon Center sitemap watcher** — monitors 33,000+ product URLs for new additions before the drop page goes public
- **Premium Bandai integration** — watches specific items, series listings, pre-orders, and lottery/drawing openings across p-bandai.com
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
| `retailer` | See retailer keys below |
| `identifier` | Product ID for that retailer |
| `url` | Direct product page URL |

**Finding product IDs:**

| Retailer | `retailer` key | Where to find the ID | Example |
|---|---|---|---|
| Pokémon Center | `pokemon_center` | URL: `.../product/290-86189/...` | `290-86189` |
| Pokémon Center Sitemap | `pokemon_center_sitemap` | Always `sitemap` | `sitemap` |
| Best Buy | `best_buy` | URL: `.../6609999.p` | `6609999` |
| Target | `target` | URL: `.../A-1011206804` | `1011206804` |
| Walmart | `walmart` | URL: `.../ip/name/7534009817` | `7534009817` |
| Premium Bandai (item) | `premium_bandai` | URL: `.../item/N2888744001` | `N2888744001` |
| Premium Bandai (series) | `premium_bandai_series` | `series:{id}` or `series:{id}\|shop:{id}` | `series:03-042` |

**Premium Bandai series watcher** — monitors a full series or shop for new/available products:

```json
{
  "name": "One Piece Card Game — New Drops",
  "retailer": "premium_bandai_series",
  "identifier": "series:03-002|shop:05-0004",
  "url": "https://p-bandai.com/us/series/onepiece-series?_f_shops=05-0004&_f_series=03-002"
}
```

**Pokémon Center sitemap watcher** — catches unannounced drops before they go public:

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

### 5. Run

```bash
# Normal mode — checks every 60 seconds
python monitor.py

# Release mode — checks every 10 seconds (use during known drop windows)
python monitor.py --release-mode
```

See `COMMANDS.md` for the full command reference.

---

## Auto-start on Mac login

```bash
cp ~/Documents/retail-drop-monitor/com.jamesno.retaildropmonitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jamesno.retaildropmonitor.plist
launchctl start com.jamesno.retaildropmonitor
```

**Verify it's running:**
```bash
launchctl list | grep retaildropmonitor
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
  ├── walmart.py           — __NEXT_DATA__ JSON extraction
  └── premium_bandai.py    — Session-based p-bandai.com API (items + series)

alerts/
  ├── discord_webhook.py   — Rich embed with @everyone ping
  ├── mac_notification.py  — osascript native notification
  ├── twilio_sms.py        — Optional SMS (skips if not configured)
  └── sound.py             — afplay system sound
```

---

## Why the sitemap watcher matters

Pokémon Center registers new products in their XML sitemap **before** the drop page goes live. The sitemap watcher catches the URL the moment it appears — before the page is publicly reachable, before any Twitter account posts about it, before queue traffic peaks.

---

## Disclaimer

For personal use only — to buy products at retail price. Not for scalping or reselling.
