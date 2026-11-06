"""Build a client-ready Excel report: dashboard, changes, current prices, price history."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY = "1F2A44"
GREEN = "E3F4E8"
GREEN_TXT = "1E7B3A"
RED = "FBE5E3"
RED_TXT = "B3261E"
GREY = "F4F5F7"
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
THIN = Border(bottom=Side(style="thin", color="DDDDDD"))

CHANGE_STYLE = {
    "Price drop": (GREEN, GREEN_TXT),
    "Back in stock": (GREEN, GREEN_TXT),
    "Price increase": (RED, RED_TXT),
    "Out of stock": (RED, RED_TXT),
    "New product": ("E8F0FE", "1A56B0"),
    "Removed": (GREY, "555555"),
}


def _write_table(ws, df: pd.DataFrame, start_row: int = 1, widths: dict | None = None):
    for c, name in enumerate(df.columns, 1):
        cell = ws.cell(row=start_row, column=c, value=name)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for r, row in enumerate(df.itertuples(index=False), start_row + 1):
        for c, value in enumerate(row, 1):
            if isinstance(value, float) and pd.isna(value):
                value = None
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = THIN
    ws.row_dimensions[start_row].height = 22
    ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if len(df):
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(df.columns))}{start_row + len(df)}"
    for c, name in enumerate(df.columns, 1):
        width = (widths or {}).get(name)
        if width is None:
            longest = max([len(str(name))] + [len(str(v)) for v in df[name].head(200)])
            width = min(max(10, longest + 2), 60)
        ws.column_dimensions[get_column_letter(c)].width = width


def _fmt(ws, df: pd.DataFrame, col: str, number_format: str, start_row: int = 1):
    if col not in df.columns:
        return
    letter = get_column_letter(list(df.columns).index(col) + 1)
    for r in range(start_row + 1, start_row + len(df) + 1):
        ws[f"{letter}{r}"].number_format = number_format


def _pretty_changes(changes: pd.DataFrame) -> pd.DataFrame:
    df = changes.rename(columns={
        "change": "Change", "store": "Store", "title": "Product", "variant_title": "Variant",
        "old_price": "Old price", "new_price": "New price", "diff": "Diff",
        "diff_pct": "Diff %", "available": "In stock", "url": "URL"})
    df["In stock"] = df["In stock"].map({True: "Yes", False: "No"})
    return df


def _pretty_current(curr: pd.DataFrame) -> pd.DataFrame:
    df = curr[["store", "title", "variant_title", "sku", "price", "compare_at_price",
               "available", "url"]].copy()
    df["discount"] = ((df["compare_at_price"] - df["price"]) / df["compare_at_price"]).where(
        df["compare_at_price"] > df["price"])
    df["available"] = df["available"].map({1: "Yes", 0: "No", True: "Yes", False: "No"})
    df = df[["store", "title", "variant_title", "sku", "price", "compare_at_price",
             "discount", "available", "url"]]
    df.columns = ["Store", "Product", "Variant", "SKU", "Price", "Compare at",
                  "Discount", "In stock", "URL"]
    return df.sort_values(["Store", "Product", "Variant"]).reset_index(drop=True)


def price_history_table(history: pd.DataFrame) -> pd.DataFrame:
    """One row per variant (keyed by store + variant id, so equal names never merge)."""
    h = history.copy()
    h["variant_title"] = h["variant_title"].fillna("")
    h["date"] = pd.to_datetime(h["scraped_at"]).dt.strftime("%Y-%m-%d")
    labels = (h.sort_values("run_id").groupby(["store", "variant_id"]).last()
              .apply(lambda r: f"{r.name[0]} | {r['title']}"
                     + (f" ({r['variant_title']})" if r["variant_title"] else ""), axis=1)
              .rename("Product"))
    pivot = h.pivot_table(index=["store", "variant_id"], columns="date", values="price",
                          aggfunc="last")
    pivot = pivot.join(labels).reset_index(drop=True)
    cols = ["Product"] + [c for c in pivot.columns if c != "Product"]
    return pivot[cols].sort_values("Product").reset_index(drop=True)


def top_movers(history: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    pivot = price_history_table(history).drop_duplicates("Product").set_index("Product")
    first, last = pivot.iloc[:, 0], pivot.iloc[:, -1]
    change = ((last - first) / first).dropna()
    change = change[change != 0]
    picks = change.abs().sort_values(ascending=False).head(n).index
    return pivot.loc[picks]


def store_overview(curr: pd.DataFrame) -> pd.DataFrame:
    """Per-store snapshot: useful from the very first run."""
    c = curr.copy()
    c["on_sale"] = c["compare_at_price"].notna() & (c["compare_at_price"] > c["price"])
    c["disc"] = ((c["compare_at_price"] - c["price"]) / c["compare_at_price"]).where(c["on_sale"])
    c["available"] = c["available"].astype(bool)
    g = c.groupby("store")
    return pd.DataFrame({
        "Store": g.size().index,
        "Variants": g.size().values,
        "Median price": g["price"].median().values,
        "On sale": g["on_sale"].mean().values,
        "Avg. discount": g["disc"].mean().values,
        "Out of stock": (1 - g["available"].mean()).values,
    }).sort_values("Variants", ascending=False).reset_index(drop=True)


def build_excel(history: pd.DataFrame, curr: pd.DataFrame, changes: pd.DataFrame,
                out_path: str | Path, title: str = "Competitor Price Monitor") -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()

    # ---------------- Dashboard ----------------
    ws = wb.active
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    for col in "BCDEFG":
        ws.column_dimensions[col].width = 19

    ws["B2"] = title
    ws["B2"].font = Font(size=20, bold=True, color=NAVY)
    last_run = pd.to_datetime(curr["scraped_at"]).max()
    ws["B3"] = f"Last update: {last_run:%d %b %Y, %H:%M} UTC   ·   Runs in history: {history['run_id'].nunique()}"
    ws["B3"].font = Font(size=11, color="666666")

    counts = changes["change"].value_counts() if len(changes) else pd.Series(dtype=int)
    drops = changes[changes["change"] == "Price drop"]
    kpis = [
        ("Stores tracked", curr["store"].nunique(), NAVY),
        ("Variants tracked", len(curr), NAVY),
        ("Price drops", int(counts.get("Price drop", 0)), GREEN_TXT),
        ("Price increases", int(counts.get("Price increase", 0)), RED_TXT),
        ("Out of stock", int(counts.get("Out of stock", 0)), RED_TXT),
        ("Avg. drop", f"{drops['diff_pct'].mean():.1%}" if len(drops) else "–", GREEN_TXT),
    ]
    for i, (label, value, color) in enumerate(kpis):
        col = get_column_letter(2 + i)
        for r in (5, 6):
            ws[f"{col}{r}"].fill = PatternFill("solid", fgColor=GREY)
        ws[f"{col}5"] = label
        ws[f"{col}5"].font = Font(size=10, color="666666")
        ws[f"{col}6"] = value
        ws[f"{col}6"].font = Font(size=22, bold=True, color=color)
        ws[f"{col}6"].alignment = Alignment(horizontal="left")
    ws.row_dimensions[6].height = 34

    ws["B8"] = "Store overview"
    ws["B8"].font = Font(size=13, bold=True, color=NAVY)
    ws.row_dimensions[8].height = 24
    ov = store_overview(curr)
    for c, name in enumerate(ov.columns, 2):
        cell = ws.cell(row=9, column=c, value=name)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
    formats = {"Median price": '"$"#,##0.00', "On sale": "0%", "Avg. discount": "0%",
               "Out of stock": "0%"}
    for r, row in enumerate(ov.itertuples(index=False), 10):
        for c, (name, value) in enumerate(zip(ov.columns, row), 2):
            if isinstance(value, float) and pd.isna(value):
                value = "–"
            cell = ws.cell(row=r, column=c, value=value)
            cell.border = THIN
            if name in formats:
                cell.number_format = formats[name]
    chart_row = 10 + len(ov) + 2
    ws.column_dimensions["B"].width = 24

    # ---------------- Changes ----------------
    wc = wb.create_sheet("Changes")
    pc = _pretty_changes(changes)
    _write_table(wc, pc, widths={"Product": 40, "URL": 50, "Change": 16})
    _fmt(wc, pc, "Old price", '"$"#,##0.00')
    _fmt(wc, pc, "New price", '"$"#,##0.00')
    _fmt(wc, pc, "Diff", '+"$"#,##0.00;-"$"#,##0.00')
    _fmt(wc, pc, "Diff %", "+0.0%;-0.0%")
    for r, change in enumerate(pc["Change"], 2):
        fill, txt = CHANGE_STYLE.get(change, (GREY, "333333"))
        for c in range(1, len(pc.columns) + 1):
            wc.cell(row=r, column=c).fill = PatternFill("solid", fgColor=fill)
        wc.cell(row=r, column=1).font = Font(bold=True, color=txt)

    # ---------------- Current prices ----------------
    wp = wb.create_sheet("Current Prices")
    pp = _pretty_current(curr)
    _write_table(wp, pp, widths={"Product": 40, "URL": 50})
    _fmt(wp, pp, "Price", '"$"#,##0.00')
    _fmt(wp, pp, "Compare at", '"$"#,##0.00')
    _fmt(wp, pp, "Discount", "0%")
    stock_col = get_column_letter(list(pp.columns).index("In stock") + 1)
    wp.conditional_formatting.add(
        f"{stock_col}2:{stock_col}{len(pp) + 1}",
        CellIsRule(operator="equal", formula=['"No"'], fill=PatternFill("solid", fgColor=RED),
                   font=Font(color=RED_TXT, bold=True)))

    # ---------------- Price history ----------------
    wh = wb.create_sheet("Price History")
    ph = price_history_table(history)
    _write_table(wh, ph, widths={"Product": 55})
    for c in range(2, len(ph.columns) + 1):
        wh.column_dimensions[get_column_letter(c)].width = 12
        for r in range(2, len(ph) + 2):
            wh.cell(row=r, column=c).number_format = '"$"#,##0.00'

    # chart of top movers: only once there is history to compare
    movers = top_movers(history) if history["run_id"].nunique() > 1 else pd.DataFrame()
    if movers.empty:
        ws.cell(row=chart_row, column=2,
                value="Price-move chart appears after the second run, once there is history to compare."
                ).font = Font(size=10, italic=True, color="888888")
        return _save(wb, out_path)
    ws.cell(row=chart_row, column=2, value="Biggest price moves this period").font = Font(
        size=13, bold=True, color=NAVY)
    ws.row_dimensions[chart_row].height = 24

    # hidden helper sheet keeps the chart live in Excel
    wd = wb.create_sheet("_chart")
    wd.sheet_state = "hidden"
    dates = list(movers.columns)
    wd.cell(row=1, column=1, value="Date")
    for j, name in enumerate(movers.index, 2):
        short = name if len(name) <= 38 else name[:36] + "…"
        wd.cell(row=1, column=j, value=short)
    for i, d in enumerate(dates, 2):
        wd.cell(row=i, column=1, value=d)
        for j, name in enumerate(movers.index, 2):
            wd.cell(row=i, column=j, value=float(movers.loc[name, d]))

    chart = LineChart()
    chart.height, chart.width = 9.5, 27
    chart.y_axis.title = "Price, $"
    chart.y_axis.number_format = '"$"#,##0'
    chart.legend.position = "b"
    data = Reference(wd, min_col=2, max_col=1 + len(movers), min_row=1, max_row=1 + len(dates))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(Reference(wd, min_col=1, min_row=2, max_row=1 + len(dates)))
    for s in chart.series:
        s.smooth = False
        s.marker.symbol = "circle"
    ws.add_chart(chart, f"B{chart_row + 1}")

    return _save(wb, out_path)


def _save(wb, out_path: Path) -> Path:
    """Save; if the file is open in Excel (locked on Windows), save a copy with the time added."""
    try:
        wb.save(out_path)
    except PermissionError:
        alt = out_path.with_name(f"{out_path.stem}_{datetime.now():%H%M}{out_path.suffix}")
        logging.getLogger(__name__).warning(
            "%s is open in Excel, saved as %s instead", out_path.name, alt.name)
        wb.save(alt)
        out_path = alt
    return out_path


def default_report_name(folder: str | Path) -> Path:
    return Path(folder) / f"price_report_{datetime.now():%Y-%m-%d}.xlsx"
