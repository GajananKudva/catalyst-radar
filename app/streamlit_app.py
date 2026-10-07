"""52-Week High Catalyst Radar - Streamlit entry point.

Run locally:  streamlit run app/streamlit_app.py
On Streamlit Cloud set the secret DATA_URL to the raw URL of the repo's `data` branch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="52-Week High Catalyst Radar", page_icon=":material/radar:", layout="wide")

dashboard = st.Page("views/dashboard.py", title="Dashboard", icon=":material/monitoring:", default=True)
deep_dive = st.Page("views/deep_dive.py", title="Deep dive", icon=":material/troubleshoot:", url_path="deep-dive")
about = st.Page("views/about.py", title="How it works", icon=":material/info:", url_path="about")

st.session_state["_pages"] = {"dashboard": dashboard, "deep_dive": deep_dive}
st.navigation([dashboard, deep_dive, about]).run()
