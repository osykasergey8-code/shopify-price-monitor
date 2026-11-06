"""PNG charts from real collected data: for the portfolio and client updates."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .report import price_history_table, store_overview, top_movers  # noqa: E402

PALETTE = ["#2563EB", "#16A34A", "#DC2626", "#D97706", "#7C3AED"]


def _style(ax, title: str):
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", color="#1F2A44", pad=14)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#CCCCCC")
    ax.spines["bottom"].set_color("#CCCCCC")
    ax.tick_params(colors="#555555")
    ax.grid(axis="y", color="#EEEEEE")
    ax.set_axisbelow(True)


def price_history_png(history: pd.DataFrame, out: Path) -> Path | None:
    if history["run_id"].nunique() < 2:
        return None
    movers = top_movers(history)
    if movers.empty:
        return None
    fig, ax = plt.subplots(figsize=(12, 6), dpi=150)
    for i, (name, row) in enumerate(movers.iterrows()):
        label = name if len(name) <= 55 else name[:53] + "…"
        ax.plot(list(row.index), row.values, marker="o", lw=2.2,
                color=PALETTE[i % len(PALETTE)], label=label)
    _style(ax, "Biggest competitor price moves")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:,.0f}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def changes_summary_png(changes: pd.DataFrame, out: Path) -> Path | None:
    if changes.empty:
        return None
    order = ["Price drop", "Price increase", "Back in stock", "Out of stock", "New product", "Removed"]
    colors = ["#16A34A", "#DC2626", "#16A34A", "#DC2626", "#2563EB", "#888888"]
    counts = changes["change"].value_counts().reindex(order, fill_value=0)
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    bars = ax.barh(order[::-1], counts.values[::-1], color=colors[::-1])
    ax.bar_label(bars, padding=4, color="#333333", fontsize=11)
    _style(ax, "Changes detected since last check")
    ax.grid(axis="x", color="#EEEEEE")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def store_overview_png(curr: pd.DataFrame, out: Path) -> Path:
    ov = store_overview(curr).sort_values("Variants")
    fig, ax = plt.subplots(figsize=(11, 0.75 * len(ov) + 1.8), dpi=150)
    y = range(len(ov))
    h = 0.38
    b1 = ax.barh([i + h / 2 for i in y], ov["On sale"] * 100, height=h, color="#16A34A",
                 label="Variants on sale")
    b2 = ax.barh([i - h / 2 for i in y], ov["Out of stock"] * 100, height=h, color="#DC2626",
                 label="Variants out of stock")
    ax.bar_label(b1, fmt="%.0f%%", padding=3, fontsize=9, color="#333333")
    ax.bar_label(b2, fmt="%.0f%%", padding=3, fontsize=9, color="#333333")
    ax.set_yticks(list(y), [f"{s}  ({n:,} variants)" for s, n in zip(ov["Store"], ov["Variants"])])
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    _style(ax, "Competitor snapshot: discounts and stock")
    ax.grid(axis="x", color="#EEEEEE")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def build_charts(history: pd.DataFrame, changes: pd.DataFrame, folder: str | Path,
                 curr: pd.DataFrame | None = None) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    made = [price_history_png(history, folder / "chart_price_history.png"),
            changes_summary_png(changes, folder / "chart_changes.png")]
    if curr is not None and len(curr):
        made.append(store_overview_png(curr, folder / "chart_store_overview.png"))
    return [p for p in made if p]


__all__ = ["build_charts", "price_history_table"]
