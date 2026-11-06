"""Optional outputs: Telegram alerts and Google Sheets export.

Both are switched on only when their settings exist, so the monitor
works out of the box with just Excel.
"""
from __future__ import annotations

import logging
import os

import pandas as pd
import requests

log = logging.getLogger(__name__)


def format_alert(changes: pd.DataFrame, max_lines: int = 15) -> str:
    if changes.empty:
        return "Price monitor: no changes since last run."
    icons = {"Price drop": "🟢", "Back in stock": "✅", "Price increase": "🔴",
             "Out of stock": "⛔", "New product": "🆕", "Removed": "➖"}
    lines = [f"<b>Price monitor: {len(changes)} changes</b>"]
    for _, r in changes.head(max_lines).iterrows():
        name = r["title"] + (f" ({r['variant_title']})" if r["variant_title"] else "")
        line = f"{icons.get(r['change'], '•')} {r['store']}: {name}"
        if r["change"] in ("Price drop", "Price increase"):
            line += f" — ${r['old_price']:.2f} → ${r['new_price']:.2f} ({r['diff_pct']:+.0%})"
        lines.append(line)
    if len(changes) > max_lines:
        lines.append(f"…and {len(changes) - max_lines} more in the Excel report")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("Telegram not configured, skipping alert")
        return False
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=20,
    )
    resp.raise_for_status()
    log.info("Telegram alert sent")
    return True


def export_google_sheets(curr: pd.DataFrame, changes: pd.DataFrame, history: pd.DataFrame) -> bool:
    """Write the same tabs to a Google Sheet. Needs: pip install gspread,
    a service-account JSON (GOOGLE_CREDENTIALS) and the sheet ID (GOOGLE_SHEET_ID),
    with the sheet shared to the service-account email."""
    creds = os.getenv("GOOGLE_CREDENTIALS")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not creds or not sheet_id:
        log.info("Google Sheets not configured, skipping export")
        return False
    import gspread  # optional dependency

    from .report import _pretty_changes, _pretty_current, price_history_table

    book = gspread.service_account(filename=creds).open_by_key(sheet_id)
    for tab, df in [("Changes", _pretty_changes(changes)),
                    ("Current Prices", _pretty_current(curr)),
                    ("Price History", price_history_table(history))]:
        try:
            ws = book.worksheet(tab)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = book.add_worksheet(tab, rows=len(df) + 10, cols=len(df.columns) + 2)
        values = [list(df.columns)] + df.astype(object).where(df.notna(), "").values.tolist()
        ws.update(values, "A1")
    log.info("Google Sheet updated")
    return True
