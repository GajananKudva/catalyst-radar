"""Daily price download from Yahoo Finance via yfinance, in polite batches.

Returns a long table: symbol (Yahoo ticker), date, open, high, low, close, volume.
Prices are split-adjusted but NOT dividend-adjusted (auto_adjust=False), so
splits/bonuses don't create false 52-week signals.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator

import pandas as pd

import config

log = logging.getLogger(__name__)

PRICE_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]
_FIELDS = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}


def empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _normalise_index(idx: pd.Index) -> pd.DatetimeIndex:
    dt = pd.DatetimeIndex(pd.to_datetime(idx))
    if dt.tz is not None:
        dt = dt.tz_convert(config.IST).tz_localize(None)
    return dt.normalize()


def to_long(raw: pd.DataFrame | None, tickers: list[str]) -> pd.DataFrame:
    """Convert yfinance's wide (ticker, field) frame into the long PRICE_COLUMNS table."""
    if raw is None or raw.empty:
        return empty_prices()
    frames = []
    if isinstance(raw.columns, pd.MultiIndex):
        if set(raw.columns.get_level_values(0)) <= _FIELDS:  # group_by='column' layout
            raw = raw.swaplevel(axis=1)
        for t in dict.fromkeys(raw.columns.get_level_values(0)):
            frames.append(_one(raw[t], t))
    else:  # single ticker, flat columns
        frames.append(_one(raw, tickers[0]))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return empty_prices()
    return pd.concat(frames, ignore_index=True)[PRICE_COLUMNS]


def _one(sub: pd.DataFrame, ticker: str) -> pd.DataFrame:
    sub = sub.rename(columns=lambda c: str(c).lower())
    need = ["open", "high", "low", "close"]
    if any(c not in sub.columns for c in need):
        return empty_prices()
    sub = sub.dropna(subset=["high", "low", "close"])
    if sub.empty:
        return empty_prices()
    out = pd.DataFrame({
        "symbol": ticker,
        "date": _normalise_index(sub.index),
        "open": sub["open"].to_numpy(dtype=float),
        "high": sub["high"].to_numpy(dtype=float),
        "low": sub["low"].to_numpy(dtype=float),
        "close": sub["close"].to_numpy(dtype=float),
        "volume": sub["volume"].to_numpy(dtype=float) if "volume" in sub else float("nan"),
    })
    return out.drop_duplicates(subset=["date"], keep="last")


def _download_batch(batch: list[str], **kwargs) -> pd.DataFrame:
    import yfinance as yf  # imported lazily so tests don't need network

    for attempt in range(config.YF_RETRIES + 1):
        try:
            raw = yf.download(
                batch, interval="1d", auto_adjust=False, actions=False, group_by="ticker",
                threads=True, progress=False, timeout=config.YF_TIMEOUT, **kwargs,
            )
            return to_long(raw, batch)
        except Exception as exc:  # network / throttling
            wait = config.YF_PAUSE_SEC * (2 ** attempt)
            log.warning("yfinance batch failed (%s), retry in %.1fs", exc, wait)
            time.sleep(wait)
    return empty_prices()


def download_daily(tickers: Iterable[str], *, start=None, end=None, period: str | None = None,
                   batch_size: int = config.YF_BATCH_SIZE, pause: float = config.YF_PAUSE_SEC,
                   downloader=_download_batch) -> tuple[pd.DataFrame, list[str]]:
    """Download daily bars for many tickers. Returns (prices, tickers_with_no_data)."""
    tickers = list(dict.fromkeys(tickers))
    kwargs = {}
    if period:
        kwargs["period"] = period
    else:
        kwargs["start"], kwargs["end"] = start, end

    frames: list[pd.DataFrame] = []
    got: set[str] = set()
    for i, batch in enumerate(chunks(tickers, batch_size), 1):
        df = downloader(batch, **kwargs)
        frames.append(df)
        got |= set(df["symbol"].unique())
        log.info("yfinance batch %d: %d/%d tickers with data", i, df["symbol"].nunique(), len(batch))
        time.sleep(pause)

    missing = [t for t in tickers if t not in got]
    if missing:  # one slower second pass for throttled tickers
        log.info("retrying %d tickers in smaller batches", len(missing))
        for batch in chunks(missing, max(10, batch_size // 4)):
            df = downloader(batch, **kwargs)
            frames.append(df)
            got |= set(df["symbol"].unique())
            time.sleep(pause * 2)
        missing = [t for t in tickers if t not in got]

    frames = [f for f in frames if not f.empty]
    prices = pd.concat(frames, ignore_index=True) if frames else empty_prices()
    prices = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
    log.info("yfinance done: %d/%d tickers, %d rows", len(got), len(tickers), len(prices))
    return prices, missing
