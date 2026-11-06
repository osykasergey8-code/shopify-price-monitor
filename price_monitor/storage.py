"""SQLite storage: every run is saved as a snapshot, so full price history is kept."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .scraper import VariantSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    run_id           INTEGER NOT NULL,
    scraped_at       TEXT    NOT NULL,
    store            TEXT    NOT NULL,
    product_id       INTEGER NOT NULL,
    variant_id       INTEGER NOT NULL,
    title            TEXT,
    variant_title    TEXT,
    sku              TEXT,
    price            REAL,
    compare_at_price REAL,
    available        INTEGER,
    url              TEXT,
    PRIMARY KEY (run_id, store, variant_id)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variant ON snapshots (store, variant_id);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)

    def new_run(self, started_at: str) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started_at,))
        self.conn.commit()
        return int(cur.lastrowid)

    def save(self, run_id: int, rows: list[VariantSnapshot]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO snapshots VALUES
               (:run_id, :scraped_at, :store, :product_id, :variant_id, :title,
                :variant_title, :sku, :price, :compare_at_price, :available, :url)""",
            [{**asdict(r), "run_id": run_id, "available": int(r.available)} for r in rows],
        )
        self.conn.commit()

    def run_ids(self) -> list[int]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT run_id FROM snapshots ORDER BY run_id")]

    def snapshot(self, run_id: int) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM snapshots WHERE run_id = ?", self.conn, params=(run_id,))

    def history(self) -> pd.DataFrame:
        return pd.read_sql("SELECT * FROM snapshots ORDER BY run_id", self.conn)

    def close(self) -> None:
        self.conn.close()
