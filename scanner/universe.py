"""The stock universe: every NSE stock in series EQ/BE (~2,000+ symbols).

Sources: NSE EQUITY_L.csv for the list; NSE index lists for a sector label and
a SEBI-style market-cap bucket (Nifty 100 = Large, Midcap 150 = Mid,
Smallcap 250 = Small, everything else = Micro). The result is cached in
data/universe.csv and refreshed weekly; if NSE is unreachable the cached copy
is used.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

import config
from scanner import storage
from scanner.nse import NSEClient, NSEError

log = logging.getLogger(__name__)

UNIVERSE_COLUMNS = ["symbol", "name", "series", "isin", "yahoo", "sector", "industry", "mcap_bucket"]


def _meta_path():
    return storage.data_dir() / "universe_meta.json"


def _is_stale() -> bool:
    """File mtimes are unreliable after a git checkout, so the refresh time is stored explicitly."""
    ts = storage.read_json(_meta_path()).get("refreshed_at")
    if not ts:
        return True
    try:
        age = datetime.now(config.IST) - datetime.fromisoformat(ts)
    except ValueError:
        return True
    return age.total_seconds() > config.UNIVERSE_MAX_AGE_DAYS * 86400


def enrich(equities: pd.DataFrame, sector_list: pd.DataFrame | None,
           large: set[str], mid: set[str], small: set[str]) -> pd.DataFrame:
    df = equities.copy()
    df["yahoo"] = df["symbol"] + config.YAHOO_SUFFIX
    if sector_list is not None and not sector_list.empty:
        sec = dict(zip(sector_list["symbol"], sector_list["industry"]))
        df["sector"] = df["symbol"].map(sec)
    else:
        df["sector"] = None
    df["sector"] = df["sector"].fillna("Unclassified")
    df["industry"] = None

    def bucket(sym: str) -> str:
        if sym in large:
            return "Large"
        if sym in mid:
            return "Mid"
        if sym in small:
            return "Small"
        return "Micro"

    df["mcap_bucket"] = df["symbol"].map(bucket)
    return df[UNIVERSE_COLUMNS].drop_duplicates("symbol").reset_index(drop=True)


def build_universe(client: NSEClient | None = None) -> pd.DataFrame:
    client = client or NSEClient()
    equities = client.equity_list()

    def safe_index(name: str) -> pd.DataFrame | None:
        try:
            return client.index_list(name)
        except NSEError as exc:
            log.warning("index list %s unavailable: %s", name, exc)
            return None

    sector_list = safe_index(config.INDEX_SECTOR_LIST)
    sets = []
    for name in (config.INDEX_LARGE, config.INDEX_MID, config.INDEX_SMALL):
        lst = safe_index(name)
        sets.append(set(lst["symbol"]) if lst is not None else set())
    return enrich(equities, sector_list, *sets)


def load_universe(force_refresh: bool = False, client: NSEClient | None = None) -> pd.DataFrame:
    path = storage.universe_path()
    cached = storage.read_universe()
    if force_refresh or cached is None or _is_stale():
        try:
            uni = build_universe(client)
            storage.write_csv(uni, path)
            storage.write_json({"refreshed_at": datetime.now(config.IST).isoformat(timespec="seconds"),
                                "symbols": int(len(uni))}, _meta_path())
            log.info("universe refreshed from NSE: %d symbols", len(uni))
            return uni
        except Exception as exc:  # NSE down or blocked
            if cached is None:
                raise RuntimeError(
                    "No universe available: NSE equity list could not be downloaded and "
                    "data/universe.csv does not exist. Download EQUITY_L.csv from nseindia.com "
                    "and run `python -m scanner.universe --from-file EQUITY_L.csv`."
                ) from exc
            log.warning("universe refresh failed (%s); using cached copy (%d symbols)", exc, len(cached))
    return cached


def _main() -> None:
    import argparse
    from scanner.nse import parse_equity_list

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Build data/universe.csv")
    ap.add_argument("--from-file", help="local EQUITY_L.csv (when NSE blocks downloads)")
    args = ap.parse_args()
    if args.from_file:
        with open(args.from_file, "rb") as fh:
            eq = parse_equity_list(fh.read())
        uni = enrich(eq, None, set(), set(), set())
        storage.write_csv(uni, storage.universe_path())
    else:
        uni = load_universe(force_refresh=True)
    print(f"universe: {len(uni)} symbols -> {storage.universe_path()}")


if __name__ == "__main__":
    _main()
