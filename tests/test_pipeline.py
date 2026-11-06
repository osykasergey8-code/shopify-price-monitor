"""Tests run without internet: the Shopify feed is replaced with a stub response."""
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from price_monitor import scraper
from price_monitor.charts import build_charts
from price_monitor.compare import detect_changes
from price_monitor.report import build_excel
from price_monitor.storage import Storage


def product(pid, title, variants):
    return {"id": pid, "title": title, "handle": title.lower().replace(" ", "-"),
            "variants": [{"id": vid, "title": vt, "sku": f"SKU{vid}", "price": price,
                          "compare_at_price": cmp, "available": av}
                         for vid, vt, price, cmp, av in variants]}


DAY1 = [product(1, "House Blend", [(11, "12 oz", "18.00", None, True), (12, "2 lb", "42.00", None, True)]),
        product(2, "Espresso Roast", [(21, "Default Title", "20.00", None, True)]),
        product(3, "Decaf", [(31, "12 oz", "17.00", None, False)])]
DAY2 = [product(1, "House Blend", [(11, "12 oz", "15.30", "18.00", True), (12, "2 lb", "42.00", None, False)]),
        product(2, "Espresso Roast", [(21, "Default Title", "22.00", None, True)]),
        product(3, "Decaf", [(31, "12 oz", "17.00", None, True)]),
        product(4, "Cold Brew Pack", [(41, "Default Title", "29.00", None, True)])]


class FakeResp:
    status_code = 200
    headers: dict = {}

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def fake_session(pages):
    class S:
        headers: dict = {}

        def get(self, url, timeout):
            page = int(url.split("page=")[1])
            return FakeResp({"products": pages if page == 1 else []})
    return S


def scrape_with(monkeypatch, pages):
    monkeypatch.setattr(scraper.requests, "Session", fake_session(pages))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    return scraper.scrape_store("Test Roasters", "teststore.com")


def test_parse_variants(monkeypatch):
    rows = scrape_with(monkeypatch, DAY1)
    assert len(rows) == 4
    espresso = next(r for r in rows if r.variant_id == 21)
    assert espresso.variant_title == ""          # "Default Title" removed
    assert espresso.url == "https://teststore.com/products/espresso-roast?variant=21"


def test_full_pipeline(monkeypatch, tmp_path: Path):
    db = Storage(tmp_path / "prices.db")
    for i, day in enumerate([DAY1, DAY2], 1):
        rows = scrape_with(monkeypatch, day)
        for r in rows:                              # different dates for the history
            r.scraped_at = f"2026-11-0{i}T08:00:00+00:00"
        db.save(db.new_run(rows[0].scraped_at), rows)

    runs = db.run_ids()
    changes = detect_changes(db.snapshot(runs[0]), db.snapshot(runs[1]))
    kinds = dict(zip(changes["title"] + "|" + changes["variant_title"].fillna(""), changes["change"]))
    assert kinds["House Blend|12 oz"] == "Price drop"
    assert kinds["House Blend|2 lb"] == "Out of stock"
    assert kinds["Espresso Roast|"] == "Price increase"
    assert kinds["Decaf|12 oz"] == "Back in stock"
    assert kinds["Cold Brew Pack|"] == "New product"
    drop = changes[changes["change"] == "Price drop"].iloc[0]
    assert drop["diff_pct"] == pytest.approx(-0.15)

    xlsx = build_excel(db.history(), db.snapshot(runs[1]), changes, tmp_path / "r.xlsx")
    wb = openpyxl.load_workbook(xlsx)
    assert {"Dashboard", "Changes", "Current Prices", "Price History"} <= set(wb.sheetnames)
    assert wb["Changes"].max_row == len(changes) + 1
    assert len(build_charts(db.history(), changes, tmp_path, curr=db.snapshot(runs[1]))) == 3


def test_skips_technical_prices(monkeypatch):
    pages = [product(7, "Currency Convert", [(71, "Default Title", "1000000000.00", None, True)]),
             product(8, "Gift Bundle", [(81, "Default Title", "0.00", None, True)]),
             product(9, "Real Coffee", [(91, "12 oz", "19.00", None, True)])]
    rows = scrape_with(monkeypatch, pages)
    assert [r.variant_id for r in rows] == [91]


def test_same_names_do_not_merge(monkeypatch, tmp_path: Path):
    pages = [product(5, "Mug", [(51, "Default Title", "10.00", None, True)]),
             product(6, "Mug", [(61, "Default Title", "12.00", None, True)])]
    db = Storage(tmp_path / "p.db")
    db.save(db.new_run("x"), scrape_with(monkeypatch, pages))
    from price_monitor.report import price_history_table
    assert len(price_history_table(db.history())) == 2


def test_first_run_report(monkeypatch, tmp_path: Path):
    db = Storage(tmp_path / "p.db")
    db.save(db.new_run("x"), scrape_with(monkeypatch, DAY1))
    curr = db.snapshot(db.run_ids()[0])
    changes = detect_changes(curr.iloc[0:0], curr)
    xlsx = build_excel(db.history(), curr, changes, tmp_path / "first.xlsx")
    assert "_chart" not in openpyxl.load_workbook(xlsx).sheetnames


def test_first_run_has_no_changes():
    empty = pd.DataFrame(columns=["store", "variant_id"])
    assert detect_changes(empty, empty).empty
