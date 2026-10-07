"""API keys and model settings for the AI report.

Values come from Streamlit secrets (on Streamlit Cloud) or environment variables
(local runs). Keys are NEVER stored in the repository.
"""
from __future__ import annotations

import os

DEFAULTS = {
    "GROQ_QUICK_MODEL": "openai/gpt-oss-20b",     # AI 1 - Collector
    "GROQ_ANALYST_MODEL": "openai/gpt-oss-120b",  # AI 2 - Analyst
}

KEY_NAMES = ["GROQ_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "NEWSAPI_KEY",
             "FINNHUB_API_KEY", "FMP_API_KEY", "FRED_API_KEY"]

# search window around the 52-week session
NEWS_DAYS_BEFORE = 10
NEWS_DAYS_AFTER = 1
MAX_CANDIDATES_FOR_TAGGING = 20   # keeps the Collector's tagging call small (Groq free tier: 8K tokens/min)
MAX_EVIDENCE = 12                 # evidence items the Analyst sees
SNIPPET_CHARS = 240

GOV_DOMAINS = ["pib.gov.in", "sebi.gov.in", "rbi.org.in", "dgft.gov.in", "cbic.gov.in", "mca.gov.in"]
FILING_DOMAINS = ["nseindia.com", "bseindia.com"]
EXCLUDE_DOMAINS = ["reddit.com", "x.com", "twitter.com", "facebook.com", "youtube.com", "quora.com",
                   "instagram.com", "linkedin.com"]


def get(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default if default is not None else DEFAULTS.get(name)


def missing_keys(required: tuple[str, ...] = ("GROQ_API_KEY",)) -> list[str]:
    return [k for k in required if not get(k)]


def available_sources() -> dict[str, bool]:
    return {k: bool(get(k)) for k in KEY_NAMES}
