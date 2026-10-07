"""Writes data/latest.json, the small file the dashboard reads first."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

import config
from scanner import storage


def write_latest(*, job: str, market_state: str, session_date, hits: pd.DataFrame | None,
                 universe_size: int, scanned_ok: int, thresholds_as_of=None, note: str = "",
                 extra: dict | None = None) -> dict:
    hits = hits if hits is not None else pd.DataFrame(columns=["type", "status", "volume_confirmed"])
    valid = hits[hits.get("status", pd.Series(dtype=str)) != "not_confirmed"] if not hits.empty else hits
    highs = valid[valid["type"] == "HIGH"] if not valid.empty else valid
    lows = valid[valid["type"] == "LOW"] if not valid.empty else valid

    def n_conf(df: pd.DataFrame) -> int:
        return int(df["volume_confirmed"].fillna(False).astype(bool).sum()) if not df.empty else 0

    session_str = pd.Timestamp(session_date).strftime("%Y-%m-%d") if session_date is not None else None
    payload = {
        "generated_at": datetime.now(config.IST).isoformat(timespec="seconds"),
        "job": job,
        "market_state": market_state,
        "session_date": session_str,
        "thresholds_as_of": pd.Timestamp(thresholds_as_of).strftime("%Y-%m-%d") if thresholds_as_of is not None else None,
        "universe_size": int(universe_size),
        "scanned_ok": int(scanned_ok),
        "coverage_pct": round(100 * scanned_ok / universe_size, 1) if universe_size else 0.0,
        "counts": {
            "high": int(len(highs)), "low": int(len(lows)),
            "high_volume_confirmed": n_conf(highs), "low_volume_confirmed": n_conf(lows),
        },
        "hits_file": f"hits/{session_str}.csv" if session_str else None,
        "note": note,
    }
    if extra:
        payload.update(extra)
    storage.write_json(payload, storage.latest_path())
    return payload
