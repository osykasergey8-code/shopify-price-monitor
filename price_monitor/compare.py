"""Compare two snapshots and classify every change."""
from __future__ import annotations

import pandas as pd

KEY = ["store", "variant_id"]
CHANGE_COLUMNS = ["change", "store", "title", "variant_title", "old_price", "new_price",
                  "diff", "diff_pct", "available", "url"]


def detect_changes(prev: pd.DataFrame, curr: pd.DataFrame) -> pd.DataFrame:
    """Return one row per change: price drop/increase, stock in/out, new/removed product."""
    if prev.empty:
        return pd.DataFrame(columns=CHANGE_COLUMNS)
    # older runs may still hold placeholder prices: never report them as "Removed"
    from .scraper import is_real_price
    prev = prev[prev["price"].apply(is_real_price)]
    curr = curr[curr["price"].apply(is_real_price)]

    merged = prev.merge(curr, on=KEY, how="outer", suffixes=("_old", "_new"), indicator=True)
    out = []
    for _, r in merged.iterrows():
        status = r["_merge"]
        side = "_new" if status != "left_only" else "_old"
        base = {
            "store": r["store"],
            "title": r[f"title{side}"],
            "variant_title": r[f"variant_title{side}"],
            "url": r[f"url{side}"],
            "old_price": r.get("price_old"),
            "new_price": r.get("price_new"),
            "available": bool(r[f"available{side}"]) if pd.notna(r[f"available{side}"]) else None,
        }
        if status == "right_only":
            out.append({**base, "change": "New product"})
            continue
        if status == "left_only":
            out.append({**base, "change": "Removed"})
            continue

        old_p, new_p = float(r["price_old"]), float(r["price_new"])
        if abs(new_p - old_p) >= 0.01:
            out.append({**base, "change": "Price drop" if new_p < old_p else "Price increase"})
        was, now = bool(r["available_old"]), bool(r["available_new"])
        if was and not now:
            out.append({**base, "change": "Out of stock"})
        elif not was and now:
            out.append({**base, "change": "Back in stock"})

    df = pd.DataFrame(out)
    if df.empty:
        return pd.DataFrame(columns=CHANGE_COLUMNS)
    df["diff"] = (df["new_price"] - df["old_price"]).round(2)
    df["diff_pct"] = (df["diff"] / df["old_price"]).round(4)
    order = {"Price drop": 0, "Back in stock": 1, "Price increase": 2,
             "Out of stock": 3, "New product": 4, "Removed": 5}
    df["_o"] = df["change"].map(order)
    df = df.sort_values(["_o", "diff_pct"]).drop(columns="_o")
    return df[CHANGE_COLUMNS].reset_index(drop=True)
