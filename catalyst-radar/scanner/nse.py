"""Small NSE archive client: equity list, index lists, bhavcopy and 52-week report.

NSE is used as the FALLBACK source (yfinance is primary). NSE sometimes blocks
cloud servers, so every call is wrapped and failures raise NSEError, which the
callers catch and log.

Parsers are pure functions (parse_*) so they can be unit-tested offline.
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import date

import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

BHAV_COLUMNS = ["symbol", "series", "date", "open", "high", "low", "close", "prev_close", "volume"]


class NSEError(RuntimeError):
    pass


class NSEClient:
    def __init__(self, timeout: int = config.NSE_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(config.NSE_HEADERS)
        self._warmed = False

    def _warm(self) -> None:
        """Visit the home page once so NSE sets its cookies."""
        if self._warmed:
            return
        self._warmed = True
        try:
            self.session.get(config.NSE_HOME, timeout=self.timeout)
        except requests.RequestException as exc:
            log.debug("NSE warm-up failed: %s", exc)

    def get_bytes(self, path: str) -> bytes:
        self._warm()
        last: object = None
        for base in config.NSE_BASES:
            for attempt in range(2):
                try:
                    r = self.session.get(base + path, timeout=self.timeout)
                    if r.status_code == 200 and r.content:
                        return r.content
                    last = f"HTTP {r.status_code}"
                except requests.RequestException as exc:
                    last = exc
                time.sleep(1 + attempt)
        raise NSEError(f"{path}: {last}")

    # ------------------------------------------------------------ endpoints
    def equity_list(self) -> pd.DataFrame:
        return parse_equity_list(self.get_bytes(config.NSE_PATHS["equity_list"]))

    def index_list(self, name: str) -> pd.DataFrame:
        return parse_index_list(self.get_bytes(config.NSE_PATHS["index_list"].format(name=name)))

    def bhavcopy(self, d: date) -> pd.DataFrame:
        """End-of-day prices for every NSE stock on date d (unadjusted)."""
        paths = [config.NSE_PATHS["bhav_udiff"].format(yyyymmdd=f"{d:%Y%m%d}")]
        mon = f"{d:%b}".upper()
        paths.append(config.NSE_PATHS["bhav_legacy"].format(yyyy=d.year, mon=mon, dd=f"{d:%d}"))
        last: Exception | None = None
        for p in paths:
            try:
                return parse_bhavcopy(self.get_bytes(p))
            except (NSEError, ValueError) as exc:
                last = exc
        raise NSEError(f"bhavcopy {d}: {last}")

    def report_52w(self, d: date) -> pd.DataFrame:
        """NSE's corporate-action-adjusted 52-week high/low report for date d."""
        raw = self.get_bytes(config.NSE_PATHS["report_52w"].format(ddmmyyyy=f"{d:%d%m%Y}"))
        return parse_52w_report(raw)


# ------------------------------------------------------------------ parsers
def _to_text(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8-sig", errors="replace")


def _maybe_unzip(raw: bytes | str) -> str:
    if isinstance(raw, bytes) and raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
            return zf.read(name).decode("utf-8-sig", errors="replace")
    return _to_text(raw)


def parse_equity_list(raw: bytes | str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(_to_text(raw)))
    df.columns = [c.strip().upper() for c in df.columns]
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].astype(str).str.strip(),
        "name": df.get("NAME OF COMPANY", df["SYMBOL"]).astype(str).str.strip(),
        "series": df["SERIES"].astype(str).str.strip(),
        "isin": df.get("ISIN NUMBER", pd.Series([""] * len(df))).astype(str).str.strip(),
    })
    return out[out["series"].isin(config.UNIVERSE_SERIES)].reset_index(drop=True)


def parse_index_list(raw: bytes | str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(_to_text(raw)))
    df.columns = [c.strip() for c in df.columns]
    return pd.DataFrame({
        "symbol": df["Symbol"].astype(str).str.strip(),
        "industry": df["Industry"].astype(str).str.strip() if "Industry" in df else "",
    })


_BHAV_MAP = {
    # UDiFF format (July 2024 onwards)
    "TckrSymb": "symbol", "SctySrs": "series", "TradDt": "date", "OpnPric": "open",
    "HghPric": "high", "LwPric": "low", "ClsPric": "close", "PrvsClsgPric": "prev_close",
    "TtlTradgVol": "volume",
    # legacy format
    "SYMBOL": "symbol", "SERIES": "series", "TIMESTAMP": "date", "OPEN": "open", "HIGH": "high",
    "LOW": "low", "CLOSE": "close", "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume",
}


def parse_bhavcopy(raw: bytes | str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(_maybe_unzip(raw)))
    df.columns = [c.strip() for c in df.columns]
    if "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].astype(str).str.strip() == "STK"]
    df = df.rename(columns={k: v for k, v in _BHAV_MAP.items() if k in df.columns})
    missing = [c for c in BHAV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"bhavcopy missing columns {missing}")
    df = df[BHAV_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["series"] = df["series"].astype(str).str.strip()
    df = df[df["series"].isin(config.UNIVERSE_SERIES)]
    for c in ["open", "high", "low", "close", "prev_close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed", dayfirst=False).dt.normalize()
    # one row per symbol (prefer EQ over BE)
    df["_rank"] = df["series"].map({s: i for i, s in enumerate(config.UNIVERSE_SERIES)})
    df = df.sort_values("_rank").drop_duplicates("symbol").drop(columns="_rank")
    return df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)


def parse_52w_report(raw: bytes | str) -> pd.DataFrame:
    """The file starts with disclaimer lines; the real header begins with SYMBOL."""
    text = _to_text(raw)
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().strip('"').upper().startswith("SYMBOL")), None)
    if start is None:
        raise ValueError("52-week report: header not found")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.strip() for c in df.columns]
    col = {c.lower(): c for c in df.columns}

    def pick(*keys: str) -> str:
        for k in keys:
            for lc, orig in col.items():
                if k in lc:
                    return orig
        raise ValueError(f"52-week report: column {keys} not found")

    out = pd.DataFrame({
        "symbol": df[pick("symbol")].astype(str).str.strip(),
        "series": df[pick("series")].astype(str).str.strip(),
        "high_52w": pd.to_numeric(df[pick("52_week_high")].astype(str).str.strip(), errors="coerce"),
        "high_52w_date": pd.to_datetime(df[pick("52_week_high_date")].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce"),
        "low_52w": pd.to_numeric(df[pick("52_week_low")].astype(str).str.strip(), errors="coerce"),
        "low_52w_date": pd.to_datetime(df[pick("52_week_low_dt", "52_week_low_date")].astype(str).str.strip(), format="%d-%b-%Y", errors="coerce"),
    })
    out = out[out["series"].isin(config.UNIVERSE_SERIES)]
    return out.dropna(subset=["high_52w", "low_52w"]).drop_duplicates("symbol").reset_index(drop=True)
