"""Sector labels for stocks outside NSE's index lists.

NSE's Total Market list labels only ~750 stocks. For the rest we ask Yahoo
Finance (yfinance `Ticker.info`) for sector + industry and map them onto NSE's
own sector names, so the dashboard and the sector-breadth signal use ONE
taxonomy. Results are cached in data/sector_cache.csv, and each nightly run
looks up at most SECTOR_FETCH_LIMIT new stocks (today's 52-week hits first),
so the whole universe is covered within a few nights without slowing the job.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd

import config
from scanner import storage

log = logging.getLogger(__name__)

UNCLASSIFIED = "Unclassified"
CACHE_COLUMNS = ["yahoo", "sector", "industry", "fetched_at"]

# Yahoo industry keywords -> NSE sector (checked in order, first match wins)
INDUSTRY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("auto",), "Automobile and Auto Components"),
    (("textile", "apparel", "footwear"), "Textiles"),
    (("steel", "aluminum", "aluminium", "copper", "metal", "mining", "gold", "silver"), "Metals & Mining"),
    (("building materials", "cement"), "Construction Materials"),
    (("engineering & construction", "infrastructure operations"), "Construction"),
    (("real estate",), "Realty"),
    (("paper", "lumber", "forest"), "Forest Materials"),
    (("entertainment", "broadcasting", "publishing", "advertising"), "Media Entertainment & Publication"),
    (("telecom",), "Telecommunication"),
    (("drug", "pharma", "biotech", "medical", "diagnostics", "healthcare"), "Healthcare"),
    (("software", "information technology", "computer", "semiconductor", "electronic components"), "Information Technology"),
    (("bank", "credit", "insurance", "capital markets", "asset management", "financial", "mortgage"), "Financial Services"),
    (("oil", "gas", "coal"), "Oil Gas & Consumable Fuels"),
    (("utilities", "renewable", "solar"), "Power"),
    (("chemical", "agricultural inputs", "fertilizer"), "Chemicals"),
    (("furnishings", "appliances", "consumer electronics", "luxury", "home improvement"), "Consumer Durables"),
    (("airline", "trucking", "shipping", "railroad", "freight", "airport", "logistics",
      "staffing", "consulting", "education", "business services", "rental"), "Services"),
    (("lodging", "restaurant", "resort", "leisure", "travel", "gambling", "department store",
      "retail", "internet retail"), "Consumer Services"),
    (("farm products", "packaged foods", "beverages", "tobacco", "household", "personal products",
      "confectioner", "food distribution", "grocery"), "Fast Moving Consumer Goods"),
    (("electrical equipment", "machinery", "aerospace", "defense", "industrial", "tools",
      "pollution", "security & protection", "metal fabrication"), "Capital Goods"),
    (("conglomerate",), "Diversified"),
]

# fallback when no industry keyword matches
SECTOR_RULES = {
    "technology": "Information Technology",
    "healthcare": "Healthcare",
    "financial services": "Financial Services",
    "real estate": "Realty",
    "utilities": "Power",
    "energy": "Oil Gas & Consumable Fuels",
    "communication services": "Telecommunication",
    "industrials": "Capital Goods",
    "basic materials": "Chemicals",
    "consumer cyclical": "Consumer Services",
    "consumer defensive": "Fast Moving Consumer Goods",
}


def map_to_nse_sector(yahoo_sector: str | None, yahoo_industry: str | None) -> str:
    ind = (yahoo_industry or "").lower()
    if ind:
        for keys, sector in INDUSTRY_RULES:
            if any(k in ind for k in keys):
                return sector
    return SECTOR_RULES.get((yahoo_sector or "").strip().lower(), UNCLASSIFIED)


def _yahoo_info(ticker: str) -> dict:
    import yfinance as yf  # lazy: tests and the app don't need it for this module

    try:
        info = yf.Ticker(ticker).info or {}
        return {"sector": info.get("sector"), "industry": info.get("industry")}
    except Exception as exc:  # throttling, delisted, network
        log.debug("info failed for %s: %s", ticker, exc)
        return {"sector": None, "industry": None}


def read_cache() -> pd.DataFrame:
    df = storage.read_csv(storage.data_dir() / "sector_cache.csv")
    if df is None:
        return pd.DataFrame(columns=CACHE_COLUMNS)
    return df.reindex(columns=CACHE_COLUMNS)


def fill_sectors(universe: pd.DataFrame, priority: list[str] | None = None,
                 limit: int = config.SECTOR_FETCH_LIMIT, fetcher=_yahoo_info,
                 workers: int = 4, now: datetime | None = None) -> pd.DataFrame:
    """Return the universe with 'Unclassified' sectors filled from the cache and new lookups."""
    now = now or datetime.now(config.IST)
    uni = universe.copy()
    if "industry" not in uni.columns:
        uni["industry"] = None
    cache = read_cache()

    # 1. apply cached answers
    cached = cache.set_index("yahoo")
    known = uni["sector"].eq(UNCLASSIFIED) & uni["yahoo"].isin(cached.index)
    if known.any():
        hit = cached.loc[uni.loc[known, "yahoo"]]
        uni.loc[known, "sector"] = hit["sector"].fillna(UNCLASSIFIED).to_numpy()
        uni.loc[known, "industry"] = hit["industry"].to_numpy()

    # 2. look up the rest (skip ones tried in the last 30 days)
    fetched = pd.to_datetime(cache["fetched_at"], errors="coerce", utc=True)
    recent = set(cache.loc[fetched > pd.Timestamp(now - timedelta(days=30)).tz_convert("UTC"), "yahoo"])
    todo = uni.loc[uni["sector"].eq(UNCLASSIFIED) & ~uni["yahoo"].isin(recent), "yahoo"].tolist()
    if priority:
        pri = [t for t in priority if t in set(todo)]
        todo = pri + [t for t in todo if t not in set(pri)]
    todo = todo[:max(0, limit)]
    if not todo:
        return uni

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetcher, todo))
    rows = []
    for t, r in zip(todo, results):
        sector = map_to_nse_sector(r.get("sector"), r.get("industry"))
        rows.append({"yahoo": t, "sector": sector, "industry": r.get("industry"),
                     "fetched_at": now.isoformat(timespec="seconds")})
    new = pd.DataFrame(rows, columns=CACHE_COLUMNS)
    cache = pd.concat([cache[~cache["yahoo"].isin(new["yahoo"])], new], ignore_index=True)
    storage.write_csv(cache, storage.data_dir() / "sector_cache.csv")

    by = new.set_index("yahoo")
    mask = uni["yahoo"].isin(by.index)
    uni.loc[mask, "sector"] = by.loc[uni.loc[mask, "yahoo"], "sector"].to_numpy()
    uni.loc[mask, "industry"] = by.loc[uni.loc[mask, "yahoo"], "industry"].to_numpy()
    n_ok = int((new["sector"] != UNCLASSIFIED).sum())
    log.info("sector lookup: %d/%d classified; %d still unclassified in universe",
             n_ok, len(new), int(uni["sector"].eq(UNCLASSIFIED).sum()))
    return uni
