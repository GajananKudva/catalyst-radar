"""Pure 52-week logic (no network, fully unit-tested).

Rule: a stock is a 52-week HIGH on session T if
    day_high(T) >= max(high over the 252 sessions before T)
and a 52-week LOW if
    day_low(T)  <= min(low  over the 252 sessions before T).
The day's HIGH/LOW is used, never the last traded price, so a hit stays a hit
for the rest of the day even if the price falls back.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

THRESHOLD_COLUMNS = [
    "symbol", "as_of", "sessions", "short_history",
    "prior_52w_high", "prior_52w_high_date", "prior_52w_low", "prior_52w_low_date",
    "prev_close", "avg_vol_20", "close_ref", "source",
]

HIT_COLUMNS = [
    "session_date", "symbol", "nse_symbol", "name", "sector", "mcap_bucket", "type", "status",
    "first_hit_time", "last_update",
    "day_open", "day_high", "day_low", "ltp", "prev_close", "change_pct",
    "prior_52w_high", "prior_52w_low", "prior_extreme_date", "pct_beyond", "still_beyond",
    "volume", "avg_vol_20", "vol_multiple", "vol_pace", "volume_confirmed",
    "gap_pct", "range_position", "rs_vs_nifty_1m", "short_history", "source",
]


def compute_thresholds(hist: pd.DataFrame, lookback: int = config.LOOKBACK_SESSIONS,
                       min_sessions: int = config.MIN_SESSIONS, source: str = "yfinance") -> pd.DataFrame:
    """Per-symbol 52-week stats from the LAST `lookback` bars of `hist`.

    The result is the threshold for the session AFTER the last bar in `hist`.
    """
    if hist is None or hist.empty:
        return pd.DataFrame(columns=THRESHOLD_COLUMNS)
    hist = hist.sort_values(["symbol", "date"])
    rows = []
    for sym, df in hist.groupby("symbol", sort=False):
        full_n = len(df)
        win = df.tail(lookback)
        n = len(win)
        if n < min_sessions:
            continue
        hi_i = win["high"].to_numpy().argmax()
        lo_i = win["low"].to_numpy().argmin()
        closes = df["close"].to_numpy()
        rows.append({
            "symbol": sym,
            "as_of": win["date"].iloc[-1],
            "sessions": n,
            "short_history": full_n < lookback,
            "prior_52w_high": float(win["high"].iloc[hi_i]),
            "prior_52w_high_date": win["date"].iloc[hi_i],
            "prior_52w_low": float(win["low"].iloc[lo_i]),
            "prior_52w_low_date": win["date"].iloc[lo_i],
            "prev_close": float(closes[-1]),
            "avg_vol_20": float(df["volume"].tail(config.AVG_VOLUME_SESSIONS).mean()),
            "close_ref": float(closes[-config.RS_SESSIONS]) if full_n >= config.RS_SESSIONS else np.nan,
            "source": source,
        })
    return pd.DataFrame(rows, columns=THRESHOLD_COLUMNS)


def thresholds_from_nse(report: pd.DataFrame, bhav: pd.DataFrame | None, as_of) -> pd.DataFrame:
    """Fallback thresholds from NSE's adjusted 52-week report, widened with that day's bhavcopy.

    Taking max/min with the bhavcopy day high/low makes the result correct whether
    or not the report already includes that day's trading.
    """
    df = report.rename(columns={"high_52w": "prior_52w_high", "high_52w_date": "prior_52w_high_date",
                                "low_52w": "prior_52w_low", "low_52w_date": "prior_52w_low_date"}).copy()
    df["prev_close"] = np.nan
    if bhav is not None and not bhav.empty:
        b = bhav.set_index("symbol")
        bh, bl, bc = (df["symbol"].map(b[c]) for c in ("high", "low", "close"))
        up = bh > df["prior_52w_high"]
        df.loc[up, "prior_52w_high"] = bh[up]
        df.loc[up, "prior_52w_high_date"] = pd.Timestamp(as_of)
        down = bl < df["prior_52w_low"]
        df.loc[down, "prior_52w_low"] = bl[down]
        df.loc[down, "prior_52w_low_date"] = pd.Timestamp(as_of)
        df["prev_close"] = bc
    df["symbol"] = df["symbol"] + config.YAHOO_SUFFIX
    df["as_of"] = pd.Timestamp(as_of)
    df["sessions"] = np.nan
    df["short_history"] = False
    df["avg_vol_20"] = np.nan
    df["close_ref"] = np.nan
    df["source"] = "nse_report"
    return df[THRESHOLD_COLUMNS]


def detect_hits(bars: pd.DataFrame, thresholds: pd.DataFrame, *, session_date,
                nifty_ltp: float | None = None, nifty_close_ref: float | None = None,
                elapsed: float = 1.0, source: str = "yfinance") -> pd.DataFrame:
    """Compare one session's bars (symbol, open, high, low, close, volume) with thresholds."""
    if bars is None or bars.empty or thresholds is None or thresholds.empty:
        return pd.DataFrame(columns=HIT_COLUMNS)
    thr = thresholds.drop(columns=["source"], errors="ignore")
    cols = ["symbol", "open", "high", "low", "close", "volume"]
    m = bars[cols].merge(thr, on="symbol", how="inner")
    m = m[(m["prior_52w_high"] > 0) & (m["prior_52w_low"] > 0)]
    if m.empty:
        return pd.DataFrame(columns=HIT_COLUMNS)

    nifty_ret = np.nan
    if nifty_ltp and nifty_close_ref:
        nifty_ret = nifty_ltp / nifty_close_ref - 1

    rng = (m["high"] - m["low"]).replace(0, np.nan)
    common = pd.DataFrame({
        "session_date": pd.Timestamp(session_date).strftime("%Y-%m-%d"),
        "symbol": m["symbol"],
        "nse_symbol": m["symbol"].str.removesuffix(config.YAHOO_SUFFIX),
        "day_open": m["open"], "day_high": m["high"], "day_low": m["low"], "ltp": m["close"],
        "prev_close": m["prev_close"],
        "change_pct": (m["close"] / m["prev_close"] - 1) * 100,
        "prior_52w_high": m["prior_52w_high"], "prior_52w_low": m["prior_52w_low"],
        "volume": m["volume"], "avg_vol_20": m["avg_vol_20"],
        "vol_multiple": m["volume"] / m["avg_vol_20"].replace(0, np.nan),
        "gap_pct": (m["open"] / m["prev_close"] - 1) * 100,
        "range_position": (m["close"] - m["low"]) / rng,
        "rs_vs_nifty_1m": ((m["close"] / m["close_ref"] - 1) - nifty_ret) * 100,
        "short_history": m["short_history"],
        "source": source,
    })
    common["vol_pace"] = common["vol_multiple"] / max(elapsed, 0.05)
    common["volume_confirmed"] = common["vol_pace"] >= config.VOLUME_CONFIRM

    tol = config.PRICE_TOLERANCE
    is_high = m["high"] >= m["prior_52w_high"] * (1 - tol)
    is_low = m["low"] <= m["prior_52w_low"] * (1 + tol)

    highs = common[is_high.to_numpy()].copy()
    highs["type"] = "HIGH"
    highs["pct_beyond"] = (highs["day_high"] / highs["prior_52w_high"] - 1) * 100
    highs["still_beyond"] = highs["ltp"] >= highs["prior_52w_high"]
    highs["prior_extreme_date"] = m.loc[is_high, "prior_52w_high_date"].to_numpy()

    lows = common[is_low.to_numpy()].copy()
    lows["type"] = "LOW"
    lows["pct_beyond"] = (lows["day_low"] / lows["prior_52w_low"] - 1) * 100
    lows["still_beyond"] = lows["ltp"] <= lows["prior_52w_low"]
    lows["prior_extreme_date"] = m.loc[is_low, "prior_52w_low_date"].to_numpy()

    out = pd.concat([highs, lows], ignore_index=True)
    if out.empty:
        return pd.DataFrame(columns=HIT_COLUMNS)
    out["prior_extreme_date"] = pd.to_datetime(out["prior_extreme_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ("name", "sector", "mcap_bucket", "status", "first_hit_time", "last_update"):
        out[col] = None
    return out[HIT_COLUMNS]


def enrich_hits(hits: pd.DataFrame, universe: pd.DataFrame | None) -> pd.DataFrame:
    if hits.empty or universe is None or universe.empty:
        return hits
    u = universe.set_index("yahoo")
    hits = hits.copy()
    for col in ("name", "sector", "mcap_bucket"):
        hits[col] = hits["symbol"].map(u[col]).fillna(hits[col]) if col in u else hits[col]
    hits["sector"] = hits["sector"].fillna("Unclassified")
    return hits


def merge_sticky(existing: pd.DataFrame | None, new: pd.DataFrame, now_iso: str, status: str) -> pd.DataFrame:
    """Keep every hit seen today. New snapshot values overwrite old ones; first_hit_time is preserved."""
    new = new.copy()
    new["status"] = status
    new["last_update"] = now_iso
    if existing is None or existing.empty:
        new["first_hit_time"] = now_iso
        return _sort_hits(new)
    key = ["symbol", "type"]
    existing = existing.reindex(columns=HIT_COLUMNS).drop_duplicates(subset=key, keep="last")
    first = existing.set_index(key)["first_hit_time"]
    idx = pd.MultiIndex.from_frame(new[key])
    new["first_hit_time"] = pd.Series(first.reindex(idx).to_numpy(), index=new.index).fillna(now_iso)
    seen = set(map(tuple, new[key].to_numpy()))
    keep_old = existing[[tuple(k) not in seen for k in existing[key].to_numpy()]]
    out = pd.concat([new, keep_old], ignore_index=True) if not keep_old.empty else new
    return _sort_hits(out)


def mark_unconfirmed(merged: pd.DataFrame, confirmed_keys: set[tuple[str, str]]) -> pd.DataFrame:
    """After the end-of-day check, intraday hits that final data did not confirm get status 'not_confirmed'."""
    if merged.empty:
        return merged
    merged = merged.copy()
    keys = list(zip(merged["symbol"], merged["type"]))
    merged.loc[[k not in confirmed_keys for k in keys], "status"] = "not_confirmed"
    return merged


def _sort_hits(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reindex(columns=HIT_COLUMNS)
    df["_abs"] = df["pct_beyond"].abs()
    return df.sort_values(["type", "_abs"], ascending=[True, False]).drop(columns="_abs").reset_index(drop=True)


def sector_breadth(hits: pd.DataFrame, universe: pd.DataFrame | None) -> pd.DataFrame:
    """Per sector: stocks in universe, 52-week highs, lows and share of the sector making highs."""
    cols = ["sector", "stocks", "highs", "lows", "pct_high", "pct_low"]
    if universe is None or universe.empty:
        return pd.DataFrame(columns=cols)
    base = universe.groupby("sector").size().rename("stocks")
    if hits is None or hits.empty:
        h = pd.Series(dtype=float, name="highs")
        lo = pd.Series(dtype=float, name="lows")
    else:
        valid = hits[hits["status"] != "not_confirmed"]
        h = valid[valid["type"] == "HIGH"].groupby("sector").size().rename("highs")
        lo = valid[valid["type"] == "LOW"].groupby("sector").size().rename("lows")
    df = pd.concat([base, h, lo], axis=1).fillna(0)
    df[["stocks", "highs", "lows"]] = df[["stocks", "highs", "lows"]].astype(int)
    df["pct_high"] = (df["highs"] / df["stocks"].replace(0, np.nan) * 100).round(1)
    df["pct_low"] = (df["lows"] / df["stocks"].replace(0, np.nan) * 100).round(1)
    return df.reset_index(names="sector").sort_values("highs", ascending=False)[cols].reset_index(drop=True)
