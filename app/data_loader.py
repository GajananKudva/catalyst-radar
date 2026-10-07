"""Loads scanner output for the dashboard.

Reads from DATA_URL (raw GitHub URL of the `data` branch) when set, otherwise
from the local data/ folder - so the same app works on Streamlit Cloud and on
your laptop after `python -m scanner.nightly`.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


def data_url() -> str | None:
    url = os.getenv("DATA_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATA_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    return url.rstrip("/") if url else None


def _read_text(rel_path: str) -> str | None:
    url = data_url()
    if url:
        try:
            r = requests.get(f"{url}/{rel_path}", timeout=20)
        except requests.RequestException:
            return None
        return r.text if r.status_code == 200 else None
    p = Path(config.DATA_DIR) / rel_path
    return p.read_text(encoding="utf-8") if p.exists() else None


def load_json(rel_path: str) -> dict:
    txt = _read_text(rel_path)
    try:
        return json.loads(txt) if txt else {}
    except json.JSONDecodeError:
        return {}


def load_csv(rel_path: str) -> pd.DataFrame:
    txt = _read_text(rel_path)
    if not txt:
        return pd.DataFrame()
    try:
        return pd.read_csv(io.StringIO(txt))
    except Exception:
        return pd.DataFrame()


def load_latest() -> dict:
    return load_json("latest.json")


def load_meta() -> dict:
    return load_json("meta.json")


def load_universe() -> pd.DataFrame:
    return load_csv("universe.csv")


def load_history() -> pd.DataFrame:
    """End-of-day confirmed hits for every past session (session_date, symbol, type, ...)."""
    return load_csv("history/hits_history.csv")


def load_hits_for(session: str, history: pd.DataFrame | None = None) -> pd.DataFrame:
    """Hits for one session: the day's file if it is still kept, else the confirmed history rows."""
    df = load_csv(f"hits/{session}.csv")
    if df.empty and history is not None and not history.empty:
        df = history[history["session_date"] == session].copy()
    return df


def available_sessions(latest: dict, history: pd.DataFrame) -> list[str]:
    days = set()
    if latest.get("session_date"):
        days.add(latest["session_date"])
    if history is not None and not history.empty and "session_date" in history:
        days |= set(history["session_date"].dropna().astype(str))
    return sorted(days, reverse=True)
