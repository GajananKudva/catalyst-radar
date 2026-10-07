"""Central settings for the 52-Week High Catalyst Radar.

Every value can be overridden with an environment variable of the same name,
so GitHub Actions, Streamlit Cloud and local runs can share one codebase.
"""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name: str, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return type(default)(raw)


IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))

# ---------------------------------------------------------------- universe
UNIVERSE_SERIES = ("EQ", "BE")        # NSE series treated as the stock universe
YAHOO_SUFFIX = ".NS"
NIFTY_YAHOO = "^NSEI"                 # used for the trading calendar and RS vs Nifty
UNIVERSE_MAX_AGE_DAYS = _env("UNIVERSE_MAX_AGE_DAYS", 7)

# ---------------------------------------------------------- 52-week logic
LOOKBACK_SESSIONS = 252               # ~1 trading year
MIN_SESSIONS = _env("MIN_SESSIONS", 60)  # skip very new listings
HISTORY_CALENDAR_DAYS = 400           # calendar days of history to download nightly
AVG_VOLUME_SESSIONS = 20
RS_SESSIONS = 21                      # ~1 month, for return vs Nifty 50
PRICE_TOLERANCE = 1e-6                # floating-point slack for ">=" comparisons
VOLUME_CONFIRM = _env("VOLUME_CONFIRM", 1.5)  # volume pace >= 1.5x = "confirmed"

# ------------------------------------------------------------ market hours
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
INTRADAY_GRACE_MIN = 15               # keep scanning until 15:45 to catch the close
SESSION_MINUTES = 375

# ----------------------------------------------------------------- yfinance
YF_BATCH_SIZE = _env("YF_BATCH_SIZE", 100)
YF_PAUSE_SEC = _env("YF_PAUSE_SEC", 1.5)
YF_RETRIES = _env("YF_RETRIES", 2)
YF_TIMEOUT = _env("YF_TIMEOUT", 30)

# ---------------------------------------------------------------------- NSE
NSE_BASES = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
NSE_HOME = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
NSE_TIMEOUT = _env("NSE_TIMEOUT", 30)
NSE_PATHS = {
    "equity_list": "/content/equities/EQUITY_L.csv",
    "bhav_udiff": "/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip",
    "bhav_legacy": "/content/historical/EQUITIES/{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip",
    "report_52w": "/content/CM_52_wk_High_low_{ddmmyyyy}.csv",
    "index_list": "/content/indices/{name}.csv",
}
# index lists used for sector labels and SEBI-style market-cap buckets
INDEX_SECTOR_LIST = "ind_niftytotalmarket_list"
INDEX_LARGE = "ind_nifty100list"
INDEX_MID = "ind_niftymidcap150list"
INDEX_SMALL = "ind_niftysmallcap250list"

# ------------------------------------------------------------------ storage
KEEP_HIT_DAYS = _env("KEEP_HIT_DAYS", 30)
