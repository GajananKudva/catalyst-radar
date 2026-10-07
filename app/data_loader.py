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


def _data_url() -> str | None:
    url = os.getenv("DATA_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATA_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    return url.rstrip("/") if url else None


def _read_text(rel_path: str) -> str | None:
    url = _data_url()
    if url:
        r = requests.get(f"{url}/{rel_path}", timeout=20)
        return r.text if r.status_code == 200 else None
    p = Path(config.DATA_DIR) / rel_path
    return p.read_text(encoding="utf-8") if p.exists() else None


def load_latest() -> dict:
    txt = _read_text("latest.json")
    return json.loads(txt) if txt else {}


def load_csv(rel_path: str) -> pd.DataFrame:
    txt = _read_text(rel_path)
    return pd.read_csv(io.StringIO(txt)) if txt else pd.DataFrame()


def load_hits(latest: dict | None = None) -> pd.DataFrame:
    latest = latest if latest is not None else load_latest()
    rel = latest.get("hits_file")
    return load_csv(rel) if rel else pd.DataFrame()


def load_universe() -> pd.DataFrame:
    return load_csv("universe.csv")
