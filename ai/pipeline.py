"""End-to-end AI catalyst report for one 52-week hit.

    report = run(row, hits_today, universe, progress=callback)

Steps (each reported through `progress(step, message)`):
  profile -> plan (AI 1) -> gather (APIs) -> prefilter -> tag (AI 1) -> select -> context (FMP, FRED,
  Yahoo calendar) -> analyse (AI 2) -> validate (Python, one retry)
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import pandas as pd

from ai import analyst, collector, settings, sources
from ai.sources import Diagnostics

Progress = Callable[[str, str], None]


def _noop(step: str, msg: str) -> None:
    pass


def breadth_text(row: dict, hits: pd.DataFrame, universe: pd.DataFrame | None) -> tuple[str, list[str]]:
    sector, kind = row.get("sector"), row.get("type")
    if not sector or sector == "Unclassified" or hits is None or hits.empty:
        return "sector unknown", []
    same = hits[(hits["sector"] == sector) & (hits["type"] == kind)]
    if "status" in same:
        same = same[same["status"] != "not_confirmed"]
    peers = [s for s in same["nse_symbol"].astype(str).tolist() if s != row.get("nse_symbol")]
    total = int((universe["sector"] == sector).sum()) if universe is not None and not universe.empty else 0
    word = "highs" if kind == "HIGH" else "lows"
    txt = f"{len(same)} of {total or '?'} {sector} stocks made 52-week {word} this session"
    if peers:
        txt += f" (peers: {', '.join(peers[:8])})"
    return txt, peers[:8]


def run(row: dict, hits: pd.DataFrame, universe: pd.DataFrame | None, *, progress: Progress = _noop,
        client=None) -> dict:
    t0 = time.time()
    diag = Diagnostics()
    missing = settings.missing_keys()
    if missing:
        raise RuntimeError(f"Missing secret(s): {', '.join(missing)}. Add them in Streamlit -> Settings -> Secrets.")

    session = str(row["session_date"])
    start, end = sources.window(session)
    kind = "HIGH" if row["type"] == "HIGH" else "LOW"
    yahoo = row["symbol"]

    # ---- profile
    progress("profile", "Reading the company profile")
    yprof = sources.yahoo_profile(yahoo, diag=diag)
    industry = None
    if universe is not None and not universe.empty and "industry" in universe:
        m = universe.loc[universe["yahoo"] == yahoo, "industry"]
        industry = None if m.empty or pd.isna(m.iloc[0]) else m.iloc[0]
    btxt, peers_today = breadth_text(row, hits, universe)
    profile = {
        "company": row.get("name") or row.get("nse_symbol"), "symbol": row.get("nse_symbol"), "yahoo": yahoo,
        "sector": row.get("sector"), "industry": industry or yprof.get("yahoo_industry"),
        "mcap": row.get("mcap_bucket"), "summary": yprof.get("summary"), "officers": yprof.get("officers"),
        "kind": kind, "session": session, "start": start.isoformat(), "end": end.isoformat(),
        "peers_today": peers_today,
    }

    # ---- AI 1: plan
    progress("plan", "Collector AI is mapping stakeholders and planning searches")
    stake = collector.plan(profile, diag=diag, client=client)

    # ---- gather
    progress("gather", f"Searching {len(stake['queries'])} planned queries + company news feeds")
    raw = collector.gather(profile, stake, diag=diag)
    terms = collector.alias_terms(profile["company"], profile["symbol"], stake.get("aliases") or [])
    cands = collector.prefilter(raw, profile, terms, stake.get("exclude_entities") or [])
    diag.notes.append(f"{len(raw)} articles found, {len(cands)} kept for tagging after date/duplicate filters")

    # ---- AI 1: tag
    progress("tag", f"Collector AI is tagging {len(cands)} articles")
    tagged = collector.tag(cands, profile, stake, diag=diag, client=client) if cands else []
    evidence, dropped = collector.select(tagged)

    # ---- structured context
    progress("context", "Fetching earnings, analyst grades, calendar and macro data")
    calendar = sources.yahoo_calendar(yahoo, diag=diag)
    fmp = sources.fmp_context(yahoo, diag=diag)
    macro = sources.fred_snapshot(end, diag=diag)

    # ---- AI 2: analyse (+ validate inside)
    progress("analyse", f"Analyst AI is reasoning over {len(evidence)} evidence items")
    ctx = {"row": row, "profile": profile, "stake": stake, "yahoo": yprof, "fmp": fmp, "macro": macro,
           "calendar": calendar, "breadth_text": btxt}
    report = analyst.analyse(ctx, evidence, diag=diag, client=client)

    progress("done", "Report ready")
    return {
        "report": report,
        "evidence": evidence,
        "dropped": dropped,
        "stakeholders": {k: v for k, v in stake.items() if k != "queries"},
        "queries": stake.get("queries", []),
        "context": {"breadth": btxt, "calendar": calendar, "fmp": fmp, "macro": macro,
                    "fundamentals": {k: yprof.get(k) for k in ("trailing_pe", "forward_pe", "revenue_growth",
                                                               "earnings_growth", "profit_margin", "recommendation")}},
        "meta": {"symbol": profile["symbol"], "company": profile["company"], "session": session, "kind": kind,
                 "window": [profile["start"], profile["end"]],
                 "generated_at": datetime.now().isoformat(timespec="seconds"),
                 "seconds": round(time.time() - t0, 1),
                 "models": {"collector": settings.get("GROQ_QUICK_MODEL"),
                            "analyst": settings.get("GROQ_ANALYST_MODEL")}},
        "diagnostics": diag.as_dict(),
    }
