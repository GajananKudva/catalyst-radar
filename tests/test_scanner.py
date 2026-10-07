"""Offline tests: synthetic prices only, no network.

Run:  pytest -q
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from scanner import intraday, logic, market_calendar, nightly, nse, prices, storage  # noqa: E402


# ------------------------------------------------------------------ helpers
def bars(symbol: str, dates, high, low=None, close=None, open_=None, volume=1000.0) -> pd.DataFrame:
    n = len(dates)
    high = np.broadcast_to(np.asarray(high, dtype=float), n)
    low = high * 0.98 if low is None else np.broadcast_to(np.asarray(low, dtype=float), n)
    close = (high + low) / 2 if close is None else np.broadcast_to(np.asarray(close, dtype=float), n)
    open_ = close if open_ is None else np.broadcast_to(np.asarray(open_, dtype=float), n)
    return pd.DataFrame({"symbol": symbol, "date": pd.DatetimeIndex(dates), "open": open_, "high": high,
                         "low": low, "close": close, "volume": np.broadcast_to(np.asarray(volume, dtype=float), n)})


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return tmp_path


# ------------------------------------------------------------- thresholds
def test_thresholds_use_only_last_252_sessions():
    d = pd.bdate_range("2025-01-01", periods=300)
    h = np.full(300, 100.0)
    h[10] = 500.0           # outside the 252 window -> ignored
    h[200] = 150.0          # inside the window -> the 52-week high
    thr = logic.compute_thresholds(bars("X.NS", d, h))
    row = thr.iloc[0]
    assert row["prior_52w_high"] == 150.0
    assert row["prior_52w_high_date"] == d[200]
    assert row["as_of"] == d[-1]
    assert row["sessions"] == 252 and not row["short_history"]


def test_short_history_and_min_sessions():
    d = pd.bdate_range("2026-01-01", periods=80)
    thr = logic.compute_thresholds(bars("NEW.NS", d, 50.0))
    assert bool(thr.iloc[0]["short_history"]) is True
    tiny = logic.compute_thresholds(bars("IPO.NS", d[:10], 50.0))
    assert tiny.empty


# ------------------------------------------------------------------- hits
def _thr(**kw):
    base = dict(symbol="X.NS", as_of=pd.Timestamp("2026-10-06"), sessions=252, short_history=False,
                prior_52w_high=100.0, prior_52w_high_date=pd.Timestamp("2026-05-01"),
                prior_52w_low=50.0, prior_52w_low_date=pd.Timestamp("2026-01-10"),
                prev_close=95.0, avg_vol_20=1000.0, close_ref=90.0, source="yfinance")
    base.update(kw)
    return pd.DataFrame([base])


def test_high_uses_day_high_not_ltp_and_equality_counts():
    today = pd.DataFrame([{"symbol": "X.NS", "open": 96, "high": 100.0, "low": 94, "close": 95, "volume": 3000}])
    hits = logic.detect_hits(today, _thr(), session_date="2026-10-07", nifty_ltp=110, nifty_close_ref=100, elapsed=0.5)
    assert list(hits["type"]) == ["HIGH"]
    h = hits.iloc[0]
    assert h["pct_beyond"] == pytest.approx(0.0)
    assert bool(h["still_beyond"]) is False          # LTP 95 fell back below 100, still a hit
    assert h["vol_multiple"] == pytest.approx(3.0)
    assert h["vol_pace"] == pytest.approx(6.0)       # half the session elapsed
    assert bool(h["volume_confirmed"]) is True
    assert h["gap_pct"] == pytest.approx((96 / 95 - 1) * 100)
    assert h["rs_vs_nifty_1m"] == pytest.approx(((95 / 90 - 1) - 0.10) * 100)


def test_low_and_no_hit():
    low = pd.DataFrame([{"symbol": "X.NS", "open": 52, "high": 53, "low": 49.5, "close": 50, "volume": 500}])
    assert list(logic.detect_hits(low, _thr(), session_date="2026-10-07")["type"]) == ["LOW"]
    calm = pd.DataFrame([{"symbol": "X.NS", "open": 80, "high": 82, "low": 79, "close": 81, "volume": 500}])
    assert logic.detect_hits(calm, _thr(), session_date="2026-10-07").empty


def test_merge_sticky_keeps_first_hit_and_old_rows():
    t1 = pd.DataFrame([{"symbol": "X.NS", "open": 96, "high": 101, "low": 94, "close": 100, "volume": 3000}])
    first = logic.merge_sticky(None, logic.detect_hits(t1, _thr(), session_date="2026-10-07"), "10:00", "intraday")
    # next snapshot: X missing from the download, Y is new
    thr2 = pd.concat([_thr(), _thr(symbol="Y.NS")], ignore_index=True)
    t2 = pd.DataFrame([{"symbol": "Y.NS", "open": 96, "high": 102, "low": 94, "close": 101, "volume": 3000}])
    second = logic.merge_sticky(first, logic.detect_hits(t2, thr2, session_date="2026-10-07"), "10:15", "intraday")
    assert set(second["symbol"]) == {"X.NS", "Y.NS"}
    assert second.set_index("symbol").loc["X.NS", "first_hit_time"] == "10:00"
    assert second.set_index("symbol").loc["Y.NS", "first_hit_time"] == "10:15"
    # X seen again later: first_hit_time preserved, values updated
    t3 = pd.DataFrame([{"symbol": "X.NS", "open": 96, "high": 104, "low": 94, "close": 103, "volume": 3000}])
    third = logic.merge_sticky(second, logic.detect_hits(t3, thr2, session_date="2026-10-07"), "10:30", "intraday")
    x = third.set_index("symbol").loc["X.NS"]
    assert x["first_hit_time"] == "10:00" and x["day_high"] == 104 and x["last_update"] == "10:30"


def test_sector_breadth():
    uni = pd.DataFrame({"yahoo": ["A.NS", "B.NS", "C.NS"], "sector": ["Power", "Power", "IT"]})
    hits = pd.DataFrame({"type": ["HIGH", "HIGH"], "sector": ["Power", "IT"], "status": ["intraday", "intraday"]})
    br = logic.sector_breadth(hits, uni).set_index("sector")
    assert br.loc["Power", "stocks"] == 2 and br.loc["Power", "highs"] == 1 and br.loc["Power", "pct_high"] == 50.0


# ---------------------------------------------------------------- parsers
UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,TtlTradgVol\n"
    "2026-10-06,2026-10-06,CM,NSE,STK,1,INE1,ABC,EQ,10,12,9,11,11,10,5000\n"
    "2026-10-06,2026-10-06,CM,NSE,STK,2,INE2,XYZ,BE,20,21,19,20,20,20,100\n"
    "2026-10-06,2026-10-06,CM,NSE,STK,3,INE3,BND,GB,1,1,1,1,1,1,1\n"
)
LEGACY = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN\n"
    "ABC,EQ,10,12,9,11,11,10,5000,1,05-JUL-2024,1,INE1\n"
)


def test_parse_bhavcopy_udiff_zip_and_legacy():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BhavCopy.csv", UDIFF)
    df = nse.parse_bhavcopy(buf.getvalue())
    assert set(df["symbol"]) == {"ABC", "XYZ"}     # GB series filtered out
    abc = df.set_index("symbol").loc["ABC"]
    assert abc["high"] == 12 and abc["prev_close"] == 10 and abc["date"] == pd.Timestamp("2026-10-06")
    leg = nse.parse_bhavcopy(LEGACY)
    assert leg.iloc[0]["date"] == pd.Timestamp("2024-07-05")


def test_parse_52w_report_skips_disclaimer():
    raw = (
        '"Disclaimer - The Data provided in the adjusted 52 week high and adjusted 52 week low columns are adjusted."\n'
        '"Effective for 25-Jan-2024"\n'
        '"SYMBOL","SERIES","Adjusted 52_Week_High","52_Week_High_Date","Adjusted 52_Week_Low","52_Week_Low_DT"\n'
        '"20MICRONS","EQ","    201.00","22-DEC-2023","     63.05","28-MAR-2023"\n'
        '"360ONE","EQ","    735.00","14-DEC-2023","    395.10","21-MAR-2023"\n'
    )
    df = nse.parse_52w_report(raw)
    assert len(df) == 2
    r = df.set_index("symbol").loc["20MICRONS"]
    assert r["high_52w"] == 201.0 and r["low_52w"] == 63.05
    assert r["high_52w_date"] == pd.Timestamp("2023-12-22")


def test_thresholds_from_nse_widened_by_bhavcopy():
    rep = pd.DataFrame({"symbol": ["ABC"], "series": ["EQ"], "high_52w": [11.0], "high_52w_date": [pd.Timestamp("2026-09-01")],
                        "low_52w": [8.0], "low_52w_date": [pd.Timestamp("2026-02-01")]})
    bhav = pd.DataFrame({"symbol": ["ABC"], "high": [12.0], "low": [9.0], "close": [11.0]})
    thr = logic.thresholds_from_nse(rep, bhav, "2026-10-06")
    r = thr.iloc[0]
    assert r["symbol"] == "ABC.NS" and r["prior_52w_high"] == 12.0 and r["prior_52w_low"] == 8.0
    assert r["prev_close"] == 11.0 and r["source"] == "nse_report"


# ---------------------------------------------------------------- yfinance
def test_to_long_handles_ticker_and_column_layouts():
    idx = pd.DatetimeIndex(["2026-10-05", "2026-10-06"])
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    cols = pd.MultiIndex.from_product([["A.NS", "B.NS"], fields])
    data = np.arange(24, dtype=float).reshape(2, 12) + 1
    wide = pd.DataFrame(data, index=idx, columns=cols)
    wide.loc[:, ("B.NS", slice(None))] = np.nan          # B has no data
    out = prices.to_long(wide, ["A.NS", "B.NS"])
    assert set(out["symbol"]) == {"A.NS"} and len(out) == 2
    swapped = wide.swaplevel(axis=1)
    assert len(prices.to_long(swapped, ["A.NS", "B.NS"])) == 2
    flat = wide["A.NS"]
    assert len(prices.to_long(flat, ["A.NS"])) == 2


def test_download_daily_batches_and_retries_missing():
    calls = []

    def fake(batch, **kw):
        calls.append(list(batch))
        d = pd.bdate_range("2026-10-01", periods=3)
        ok = [t for t in batch if t != "BAD.NS"]
        return pd.concat([bars(t, d, 10.0) for t in ok], ignore_index=True) if ok else prices.empty_prices()

    df, missing = prices.download_daily([f"S{i}.NS" for i in range(5)] + ["BAD.NS"], period="5d",
                                        batch_size=4, pause=0, downloader=fake)
    assert missing == ["BAD.NS"] and df["symbol"].nunique() == 5
    assert len(calls) == 3       # two batches + one retry pass for BAD.NS


# ---------------------------------------------------------------- calendar
def test_market_phase():
    ist = config.IST
    assert market_calendar.market_phase(datetime(2026, 10, 7, 9, 0, tzinfo=ist)) == "pre"
    assert market_calendar.market_phase(datetime(2026, 10, 7, 11, 0, tzinfo=ist)) == "open"
    assert market_calendar.market_phase(datetime(2026, 10, 7, 15, 40, tzinfo=ist)) == "closing"
    assert market_calendar.market_phase(datetime(2026, 10, 7, 18, 30, tzinfo=ist)) == "post"
    assert market_calendar.market_phase(datetime(2026, 10, 10, 11, 0, tzinfo=ist)) == "weekend"
    assert market_calendar.elapsed_fraction(datetime(2026, 10, 7, 12, 22, 30, tzinfo=ist)) == pytest.approx(0.5)


# -------------------------------------------------------- end-to-end flow
def _history(end: str):
    d = pd.bdate_range(end=end, periods=300)
    rng = np.random.default_rng(0)
    base = 100 + rng.normal(0, 0.5, 300).cumsum() * 0.1
    frames = [
        bars("UP.NS", d, np.r_[np.full(299, 100.0), 105.0], volume=np.r_[np.full(299, 1000.0), 4000.0]),
        bars("DOWN.NS", d, np.r_[np.full(299, 100.0), 92.0], low=np.r_[np.full(299, 90.0), 85.0]),
        bars("FLAT.NS", d, np.r_[np.full(299, 100.0), 98.0], low=np.full(300, 95.0)),
        bars("EQUAL.NS", d, np.r_[np.full(150, 100.0), np.full(149, 99.0), 100.0]),
        bars(config.NIFTY_YAHOO, d, base, close=base),
    ]
    return pd.concat(frames, ignore_index=True)


class FakeNSE:
    def bhavcopy(self, d):
        return pd.DataFrame({"symbol": ["GAP"], "series": ["EQ"], "date": [pd.Timestamp(d)], "open": [50.0],
                             "high": [61.0], "low": [49.0], "close": [60.0], "prev_close": [50.0], "volume": [9000.0]})

    def report_52w(self, d):
        return pd.DataFrame({"symbol": ["GAP"], "series": ["EQ"], "high_52w": [60.0], "high_52w_date": [pd.Timestamp("2026-08-01")],
                             "low_52w": [30.0], "low_52w_date": [pd.Timestamp("2026-01-05")]})


def test_nightly_then_intraday_end_to_end(tmp_data, monkeypatch):
    uni = pd.DataFrame({"symbol": ["UP", "DOWN", "FLAT", "EQUAL", "GAP"],
                        "name": ["Up Ltd", "Down Ltd", "Flat Ltd", "Equal Ltd", "Gap Ltd"],
                        "series": "EQ", "isin": "", "sector": ["Power", "Power", "IT", "IT", "Pharma"],
                        "mcap_bucket": "Small"})
    uni["yahoo"] = uni["symbol"] + ".NS"
    storage.write_csv(uni, storage.universe_path())
    monkeypatch.setattr(nightly.universe, "load_universe", lambda force_refresh=False: uni)
    monkeypatch.setattr(nightly, "NSEClient", FakeNSE)
    # last night's thresholds for GAP (Yahoo never returns GAP)
    storage.write_csv(_thr(symbol="GAP.NS", prior_52w_high=60.0, prior_52w_low=30.0, prev_close=50.0), storage.thresholds_path())

    hist = _history("2026-10-06")
    monkeypatch.setattr(nightly.prices, "download_daily", lambda tickers, **kw: (hist, ["GAP.NS"]))
    monkeypatch.setattr(nightly, "now_ist", lambda: datetime(2026, 10, 6, 18, 30, tzinfo=config.IST))
    assert nightly.run() == 0

    eod = storage.read_hits(datetime(2026, 10, 6).date()).set_index(["symbol", "type"])
    assert ("UP.NS", "HIGH") in eod.index and ("DOWN.NS", "LOW") in eod.index
    assert ("EQUAL.NS", "HIGH") in eod.index                 # equal to prior high counts
    assert ("GAP.NS", "HIGH") in eod.index                   # found via bhavcopy fallback
    assert eod.loc[("GAP.NS", "HIGH"), "source"] == "nse_bhavcopy"
    assert ("FLAT.NS", "HIGH") not in eod.index
    assert (eod["status"] == "confirmed").all()
    assert eod.loc[("UP.NS", "HIGH"), "sector"] == "Power"

    thr = storage.read_thresholds().set_index("symbol")
    assert thr.loc["UP.NS", "prior_52w_high"] == 105.0       # today's high now in the window
    assert thr.loc["GAP.NS", "source"] == "nse_report" and thr.loc["GAP.NS", "prior_52w_high"] == 61.0
    meta = json.loads(storage.meta_path().read_text())
    assert meta["thresholds_as_of"] == "2026-10-06"
    assert meta["final"] is True
    # running again the same evening is a no-op
    assert nightly.run() == 0

    # ---- next morning: FLAT breaks out intraday
    d7 = pd.Timestamp("2026-10-07")
    snap = pd.concat([
        hist[hist["date"] >= "2026-10-01"],
        bars("FLAT.NS", [d7], 101.0, low=99.0, close=100.5, open_=99.5, volume=500.0),
        bars("UP.NS", [d7], 104.0, low=102.0, close=103.0),
        bars(config.NIFTY_YAHOO, [d7], 120.0, close=120.0),
    ], ignore_index=True)
    monkeypatch.setattr(intraday.prices, "download_daily", lambda tickers, **kw: (snap, []))
    monkeypatch.setattr(intraday, "now_ist", lambda: datetime(2026, 10, 7, 11, 0, tzinfo=config.IST))
    assert intraday.run() == 0
    h = storage.read_hits(d7.date()).set_index(["symbol", "type"])
    assert list(h.index) == [("FLAT.NS", "HIGH")]
    first_time = h.iloc[0]["first_hit_time"]

    # 15 minutes later FLAT pulls back but stays on the list with its first-hit time
    snap2 = snap.copy()
    snap2.loc[(snap2["symbol"] == "FLAT.NS") & (snap2["date"] == d7), "close"] = 99.6
    monkeypatch.setattr(intraday.prices, "download_daily", lambda tickers, **kw: (snap2, []))
    monkeypatch.setattr(intraday, "now_ist", lambda: datetime(2026, 10, 7, 11, 15, tzinfo=config.IST))
    assert intraday.run() == 0
    h2 = storage.read_hits(d7.date()).iloc[0]
    assert h2["first_hit_time"] == first_time and bool(h2["still_beyond"]) is False

    latest = json.loads(storage.latest_path().read_text())
    assert latest["counts"]["high"] == 1 and latest["market_state"] == "open"
    assert latest["hits_file"] == "hits/2026-10-07.csv"


def test_nightly_before_close_is_not_final(tmp_data, monkeypatch):
    uni = pd.DataFrame({"symbol": ["UP"], "name": ["Up"], "series": "EQ", "isin": "", "sector": "Power",
                        "mcap_bucket": "Small", "yahoo": ["UP.NS"]})
    monkeypatch.setattr(nightly.universe, "load_universe", lambda force_refresh=False: uni)
    monkeypatch.setattr(nightly, "NSEClient", FakeNSE)
    hist = _history("2026-10-06")
    monkeypatch.setattr(nightly.prices, "download_daily", lambda tickers, **kw: (hist, []))
    monkeypatch.setattr(nightly, "now_ist", lambda: datetime(2026, 10, 6, 15, 35, tzinfo=config.IST))
    assert nightly.run() == 0
    assert json.loads(storage.meta_path().read_text())["final"] is False
    # the evening run rebuilds instead of skipping
    monkeypatch.setattr(nightly, "now_ist", lambda: datetime(2026, 10, 6, 18, 30, tzinfo=config.IST))
    assert nightly.run() == 0
    assert json.loads(storage.meta_path().read_text())["final"] is True


def test_intraday_skips_outside_market_hours(tmp_data, monkeypatch):
    monkeypatch.setattr(intraday, "now_ist", lambda: datetime(2026, 10, 7, 20, 0, tzinfo=config.IST))
    assert intraday.run() == 0
    assert not storage.latest_path().exists()


# ----------------------------------------------------------------- sectors
def test_map_to_nse_sector():
    from scanner.sectors import map_to_nse_sector
    assert map_to_nse_sector("Consumer Cyclical", "Auto Parts") == "Automobile and Auto Components"
    assert map_to_nse_sector("Basic Materials", "Steel") == "Metals & Mining"
    assert map_to_nse_sector("Healthcare", "Drug Manufacturers - Specialty & Generic") == "Healthcare"
    assert map_to_nse_sector("Industrials", "Specialty Industrial Machinery") == "Capital Goods"
    assert map_to_nse_sector("Technology", None) == "Information Technology"
    assert map_to_nse_sector(None, None) == "Unclassified"


def test_fill_sectors_uses_cache_priority_and_limit(tmp_data):
    from scanner import sectors
    uni = pd.DataFrame({"yahoo": ["A.NS", "B.NS", "C.NS", "D.NS"],
                        "sector": ["Power", "Unclassified", "Unclassified", "Unclassified"]})
    calls = []

    def fake(t):
        calls.append(t)
        return {"sector": "Technology", "industry": "Software - Application"}

    out = sectors.fill_sectors(uni, priority=["D.NS"], limit=2, fetcher=fake, workers=1)
    assert calls == ["D.NS", "B.NS"]                       # priority first, limit respected
    s = out.set_index("yahoo")["sector"]
    assert s["A.NS"] == "Power" and s["D.NS"] == "Information Technology" and s["C.NS"] == "Unclassified"
    # next run: cached answers applied without refetching, only C is looked up
    calls.clear()
    out2 = sectors.fill_sectors(uni, limit=10, fetcher=fake, workers=1)
    assert calls == ["C.NS"] and (out2["sector"] != "Unclassified").all()
