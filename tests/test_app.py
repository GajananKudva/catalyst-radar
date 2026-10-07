"""Dashboard smoke tests with a tiny synthetic data folder (no network)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config  # noqa: E402

st_testing = pytest.importorskip("streamlit.testing.v1")


def _write_data(d: Path) -> None:
    (d / "hits").mkdir(parents=True)
    (d / "history").mkdir()
    hits = pd.DataFrame([
        dict(session_date="2026-10-07", symbol="AAA.NS", nse_symbol="AAA", name="Aaa Ltd", sector="Power",
             mcap_bucket="Small", type="HIGH", status="confirmed", first_hit_time="2026-10-07T10:15:00+05:30",
             day_open=101, day_high=110, day_low=100, ltp=109, prev_close=100, change_pct=9.0,
             prior_52w_high=105, prior_52w_low=60, pct_beyond=4.76, still_beyond=True, volume=5000,
             avg_vol_20=1000, vol_multiple=5.0, vol_pace=5.0, volume_confirmed=True, gap_pct=1.0,
             range_position=0.9, rs_vs_nifty_1m=12.0, short_history=False, source="yfinance"),
        dict(session_date="2026-10-07", symbol="BBB.NS", nse_symbol="BBB", name="Bbb Ltd", sector="IT",
             mcap_bucket="Micro", type="LOW", status="confirmed", first_hit_time="2026-10-07T11:00:00+05:30",
             day_open=50, day_high=51, day_low=40, ltp=41, prev_close=50, change_pct=-18.0,
             prior_52w_high=90, prior_52w_low=42, pct_beyond=-4.76, still_beyond=True, volume=900,
             avg_vol_20=1000, vol_multiple=0.9, vol_pace=0.9, volume_confirmed=False, gap_pct=0.0,
             range_position=0.1, rs_vs_nifty_1m=-20.0, short_history=False, source="yfinance"),
    ])
    hits.to_csv(d / "hits" / "2026-10-07.csv", index=False)
    hits.to_csv(d / "history" / "hits_history.csv", index=False)
    pd.DataFrame({"symbol": ["AAA", "BBB"], "yahoo": ["AAA.NS", "BBB.NS"], "sector": ["Power", "IT"],
                  "industry": [None, None], "mcap_bucket": ["Small", "Micro"]}).to_csv(d / "universe.csv", index=False)
    (d / "latest.json").write_text(json.dumps({
        "generated_at": "2026-10-07T18:40:00+05:30", "job": "nightly", "market_state": "closed",
        "session_date": "2026-10-07", "universe_size": 2, "scanned_ok": 2, "coverage_pct": 100.0,
        "counts": {"high": 1, "low": 1}, "hits_file": "hits/2026-10-07.csv"}))
    (d / "meta.json").write_text(json.dumps({"sources": {"yfinance": 2}}))


@pytest.fixture
def app(tmp_path, monkeypatch):
    _write_data(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("DATA_URL", raising=False)
    at = st_testing.AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=60)
    return at


def test_dashboard_renders_and_filters(app):
    app.run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["▲ 52W highs"] == "1" and metrics["▼ 52W lows"] == "1"
    app.sidebar.toggle[0].set_value(True).run()          # volume-confirmed only
    assert {m.label: m.value for m in app.metric}["▼ 52W lows"] == "0"


def test_deep_dive_page(app):
    app.query_params["symbol"] = "AAA.NS"
    app.query_params["session"] = "2026-10-07"
    app.run()
    app.switch_page("views/deep_dive.py").run()
    assert not app.exception
    assert app.title[0].value == "Aaa Ltd"


def test_apply_filters():
    import common
    df = common.prepare_hits(pd.DataFrame({
        "symbol": ["A.NS", "B.NS"], "name": ["A", "B"], "sector": ["Power", None], "type": ["HIGH", "HIGH"],
        "pct_beyond": [5.0, 0.5], "volume_confirmed": ["True", "False"], "still_beyond": [True, False],
        "short_history": [False, True], "status": ["confirmed", "not_confirmed"]}))
    f = common.Filters(min_beyond=1.0)
    assert list(common.apply_filters(df, f)["symbol"]) == ["A.NS"]
    assert list(common.apply_filters(df, common.Filters(hide_unconfirmed=False, search="b"))["symbol"]) == ["B.NS"]
    assert df.loc[df["symbol"] == "B.NS", "sector"].iloc[0] == "Unclassified"
