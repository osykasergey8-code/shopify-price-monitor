# Shopify Competitor Price Monitor

Tracks prices, discounts and stock of competitor Shopify stores every day and turns the changes into a client-ready Excel report, with optional Telegram alerts and Google Sheets sync.

**What the client gets every morning**

- **Dashboard** with stores tracked, price drops, price increases, out-of-stock items and a chart of the biggest price moves
- **Changes** tab: every price drop, increase, stock change, new or removed product, colour-coded, with old/new price and % difference
- **Current Prices** tab: every product variant with price, compare-at price, discount %, stock status and link
- **Price History** tab: one row per variant, one column per day
- Telegram message with the top changes (optional)
- The same tables in Google Sheets (optional)

## How it works

```
config.yaml (stores) → scraper (public /products.json feed) → SQLite history
                     → compare with previous run → Excel + PNG charts → Telegram / Google Sheets
```

- Uses only the public product feed every Shopify store exposes. No login, no private data.
- Polite by design: pause between pages, retries with backoff, respects HTTP 429 `Retry-After`.
- One broken store never stops the run; errors are logged in `logs/monitor.log`.
- Every run is stored, so the full price history is always available.

## Quick start (Windows)

1. Install Python 3.10+ from python.org (tick "Add to PATH").
2. Double-click `setup.bat`.
3. Edit `config.yaml` with the stores to watch, then double-click `check.bat` to test them.
4. Double-click `run.bat`. The report opens in `reports/`.
5. Double-click `schedule.bat` to run it every day at 08:00.

macOS / Linux:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m price_monitor check
python -m price_monitor run
# daily at 08:00:  0 8 * * * cd /path/to/project && .venv/bin/python -m price_monitor run
```

## Optional outputs

Copy `.env.example` to `.env` and fill in:

| Setting | What for |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alert with the top changes after each run |
| `GOOGLE_CREDENTIALS`, `GOOGLE_SHEET_ID` | Sync tables to a Google Sheet (`pip install gspread`, share the sheet with the service-account email) |

## Commands

| Command | Does |
|---|---|
| `python -m price_monitor check` | Tests that every store in `config.yaml` answers |
| `python -m price_monitor run` | Scrape → save → compare → report → alerts |
| `python -m price_monitor report` | Rebuild the report from saved history |

## Tests

```bash
pip install pytest && python -m pytest -q
```

## Stack

Python · requests · pandas · SQLite · openpyxl · matplotlib · Telegram Bot API · Google Sheets API
