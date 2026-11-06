"""Fetch public product data from Shopify stores.

Every Shopify store exposes its public catalogue at /products.json.
No login, no HTML parsing, no anti-bot tricks: just the public JSON feed,
fetched politely (delay between pages, retries with backoff).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; PriceMonitor/1.0)"
PAGE_LIMIT = 250  # Shopify maximum per page


@dataclass
class VariantSnapshot:
    store: str
    product_id: int
    variant_id: int
    title: str
    variant_title: str
    sku: str
    price: float
    compare_at_price: float | None
    available: bool
    url: str
    scraped_at: str


def normalize_store_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_json(session: requests.Session, url: str, retries: int = 3) -> dict:
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 429:  # rate limited: wait and retry
                wait = int(resp.headers.get("Retry-After", 10 * attempt))
                log.warning("Rate limited on %s, waiting %ss", url, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries:
                raise
            log.warning("Attempt %s failed for %s: %s", attempt, url, exc)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not fetch {url}")


MAX_REAL_PRICE = 100_000  # above this it is a technical placeholder, not a product


def is_real_price(price: float) -> bool:
    """Shopify stores use $0 for bundle containers and huge numbers for hidden
    technical items (e.g. currency converters). Keep them out of the analytics."""
    return 0 < price < MAX_REAL_PRICE


def parse_products(store_name: str, base_url: str, products: list[dict],
                   scraped_at: str) -> list[VariantSnapshot]:
    rows: list[VariantSnapshot] = []
    skipped = 0
    for p in products:
        for v in p.get("variants", []):
            if not is_real_price(float(v.get("price") or 0)):
                skipped += 1
                continue
            compare = v.get("compare_at_price")
            variant_title = v.get("title") or ""
            rows.append(VariantSnapshot(
                store=store_name,
                product_id=int(p["id"]),
                variant_id=int(v["id"]),
                title=p.get("title", "").strip(),
                variant_title="" if variant_title == "Default Title" else variant_title,
                sku=v.get("sku") or "",
                price=float(v.get("price") or 0),
                compare_at_price=float(compare) if compare else None,
                available=bool(v.get("available", False)),
                url=f"{base_url}/products/{p.get('handle', '')}?variant={v['id']}",
                scraped_at=scraped_at,
            ))
    if skipped:
        log.info("%s: skipped %s technical variants ($0 or placeholder price)", store_name, skipped)
    return rows


def scrape_store(name: str, url: str, delay: float = 1.5,
                 max_pages: int = 40) -> list[VariantSnapshot]:
    base = normalize_store_url(url)
    scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    rows: list[VariantSnapshot] = []
    for page in range(1, max_pages + 1):
        data = _get_json(session, f"{base}/products.json?limit={PAGE_LIMIT}&page={page}")
        products = data.get("products", [])
        if not products:
            break
        rows.extend(parse_products(name, base, products, scraped_at))
        log.info("%s: page %s, %s products", name, page, len(products))
        time.sleep(delay)
    log.info("%s: %s variants total", name, len(rows))
    return rows
