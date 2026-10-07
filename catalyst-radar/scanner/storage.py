"""File layout of the data directory (published to the `data` branch).

data/
  universe.csv              symbol, name, series, isin, yahoo, sector, mcap_bucket
  thresholds.csv            prior 52-week high/low per stock, valid for the NEXT session
  meta.json                 thresholds as-of date, Nifty reference values, run stats
  latest.json               what the dashboard reads first (status + counts + hits file)
  hits/YYYY-MM-DD.csv       sticky list of 52-week highs/lows for that session
  history/hits_history.csv  end-of-day confirmed hits, appended daily (for analytics)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config

log = logging.getLogger(__name__)


def data_dir() -> Path:
    d = Path(config.DATA_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def universe_path() -> Path:
    return data_dir() / "universe.csv"


def thresholds_path() -> Path:
    return data_dir() / "thresholds.csv"


def meta_path() -> Path:
    return data_dir() / "meta.json"


def latest_path() -> Path:
    return data_dir() / "latest.json"


def hits_path(session: date) -> Path:
    p = data_dir() / "hits"
    p.mkdir(exist_ok=True)
    return p / f"{session:%Y-%m-%d}.csv"


def history_path() -> Path:
    p = data_dir() / "history"
    p.mkdir(exist_ok=True)
    return p / "hits_history.csv"


# ------------------------------------------------------------------ helpers
def read_csv(path: Path, parse_dates: list[str] | None = None) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(path)
    except Exception as exc:  # corrupted file should not kill the run
        log.warning("could not read %s: %s", path, exc)
        return None
    for col in parse_dates or []:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    out.to_csv(tmp, index=False, float_format="%.4f")
    tmp.replace(path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}


def write_json(obj: dict, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------- typed I/O
def read_universe() -> pd.DataFrame | None:
    return read_csv(universe_path())


def read_thresholds() -> pd.DataFrame | None:
    return read_csv(thresholds_path(), parse_dates=["as_of", "prior_52w_high_date", "prior_52w_low_date"])


def read_hits(session: date) -> pd.DataFrame | None:
    return read_csv(hits_path(session))


def append_history(confirmed: pd.DataFrame) -> None:
    if confirmed is None or confirmed.empty:
        return
    path = history_path()
    old = read_csv(path)
    combined = confirmed if old is None else pd.concat([old, confirmed], ignore_index=True)
    combined = combined.drop_duplicates(subset=["session_date", "symbol", "type"], keep="last")
    write_csv(combined, path)


def prune_hits(keep_days: int = config.KEEP_HIT_DAYS, today: date | None = None) -> int:
    today = today or datetime.now(config.IST).date()
    cutoff = today - timedelta(days=keep_days)
    removed = 0
    for f in (data_dir() / "hits").glob("*.csv"):
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            f.unlink()
            removed += 1
    return removed
