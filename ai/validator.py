"""Python checks on the Analyst's JSON (the 'Validator' step)."""
from __future__ import annotations

import pandas as pd

REQUIRED = ["verdict", "trigger_type", "confidence", "surprise", "primary_catalysts", "price_news_alignment",
            "context_not_company_specific", "fundamental_base", "conflicts_and_rumours", "news_flow_quality",
            "what_to_watch"]


def validate(report: dict, evidence: list[dict], session: str, start: str) -> list[str]:
    """Return a list of problems (empty list = report passes)."""
    problems = []
    for k in REQUIRED:
        if k not in report:
            problems.append(f"missing key '{k}'")
    ev = {e["id"]: e for e in evidence}

    s = report.get("surprise") or {}
    try:
        score = int(s.get("surprise_score"))
        if not 0 <= score <= 100:
            problems.append("surprise_score must be 0-100")
    except (TypeError, ValueError):
        problems.append("surprise_score must be an integer")

    cats = report.get("primary_catalysts") or []
    no_cat = "no verified catalyst" in str(report.get("trigger_type", "")).lower()
    if not cats and not no_cat:
        problems.append("no primary_catalysts given but trigger_type is not 'No verified catalyst'")
    for c in cats:
        eid = str(c.get("evidence_id", "")).strip()
        if eid not in ev:
            problems.append(f"primary catalyst cites unknown evidence id '{eid}'")
            continue
        e = ev[eid]
        if not e.get("published_at"):
            problems.append(f"{eid} has no publication date, so it cannot be a primary catalyst")
        elif e["published_at"] < (pd.Timestamp(session) - pd.Timedelta(days=7)).strftime("%Y-%m-%d"):
            problems.append(f"{eid} is older than 7 days before the session")
        if e["scope"] != "COMPANY" and e.get("impact_link") != "direct":
            problems.append(f"{eid} is {e['scope']} scope with impact '{e.get('impact_link')}', "
                            "so it cannot be a primary catalyst")
        if str(c.get("timing", "")).lower().startswith("after") and len(cats) == 1:
            problems.append(f"{eid} was published after the move; it cannot be the only primary catalyst")

    for c in report.get("context_not_company_specific") or []:
        eid = str(c.get("evidence_id", "")).strip()
        if eid and eid.upper() != "HYPOTHESIS" and eid not in ev:
            problems.append(f"context item cites unknown evidence id '{eid}'")
    return problems
