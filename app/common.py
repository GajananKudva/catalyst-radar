"""Shared helpers for the dashboard pages: cached loaders, filters, colours, formatting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import streamlit as st

import data_loader as dl

# Highs/lows colours (validated categorical pair; identity is never colour-alone:
# every chart also uses legends, direct labels and the ▲ / ▼ symbols).
HIGH_COLOR = "#2a78d6"
LOW_COLOR = "#eb6834"
MCAP_ORDER = ["Large", "Mid", "Small", "Micro"]
CACHE_TTL = 300  # seconds; the scanner publishes every 15 minutes


# ------------------------------------------------------------------ loading
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_latest() -> dict:
    return dl.load_latest()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_meta() -> dict:
    return dl.load_meta()


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def get_history() -> pd.DataFrame:
    return dl.load_history()


@st.cache_data(ttl=3600, show_spinner=False)
def get_universe() -> pd.DataFrame:
    return dl.load_universe()


@st.cache_data(ttl=CACHE_TTL, show_spinner="Loading 52-week hits...")
def get_hits(session: str) -> pd.DataFrame:
    return prepare_hits(dl.load_hits_for(session, get_history()))


def refresh_all() -> None:
    st.cache_data.clear()


# ------------------------------------------------------------- transforms
BOOL_COLS = ["still_beyond", "volume_confirmed", "short_history"]
NUM_COLS = ["day_open", "day_high", "day_low", "ltp", "prev_close", "change_pct", "prior_52w_high",
            "prior_52w_low", "pct_beyond", "volume", "avg_vol_20", "vol_multiple", "vol_pace",
            "gap_pct", "range_position", "rs_vs_nifty_1m"]


def _to_bool(s: pd.Series) -> pd.Series:
    return s.map(lambda v: str(v).strip().lower() in ("true", "1", "yes")).astype(bool)


def prepare_hits(df: pd.DataFrame) -> pd.DataFrame:
    """Type-clean the hits CSV and add display helpers."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    for c in BOOL_COLS:
        df[c] = _to_bool(df[c]) if c in df else False
    for c in NUM_COLS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("name", "sector", "mcap_bucket", "status", "nse_symbol"):
        if c not in df:
            df[c] = None
    df["sector"] = df["sector"].fillna("Unclassified")
    df["mcap_bucket"] = df["mcap_bucket"].fillna("Micro")
    df["nse_symbol"] = df["nse_symbol"].fillna(df["symbol"].astype(str).str.replace(".NS", "", regex=False))
    df["name"] = df["name"].fillna(df["nse_symbol"])
    if "first_hit_time" in df:
        df["first_hit"] = pd.to_datetime(df["first_hit_time"], errors="coerce", utc=True) \
            .dt.tz_convert("Asia/Kolkata").dt.strftime("%H:%M")
    else:
        df["first_hit"] = None
    df["abs_beyond"] = df["pct_beyond"].abs()
    return df


@dataclass
class Filters:
    sectors: list[str] = field(default_factory=list)
    mcaps: list[str] = field(default_factory=list)
    min_beyond: float = 0.0
    volume_confirmed: bool = False
    still_beyond: bool = False
    hide_short_history: bool = False
    hide_unconfirmed: bool = True
    search: str = ""


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if f.sectors:
        out = out[out["sector"].isin(f.sectors)]
    if f.mcaps:
        out = out[out["mcap_bucket"].isin(f.mcaps)]
    if f.min_beyond > 0:
        out = out[out["abs_beyond"] >= f.min_beyond]
    if f.volume_confirmed:
        out = out[out["volume_confirmed"]]
    if f.still_beyond:
        out = out[out["still_beyond"]]
    if f.hide_short_history:
        out = out[~out["short_history"]]
    if f.hide_unconfirmed and "status" in out:
        out = out[out["status"] != "not_confirmed"]
    if f.search.strip():
        q = f.search.strip().lower()
        out = out[out["nse_symbol"].str.lower().str.contains(q, regex=False)
                  | out["name"].astype(str).str.lower().str.contains(q, regex=False)]
    return out


def session_counts(history: pd.DataFrame) -> pd.DataFrame:
    """Confirmed highs and lows per session from the history file."""
    if history is None or history.empty:
        return pd.DataFrame(columns=["session_date", "HIGH", "LOW"])
    c = history.groupby(["session_date", "type"]).size().unstack(fill_value=0)
    for t in ("HIGH", "LOW"):
        if t not in c:
            c[t] = 0
    return c[["HIGH", "LOW"]].reset_index().sort_values("session_date")


# --------------------------------------------------------------- status UI
def minutes_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso)
    except ValueError:
        return None
    now = datetime.now(ts.tzinfo)
    return (now - ts).total_seconds() / 60


MARKET_LABEL = {
    "open": "Market open · intraday snapshot",
    "closing": "Market closing · intraday snapshot",
    "closed": "Market closed · end-of-day list",
    "holiday_or_no_data": "No trading data today (holiday?)",
}


def status_line(latest: dict) -> None:
    mins = minutes_since(latest.get("generated_at"))
    ago = "" if mins is None else (f"{mins:.0f} min ago" if mins < 120 else f"{mins / 60:.1f} h ago")
    state = MARKET_LABEL.get(latest.get("market_state", ""), latest.get("market_state", ""))
    st.caption(f"Session **{latest.get('session_date', '-')}** · {state} · updated {ago} · "
               f"{latest.get('scanned_ok', 0):,} of {latest.get('universe_size', 0):,} stocks scanned "
               f"({latest.get('coverage_pct', 0)}%)")
    if latest.get("market_state") in ("open", "closing") and mins is not None and mins > 35:
        st.warning(f"The last intraday scan finished {mins:.0f} minutes ago; GitHub may have delayed the "
                   "scheduled run. Numbers may be out of date.", icon=":material/schedule:")
    if latest.get("coverage_pct", 100) < 90:
        st.warning(f"Only {latest.get('coverage_pct')}% of stocks returned data in the last scan, "
                   "so some 52-week hits may be missing.", icon=":material/warning:")


def fmt_pct(v: float | None, plus: bool = True) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v:+.2f}%" if plus else f"{v:.2f}%"


def fmt_inr(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"₹{v:,.2f}"
