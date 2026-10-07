"""Nightly job (after market close, ~18:30 IST).

1. Refresh the universe (weekly) from NSE.
2. Download ~400 days of daily bars for every stock + Nifty 50 (yfinance).
3. END-OF-DAY CHECK: final 52-week highs/lows for today's session, merged with
   the intraday file (first-hit times kept; intraday-only hits marked
   'not_confirmed'). Stocks Yahoo missed are checked with NSE's bhavcopy.
4. THRESHOLDS for the next session (yfinance; NSE 52-week report as fallback).
5. Write meta.json + latest.json and prune old hit files.

Run:  python -m scanner.nightly            (normal)
      python -m scanner.nightly --force    (rebuild even if already done today)
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta

import pandas as pd

import config
from scanner import logic, prices, status, storage, universe
from scanner.market_calendar import now_ist
from scanner.nse import NSEClient, NSEError

log = logging.getLogger("scanner.nightly")


def _nifty_refs(nifty: pd.DataFrame) -> tuple[float | None, float | None]:
    """(last close, close RS_SESSIONS bars back) for a Nifty history ending at the reference day."""
    if nifty.empty:
        return None, None
    closes = nifty.sort_values("date")["close"].to_numpy()
    last = float(closes[-1])
    ref = float(closes[-config.RS_SESSIONS]) if len(closes) >= config.RS_SESSIONS else None
    return last, ref


def run(force: bool = False, refresh_universe: bool = False) -> int:
    now = now_ist()
    today = now.date()
    meta_old = storage.read_json(storage.meta_path())

    uni = universe.load_universe(force_refresh=refresh_universe)
    tickers = uni["yahoo"].tolist()
    log.info("universe: %d stocks", len(tickers))

    start = today - timedelta(days=config.HISTORY_CALENDAR_DAYS)
    hist, missing = prices.download_daily(tickers + [config.NIFTY_YAHOO], start=start, end=today + timedelta(days=1))
    hist = hist[hist["date"] <= pd.Timestamp(today)]
    nifty = hist[hist["symbol"] == config.NIFTY_YAHOO]
    stocks = hist[hist["symbol"] != config.NIFTY_YAHOO]

    if nifty.empty:
        # Yahoo is down: fall back to the last weekday as the session date
        session = pd.Timestamp(today)
        while session.weekday() >= 5:
            session -= pd.Timedelta(days=1)
        log.warning("no Nifty data from Yahoo; assuming session %s", session.date())
    else:
        session = nifty["date"].max()

    if not force and meta_old.get("thresholds_as_of") == session.strftime("%Y-%m-%d"):
        log.info("thresholds already built for %s; nothing to do (use --force to rebuild)", session.date())
        return 0

    stocks = stocks[stocks["date"] <= session]
    nifty = nifty[nifty["date"] <= session]
    today_bars = stocks[stocks["date"] == session]
    log.info("session %s: %d stocks have a bar from Yahoo", session.date(), today_bars["symbol"].nunique())

    nse = NSEClient()
    bhav = None
    try:
        bhav = nse.bhavcopy(session.date())
        log.info("bhavcopy %s: %d rows", session.date(), len(bhav))
    except NSEError as exc:
        log.warning("bhavcopy unavailable: %s", exc)

    # ------------------------------------------------ 3. end-of-day check
    nifty_prev_last, nifty_prev_ref = _nifty_refs(nifty[nifty["date"] < session])
    nifty_today = float(nifty.loc[nifty["date"] == session, "close"].iloc[-1]) if not nifty.empty and (nifty["date"] == session).any() else None

    thr_before = logic.compute_thresholds(stocks[stocks["date"] < session])
    hits_yf = logic.detect_hits(today_bars, thr_before, session_date=session,
                                nifty_ltp=nifty_today, nifty_close_ref=nifty_prev_ref, elapsed=1.0)

    hits_parts = [hits_yf]
    bhav_checked = 0
    have_bar = set(today_bars["symbol"])
    no_bar = [t for t in tickers if t not in have_bar]
    old_thr = storage.read_thresholds()
    if no_bar and bhav is not None and old_thr is not None:
        b = bhav.assign(symbol=bhav["symbol"] + config.YAHOO_SUFFIX)
        b = b[b["symbol"].isin(no_bar)]
        thr_fb = old_thr[old_thr["symbol"].isin(b["symbol"])]
        hits_bhav = logic.detect_hits(b, thr_fb, session_date=session, nifty_ltp=nifty_today,
                                      nifty_close_ref=nifty_prev_ref, elapsed=1.0, source="nse_bhavcopy")
        bhav_checked = int(b["symbol"].nunique())
        log.info("bhavcopy fallback checked %d stocks, %d hits", bhav_checked, len(hits_bhav))
        hits_parts.append(hits_bhav)
    eod = pd.concat([h for h in hits_parts if not h.empty], ignore_index=True) if any(not h.empty for h in hits_parts) \
        else pd.DataFrame(columns=logic.HIT_COLUMNS)
    eod = logic.enrich_hits(eod, uni)

    now_iso = now.isoformat(timespec="seconds")
    intraday = storage.read_hits(session.date())
    merged = logic.merge_sticky(intraday, eod, now_iso, status="confirmed")
    merged = logic.mark_unconfirmed(merged, set(zip(eod["symbol"], eod["type"])))
    storage.write_csv(merged, storage.hits_path(session.date()))
    storage.append_history(eod.assign(status="confirmed"))
    log.info("EOD %s: %d highs, %d lows confirmed", session.date(),
             (eod["type"] == "HIGH").sum(), (eod["type"] == "LOW").sum())

    # ------------------------------------- 4. thresholds for next session
    thr = logic.compute_thresholds(stocks)
    thr = thr[thr["as_of"] == session]  # drop stocks with stale data (suspended etc.)
    lacking = [t for t in tickers if t not in set(thr["symbol"])]
    if lacking:
        try:
            report = nse.report_52w(session.date())
            fb = logic.thresholds_from_nse(report, bhav, session)
            fb = fb[fb["symbol"].isin(lacking)]
            thr = pd.concat([thr, fb], ignore_index=True)
            log.info("NSE 52-week report filled %d of %d missing thresholds", len(fb), len(lacking))
        except NSEError as exc:
            log.warning("NSE 52-week report unavailable (%s); %d stocks have no threshold", exc, len(lacking))
    storage.write_csv(thr, storage.thresholds_path())

    nifty_last, nifty_ref = _nifty_refs(nifty)
    meta = {
        "built_at": now_iso,
        "thresholds_as_of": session.strftime("%Y-%m-%d"),
        "nifty_prev_close": nifty_last,
        "nifty_close_ref": nifty_ref,
        "universe_size": len(tickers),
        "thresholds_count": int(len(thr)),
        "yahoo_ok": int(stocks["symbol"].nunique()),
        "yahoo_missing": len(missing),
        "sources": thr["source"].value_counts().to_dict() if not thr.empty else {},
    }
    storage.write_json(meta, storage.meta_path())

    status.write_latest(
        job="nightly", market_state="closed", session_date=session, hits=merged,
        universe_size=len(tickers), scanned_ok=len(have_bar) + bhav_checked,
        thresholds_as_of=session, note="End-of-day confirmed list",
    )
    removed = storage.prune_hits(today=today)
    log.info("thresholds for next session: %d stocks; pruned %d old hit files", len(thr), removed)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="rebuild even if thresholds are current")
    ap.add_argument("--refresh-universe", action="store_true", help="re-download the NSE stock list now")
    args = ap.parse_args()
    return run(force=args.force, refresh_universe=args.refresh_universe)


if __name__ == "__main__":
    raise SystemExit(main())
