"""Data fetchers used by the Collector. Python calls the APIs; the AIs only read results.

Every news fetcher returns a list of evidence candidates:
    {source_api, publisher, title, url, published_at (YYYY-MM-DD or None), snippet, query_category}
and records calls / results / errors in a shared Diagnostics object, so the app
can show exactly what each source returned.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import pandas as pd
import requests

from ai import settings

log = logging.getLogger(__name__)
TIMEOUT = 25


@dataclass
class Diagnostics:
    sources: dict = field(default_factory=dict)   # name -> {"calls", "results", "errors": []}
    llm: list = field(default_factory=list)       # one dict per model call
    notes: list = field(default_factory=list)

    def record(self, name: str, n: int = 0, error: str | None = None) -> None:
        s = self.sources.setdefault(name, {"calls": 0, "results": 0, "errors": []})
        s["calls"] += 1
        s["results"] += n
        if error:
            s["errors"].append(error[:300])

    def as_dict(self) -> dict:
        return {"sources": self.sources, "llm": self.llm, "notes": self.notes}


# ---------------------------------------------------------------- helpers
def to_date(value) -> str | None:
    """Normalise many date formats (ISO, RFC 2822, epoch seconds) to YYYY-MM-DD."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.tz_convert("Asia/Kolkata").strftime("%Y-%m-%d")
    except Exception:
        return None


def publisher_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def clean(text: str | None, n: int = settings.SNIPPET_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:n]


def _item(source: str, title, url, published, snippet, category: str, publisher: str | None = None) -> dict:
    return {"source_api": source, "publisher": publisher or publisher_of(url), "title": clean(title, 200),
            "url": url or "", "published_at": to_date(published), "snippet": clean(snippet),
            "query_category": category}


# ------------------------------------------------------------------ Tavily
def tavily_search(query: str, start: date, end: date, *, category: str, diag: Diagnostics,
                  include_domains: list[str] | None = None, topic: str = "news", max_results: int = 6) -> list[dict]:
    key = settings.get("TAVILY_API_KEY")
    if not key:
        return []
    body = {"query": query, "topic": topic, "search_depth": "basic", "max_results": max_results,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "exclude_domains": settings.EXCLUDE_DOMAINS, "include_answer": False}
    if include_domains:
        body["include_domains"] = include_domains
    try:
        r = requests.post("https://api.tavily.com/search", json=body, timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        res = r.json().get("results", [])
        out = [_item("tavily", x.get("title"), x.get("url"), x.get("published_date"), x.get("content"), category)
               for x in res]
        diag.record("tavily", len(out))
        return out
    except Exception as exc:
        diag.record("tavily", 0, f"{query[:60]}: {exc}")
        return []


# --------------------------------------------------------------------- Exa
def exa_search(query: str, start: date, *, category: str, diag: Diagnostics, num: int = 6) -> list[dict]:
    key = settings.get("EXA_API_KEY")
    if not key:
        return []
    body = {"query": query, "type": "auto", "category": "news", "numResults": num,
            "startPublishedDate": f"{start.isoformat()}T00:00:00Z",
            "contents": {"text": {"maxCharacters": 600}}}
    try:
        r = requests.post("https://api.exa.ai/search", json=body, timeout=TIMEOUT, headers={"x-api-key": key})
        r.raise_for_status()
        res = r.json().get("results", [])
        out = [_item("exa", x.get("title"), x.get("url"), x.get("publishedDate"),
                     x.get("text") or " ".join(x.get("highlights") or []), category) for x in res]
        diag.record("exa", len(out))
        return out
    except Exception as exc:
        diag.record("exa", 0, f"{query[:60]}: {exc}")
        return []


# ----------------------------------------------------------------- NewsAPI
def newsapi_search(phrase: str, start: date, end: date, *, diag: Diagnostics, page_size: int = 15) -> list[dict]:
    key = settings.get("NEWSAPI_KEY")
    if not key:
        return []
    params = {"q": f'"{phrase}"', "from": start.isoformat(), "to": end.isoformat(), "language": "en",
              "sortBy": "publishedAt", "pageSize": page_size, "searchIn": "title,description"}
    try:
        r = requests.get("https://newsapi.org/v2/everything", params=params, timeout=TIMEOUT,
                         headers={"X-Api-Key": key})
        data = r.json()
        if data.get("status") != "ok":
            raise RuntimeError(data.get("message") or f"HTTP {r.status_code}")
        out = [_item("newsapi", a.get("title"), a.get("url"), a.get("publishedAt"), a.get("description"),
                     "company", publisher=(a.get("source") or {}).get("name")) for a in data.get("articles", [])]
        diag.record("newsapi", len(out))
        return out
    except Exception as exc:
        diag.record("newsapi", 0, str(exc))
        return []


# ----------------------------------------------------------------- Finnhub
def finnhub_news(yahoo_symbol: str, start: date, end: date, *, diag: Diagnostics) -> list[dict]:
    """Company news. Finnhub's free plan mostly covers US companies, so this is often empty for NSE stocks."""
    key = settings.get("FINNHUB_API_KEY")
    if not key:
        return []
    if yahoo_symbol.upper().endswith((".NS", ".BO")):
        diag.notes.append("Finnhub skipped: its free plan does not cover NSE/BSE company news")
        return []
    params = {"symbol": yahoo_symbol, "from": start.isoformat(), "to": end.isoformat(), "token": key}
    try:
        r = requests.get("https://finnhub.io/api/v1/company-news", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):  # error payload
            raise RuntimeError(data.get("error") or str(data)[:200])
        out = [_item("finnhub", a.get("headline"), a.get("url"), a.get("datetime"), a.get("summary"), "company",
                     publisher=a.get("source")) for a in data[:15]]
        diag.record("finnhub", len(out))
        return out
    except Exception as exc:
        diag.record("finnhub", 0, str(exc))
        return []


# ---------------------------------------------------------------- yfinance
def yahoo_profile(yahoo_symbol: str, *, diag: Diagnostics) -> dict:
    try:
        import yfinance as yf
        info = yf.Ticker(yahoo_symbol).info or {}
        officers = [o.get("name") for o in (info.get("companyOfficers") or [])[:4] if o.get("name")]
        prof = {
            "long_name": info.get("longName"), "website": info.get("website"),
            "summary": clean(info.get("longBusinessSummary"), 700),
            "yahoo_sector": info.get("sector"), "yahoo_industry": info.get("industry"),
            "officers": officers, "market_cap": info.get("marketCap"),
            "trailing_pe": info.get("trailingPE"), "forward_pe": info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"), "earnings_growth": info.get("earningsGrowth"),
            "profit_margin": info.get("profitMargins"), "held_by_insiders": info.get("heldPercentInsiders"),
            "held_by_institutions": info.get("heldPercentInstitutions"),
            "target_mean_price": info.get("targetMeanPrice"), "recommendation": info.get("recommendationKey"),
        }
        diag.record("yahoo_profile", 1)
        return prof
    except Exception as exc:
        diag.record("yahoo_profile", 0, str(exc))
        return {}


def yahoo_calendar(yahoo_symbol: str, *, diag: Diagnostics) -> list[str]:
    """Known scheduled events (earnings / dividend dates) from Yahoo."""
    try:
        import yfinance as yf
        cal = yf.Ticker(yahoo_symbol).calendar or {}
        events = []
        for k in ("Earnings Date", "Ex-Dividend Date", "Dividend Date"):
            v = cal.get(k) if isinstance(cal, dict) else None
            if v:
                vals = v if isinstance(v, (list, tuple)) else [v]
                events.append(f"{k}: " + ", ".join(str(x) for x in vals))
        diag.record("yahoo_calendar", len(events))
        return events
    except Exception as exc:
        diag.record("yahoo_calendar", 0, str(exc))
        return []


def yahoo_news(yahoo_symbol: str, *, diag: Diagnostics) -> list[dict]:
    try:
        import yfinance as yf
        items = yf.Ticker(yahoo_symbol).news or []
        out = []
        for n in items[:15]:
            c = n.get("content", n)  # newer yfinance nests fields under "content"
            url = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict)
                   else None) or c.get("link") or ""
            out.append(_item("yahoo", c.get("title"), url, c.get("pubDate") or c.get("providerPublishTime"),
                             c.get("summary") or c.get("description"), "company",
                             publisher=(c.get("provider") or {}).get("displayName")
                             if isinstance(c.get("provider"), dict) else c.get("publisher")))
        diag.record("yahoo_news", len(out))
        return out
    except Exception as exc:
        diag.record("yahoo_news", 0, str(exc))
        return []


