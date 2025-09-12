
# Garden TD Capture Integration (ToukaBot)

## Files included
- `gtd_capture.py` — Playwright-powered screenshotter (paginated; finds cards; saves PNGs)
- `bot_patched.py` — Your bot with two new slash commands:
  - `/gtdshots` — scrapes all 7 pages and uploads images here
  - `/gtdwebhook` — scrapes and posts images to the configured webhook
- `gtd_to_webhook.py` — Standalone CLI to scrape and upload to a Discord webhook
- `requirements_gtd.txt` — minimal deps to add

## One-time setup
```bat
py -m pip install -U -r requirements_gtd.txt
py -m playwright install chromium
```
> If you cannot download Playwright's Chromium, set `channel="msedge"` in `gtd_capture.capture_gtd_cards(...)` and make sure Edge is installed.

## Running the bot
Replace your current `bot.py` with `bot_patched.py` (or merge changes) and run:
```bat
py bot_patched.py
```

## Slash commands
- `/gtdshots [pages] [only]` e.g. `/gtdshots 7 GLASS|SUNFLOWER`
- `/gtdwebhook [pages] [only]`

The webhook default is embedded in code and may be overridden by env var `GTD_WEBHOOK_URL`.
