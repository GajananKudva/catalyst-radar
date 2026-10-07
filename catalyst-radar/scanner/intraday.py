"""Intraday job (every 15 minutes, 09:15-15:45 IST).

Fetches only TODAY's bar so far (open, high, low, last price, volume) for every
stock, compares it with last night's thresholds, and updates the sticky hits
file for today. It never downloads a year of history.

Run:  python -m scanner.intraday           (exits quietly outside market hours)
      python -m scanner.intraday --force   (run anyway, e.g. for testing)
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from scanner import logic, prices, status, storage
from scanner.market_calendar import elapsed_fraction, market_phase, now_ist
import config

log = logging.getLogger("scanner.intraday")


def run(force: bool = False) -> int:
    now = now_ist()
    phase = market_phase(now)
    if not force and phase not in ("open", "closing"):
        log.info("market phase is %s; nothing to do", phase)
        return 0

    thr = storage.read_thresholds()
    if thr is None or thr.empty:
        log.error("no thresholds found - run `python -m scanner.nightly` first")
        return 1
    meta = storage.read_json(storage.meta_path())
    uni = storage.read_universe()
    tickers = thr["symbol"].tolist()

    snap, missing = prices.download_daily(tickers + [config.NIFTY_YAHOO], period="5d")
    nifty = snap[snap["symbol"] == config.NIFTY_YAHOO]
    today = pd.Timestamp(now.date())

    if nifty.empty or not (nifty["date"] == today).any():
        if not force:
            log.info("Nifty has no bar for %s (holiday or data not live yet); skipping", today.date())
            status.write_latest(job="intraday", market_state="holiday_or_no_data", session_date=today,
                                hits=storage.read_hits(today.date()), universe_size=len(tickers), scanned_ok=0,
                                thresholds_as_of=meta.get("thresholds_as_of"),
                                note="No live bar for Nifty 50 today")
            return 0
        if snap.empty:
            log.error("no data returned at all")
            return 1
        today = snap["date"].max()
        log.warning("--force: using latest available session %s", today.date())

    as_of = pd.Timestamp(meta.get("thresholds_as_of") or thr["as_of"].max())
    if as_of >= today:
        log.error("thresholds (as of %s) already include %s; run the nightly job for the right day", as_of.date(), today.date())
        return 1
    if (today - as_of).days > 5:
        log.warning("thresholds are stale (as of %s); results may miss recent highs", as_of.date())

    bars = snap[(snap["date"] == today) & (snap["symbol"] != config.NIFTY_YAHOO)]
    nifty_ltp = float(nifty.loc[nifty["date"] == today, "close"].iloc[-1]) if (nifty["date"] == today).any() else None
    elapsed = 1.0 if force and phase not in ("open", "closing") else elapsed_fraction(now)

    hits = logic.detect_hits(bars, thr, session_date=today, nifty_ltp=nifty_ltp,
                             nifty_close_ref=meta.get("nifty_close_ref"), elapsed=elapsed)
    hits = logic.enrich_hits(hits, uni)
    now_iso = now.isoformat(timespec="seconds")
    merged = logic.merge_sticky(storage.read_hits(today.date()), hits, now_iso, status="intraday")
    storage.write_csv(merged, storage.hits_path(today.date()))

    payload = status.write_latest(
        job="intraday", market_state="open" if phase == "open" else "closing", session_date=today,
        hits=merged, universe_size=len(tickers), scanned_ok=int(bars["symbol"].nunique()),
        thresholds_as_of=as_of, note=f"Intraday snapshot ({elapsed:.0%} of session elapsed)",
        extra={"nifty_ltp": nifty_ltp},
    )
    log.info("intraday %s: %s highs, %s lows (coverage %s%%)", today.date(),
             payload["counts"]["high"], payload["counts"]["low"], payload["coverage_pct"])
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="run even outside market hours")
    args = ap.parse_args()
    return run(force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