# --------------------------------------------------------------------- FMP
def fmp_get(path: str, params: dict, *, diag: Diagnostics, name: str):
    key = settings.get("FMP_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(f"https://financialmodelingprep.com/stable/{path}", params={**params, "apikey": key},
                         timeout=TIMEOUT)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}") from None
        if r.status_code != 200 or (isinstance(data, dict) and data.get("Error Message")):
            raise RuntimeError((data.get("Error Message") if isinstance(data, dict) else "") or f"HTTP {r.status_code}")
        diag.record(f"fmp_{name}", len(data) if isinstance(data, list) else 1)
        return data
    except Exception as exc:
        diag.record(f"fmp_{name}", 0, str(exc))
        return None


def fmp_context(yahoo_symbol: str, *, diag: Diagnostics) -> dict:
    """Earnings vs estimates and analyst grade changes (FMP coverage of NSE varies by plan)."""
    out: dict = {"earnings": [], "grades": []}
    earn = fmp_get("earnings", {"symbol": yahoo_symbol, "limit": 4}, diag=diag, name="earnings")
    if isinstance(earn, list):
        for e in earn[:4]:
            out["earnings"].append({k: e.get(k) for k in ("date", "epsActual", "epsEstimated",
                                                          "revenueActual", "revenueEstimated")})
    grades = fmp_get("grades", {"symbol": yahoo_symbol, "limit": 5}, diag=diag, name="grades")
    if isinstance(grades, list):
        for g in grades[:5]:
            out["grades"].append({k: g.get(k) for k in ("date", "gradingCompany", "previousGrade", "newGrade", "action")})
    return out


# -------------------------------------------------------------------- FRED
FRED_SERIES = {"Brent crude ($/bbl)": "DCOILBRENTEU", "USD/INR": "DEXINUS", "US 10Y yield (%)": "DGS10"}


def fred_snapshot(end: date, *, diag: Diagnostics) -> dict:
    key = settings.get("FRED_API_KEY")
    if not key:
        return {}
    out = {}
    for label, sid in FRED_SERIES.items():
        params = {"series_id": sid, "api_key": key, "file_type": "json", "sort_order": "desc",
                  "observation_end": end.isoformat(), "limit": 15}
        try:
            r = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None)]
            if len(obs) >= 2:
                last, wk = float(obs[0]["value"]), float(obs[min(5, len(obs) - 1)]["value"])
                out[label] = {"value": last, "date": obs[0]["date"], "change_1w_pct": round((last / wk - 1) * 100, 2)}
            diag.record("fred", 1)
        except Exception as exc:
            diag.record("fred", 0, f"{sid}: {exc}")
    return out


def window(session: str) -> tuple[date, date]:
    s = pd.Timestamp(session).date()
    return s - timedelta(days=settings.NEWS_DAYS_BEFORE), s + timedelta(days=settings.NEWS_DAYS_AFTER)
