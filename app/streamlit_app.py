"""Dashboard - PART 2 placeholder.

For now this only proves the scanner -> data branch -> app path works:
it shows the scan status and the raw hits table. The full dashboard
(filters, KPIs, sector breadth, "Dive deeper" button) comes in part 2.

Run locally:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from data_loader import load_hits, load_latest

st.set_page_config(page_title="52-Week High Catalyst Radar", layout="wide")
st.title("52-Week High Catalyst Radar")


@st.cache_data(ttl=900)  # scanner updates every 15 minutes
def _load():
    latest = load_latest()
    return latest, load_hits(latest)


latest, hits = _load()
if not latest:
    st.warning("No scanner output yet. Run the nightly workflow once (or `python -m scanner.nightly` locally).")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Session", latest.get("session_date", "-"))
c2.metric("52-week highs", latest["counts"]["high"])
c3.metric("52-week lows", latest["counts"]["low"])
c4.metric("Coverage", f"{latest.get('coverage_pct', 0)}%")
st.caption(f"{latest.get('note', '')} - generated {latest.get('generated_at', '')} ({latest.get('market_state', '')})")

tab_hi, tab_lo = st.tabs(["52-week highs", "52-week lows"])
for tab, kind in ((tab_hi, "HIGH"), (tab_lo, "LOW")):
    with tab:
        df = hits[hits["type"] == kind] if not hits.empty else hits
        st.dataframe(df, use_container_width=True, hide_index=True)
