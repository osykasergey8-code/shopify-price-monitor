"""Command line:

    python -m price_monitor check    # test that every store in config.yaml answers
    python -m price_monitor run      # scrape -> save -> compare -> Excel (+ Telegram / Sheets)
    python -m price_monitor report   # rebuild the Excel report from saved history
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .charts import build_charts
from .compare import detect_changes
from .notify import export_google_sheets, format_alert, send_telegram
from .report import build_excel, default_report_name
from .scraper import scrape_store
from .storage import Storage

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("price_monitor")


def load_env(path: Path) -> None:
    """Minimal .env loader (KEY=value lines), no extra dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg.get("stores"):
        sys.exit("config.yaml: add at least one store under 'stores:'")
    return cfg


def cmd_check(cfg: dict) -> None:
    import requests

    from .scraper import USER_AGENT, normalize_store_url
    for s in cfg["stores"]:
        url = normalize_store_url(s["url"]) + "/products.json?limit=1"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            ok = r.ok and "products" in r.json()
            print(f"{'OK  ' if ok else 'FAIL'}  {s['name']:<25} {url}  (HTTP {r.status_code})")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {s['name']:<25} {url}  ({exc.__class__.__name__})")


def make_report(storage: Storage, cfg: dict, notify: bool) -> None:
    runs = storage.run_ids()
    if not runs:
        sys.exit("No data yet. Run: python -m price_monitor run")
    curr = storage.snapshot(runs[-1])
    prev = storage.snapshot(runs[-2]) if len(runs) > 1 else curr.iloc[0:0]
    changes = detect_changes(prev, curr)
    history = storage.history()

    out_dir = ROOT / cfg.get("output_dir", "reports")
    xlsx = build_excel(history, curr, changes, default_report_name(out_dir),
                       title=cfg.get("report_title", "Competitor Price Monitor"))
    pngs = build_charts(history, changes, out_dir, curr=curr)
    log.info("Excel report: %s", xlsx)
    for p in pngs:
        log.info("Chart: %s", p)
    log.info("%s variants, %s changes", len(curr), len(changes))

    if notify:
        if len(runs) > 1:
            send_telegram(format_alert(changes))
        export_google_sheets(curr, changes, history)


def cmd_run(cfg: dict, storage: Storage) -> None:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    collected = []
    for s in cfg["stores"]:
        try:
            collected.append(scrape_store(s["name"], s["url"], delay=cfg.get("delay_seconds", 1.5)))
        except Exception as exc:  # noqa: BLE001 - one broken store must not stop the run
            log.error("%s failed: %s", s["name"], exc)
    rows = [r for store_rows in collected for r in store_rows]
    if not rows:
        sys.exit("No data collected. Check the store URLs with: python -m price_monitor check")
    run_id = storage.new_run(started)
    storage.save(run_id, rows)
    log.info("Run %s saved: %s variants", run_id, len(rows))
    make_report(storage, cfg, notify=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="price_monitor", description="Shopify competitor price monitor")
    parser.add_argument("command", choices=["check", "run", "report"])
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    load_env(ROOT / ".env")
    cfg = load_config(Path(args.config))
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "monitor.log", encoding="utf-8")])

    if args.command == "check":
        cmd_check(cfg)
        return
    storage = Storage(ROOT / cfg.get("database", "data/prices.db"))
    try:
        if args.command == "run":
            cmd_run(cfg, storage)
        else:
            make_report(storage, cfg, notify=False)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
