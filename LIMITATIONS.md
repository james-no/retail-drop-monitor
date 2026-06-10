# Known Limitations

This project is a personal stock monitor, not a bot network. It is built to give you a heads up before a product is gone, not to guarantee a checkout.

## Speed vs. dedicated bots

During high demand drops (Pokemon Center Pitch Black, 30th Anniversary items, etc.), dedicated resale bots running on residential proxy networks can hit retailer APIs multiple times per second from many IP addresses at once. This monitor polls on a single connection every 10 to 60 seconds.

What this means in practice: you will likely be alerted to a drop, but high demand items can sell out in the seconds between polls, especially against bots. The monitor is most useful for items that are not the absolute top target, for pre-orders, restocks, and for catching unannounced drops via the sitemap watcher before most people are even looking.

Things that help:
- Run `python monitor.py --release-mode` (10 second polling) during a known drop window
- Use the Pokemon Center sitemap watcher, which can catch a product before its page is publicly live

## What went wrong during the Pitch Black drop (June 2026)

During the live drop, the terminal showed:

```
[Pokémon Center (Sitemap)] Sitemap fetch failed → Could not retrieve sitemap
[Pokémon Center] Pokemon Center — Pitch Black (10-10416-112)
[Pokémon Center] Pokemon Center — Booster Box (10-10425-120)
```

Two problems:

1. The sitemap fetch failed, but the error message gave no detail. There was no way to tell if it was a timeout, a block, or a parsing error.
2. The two Pokemon Center product checks showed nothing. The JSON API call likely got blocked (Pokemon Center increases bot detection during a live drop), the code silently fell back to checking the HTML page, found nothing conclusive, and returned a blank result.

On top of that, none of this was surfaced as an alert. Failures sat silently in the terminal where you would only see them if you happened to be watching.

## Fixes applied

- The sitemap watcher now reports the actual failure reason (HTTP status code, timeout, connection error, or XML parse failure suggesting a block page).
- Pokemon Center product checks now explain what happened when the API fails and the HTML fallback is inconclusive, including a note that the page may be a block or CAPTCHA page during high traffic.
- The monitor now sends a separate Discord alert the first time any check starts failing, and another alert the first time it recovers. These are distinct from the green "in stock" drop alerts, so you will not confuse a monitor problem with a real restock.

## Remaining limitations

- A failure alert tells you the monitor cannot reliably check an item right now. It does not tell you whether the product is actually in stock during that window. If you get a failure alert during a known drop, check the site manually.
- The HTML fallback is a best effort check based on page text ("add to cart", "sold out", etc.). Retailers can change their page wording or structure at any time, which can break this check.
- This monitor cannot complete a checkout for you. It only alerts.
