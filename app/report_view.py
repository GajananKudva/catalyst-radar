"""Renders the AI catalyst report on the deep-dive page."""
from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

SCOPE_BADGE = {"COMPANY": "blue", "STAKEHOLDER": "violet", "PEER": "orange", "INDUSTRY": "green",
               "GOVERNMENT": "red", "MACRO": "gray", "NONE": "gray"}
CONF_BADGE = {"high": "green", "medium": "orange", "low": "red"}
CACHE_HOURS = 6


@st.cache_resource
def _shared_reports() -> dict:
    """Reports shared by all users of the app for a few hours (saves API quota)."""
    return {}


def get_cached(key: tuple) -> dict | None:
    item = _shared_reports().get(key)
    if item and time.time() - item["t"] < CACHE_HOURS * 3600:
        return item["result"]
    return None


def put_cached(key: tuple, result: dict) -> None:
    _shared_reports()[key] = {"t": time.time(), "result": result}


def badge(text: str, color: str) -> str:
    safe = str(text).replace("[", "(").replace("]", ")")
    return f":{color}-badge[{safe}]"


def _ev_link(eid: str, evidence: dict) -> str:
    e = evidence.get(eid)
    if not e:
        return eid
    return f"[{eid}]({e['url']})"


def render(result: dict) -> None:
    rep = result.get("report", {})
    ev = {e["id"]: e for e in result.get("evidence", [])}
    meta = result.get("meta", {})

    # ---------------------------------------------------------------- verdict
    scope = str(rep.get("trigger_scope", "NONE")).upper()
    conf = str(rep.get("confidence", "")).strip()
    st.markdown(" ".join([
        badge(rep.get("trigger_type", "?"), "blue"),
        badge(f"scope: {scope.title()}", SCOPE_BADGE.get(scope, "gray")),
        badge(f"confidence: {conf or '?'}", CONF_BADGE.get(conf.lower(), "gray")),
    ]))
    verdict = rep.get("verdict", "")
    for eid in ev:
        verdict = verdict.replace(f"[{eid}]", f"[{eid}]({ev[eid]['url']})")
    st.info(f"**Verdict:** {verdict}", icon=":material/gavel:")
    if rep.get("confidence_reason"):
        st.caption(rep["confidence_reason"])
    if rep.get("_validation"):
        st.warning("Some automatic checks on this answer did not pass, so read it with care: "
                   + "; ".join(rep["_validation"][:4]), icon=":material/rule:")

    # ---------------------------------------------------------------- surprise
    s = rep.get("surprise") or {}
    left, right = st.columns([1, 2], gap="large")
    with left:
        try:
            score = int(s.get("surprise_score", 0))
        except (TypeError, ValueError):
            score = 0
        st.metric("Surprise score", f"{score}/100", "unscheduled" if s.get("scheduled") is False else
                  ("scheduled event" if s.get("scheduled") else None), delta_color="off", border=True)
        st.progress(min(max(score, 0), 100) / 100)
    with right:
        st.markdown(f"**Expectation gap:** {s.get('expectation_gap', '-')}  \n"
                    f"**Market reaction:** {s.get('market_reaction', '-')}  \n"
                    f"**Why it surprised:** {s.get('why_surprising', '-')}")

    # -------------------------------------------------------------- catalysts
    st.markdown("#### Primary catalysts")
    cats = rep.get("primary_catalysts") or []
    if not cats:
        st.caption("No company-specific catalyst could be verified from the evidence.")
    for c in cats:
        eid = str(c.get("evidence_id", ""))
        e = ev.get(eid, {})
        with st.container(border=True):
            st.markdown(f"**{_ev_link(eid, ev)} · {c.get('date') or e.get('published_at') or 'no date'} · "
                        f"{c.get('source') or e.get('publisher', '')}** "
                        + badge(e.get("scope", "?").title(), SCOPE_BADGE.get(e.get("scope", ""), "gray"))
                        + " " + badge(f"timing: {c.get('timing', '?')}", "gray"))
            st.markdown(f"{c.get('what_happened', '')}")
            st.caption(f"Why it moves the price: {c.get('why_it_moves_price', '-')}")
    if rep.get("price_news_alignment"):
        st.markdown(f"**Price–news alignment:** {rep['price_news_alignment']}")

    # ---------------------------------------------------------------- context
    a, b = st.columns(2, gap="large")
    with a:
        st.markdown("#### Context (not the trigger)")
        ctx_items = rep.get("context_not_company_specific") or []
        if not ctx_items:
            st.caption("None.")
        for c in ctx_items:
            eid = str(c.get("evidence_id", ""))
            sc = str(c.get("scope", "")).upper()
            st.markdown(f"- {badge(sc.title() or 'Context', SCOPE_BADGE.get(sc, 'gray'))} "
                        f"{_ev_link(eid, ev) if eid in ev else eid}: {c.get('note', '')}")
        st.markdown("#### Fundamental base")
        st.markdown(rep.get("fundamental_base") or "-")
    with b:
        st.markdown("#### Conflicts & rumours")
        rum = rep.get("conflicts_and_rumours") or []
        st.markdown("\n".join(f"- {r}" for r in rum) if rum else "None found.")
        st.markdown("#### News flow")
        st.markdown(rep.get("news_flow_quality") or "-")
        st.markdown("#### What to watch")
        watch = rep.get("what_to_watch") or []
        st.markdown("\n".join(f"- {w}" for w in watch) if watch else "-")

    # ---------------------------------------------------------------- details
    with st.expander(f"Evidence pack ({len(ev)} items the Analyst AI saw)", icon=":material/library_books:"):
        if ev:
            df = pd.DataFrame([{
                "ID": e["id"], "Date": e.get("published_at") or "no date", "Scope": e["scope"],
                "Impact": e.get("impact_link"), "Event": e.get("event_type"), "Relevance": e.get("relevance"),
                "Publisher": e.get("publisher"), "Fact": e.get("fact"), "Link": e.get("url"),
                "Note": e.get("note", ""), "Found by": e.get("source_api")} for e in ev.values()])
            st.dataframe(df, hide_index=True, column_config={"Link": st.column_config.LinkColumn("Link")})
        else:
            st.caption("No articles passed the date, duplicate and relevance filters.")
    with st.expander("Stakeholder map and searches (Collector AI)", icon=":material/hub:"):
        sh = result.get("stakeholders", {})
        st.json(sh, expanded=False)
        q = result.get("queries", [])
        if q:
            st.dataframe(pd.DataFrame(q), hide_index=True)
    with st.expander("Filtered out", icon=":material/filter_alt:"):
        dropped = result.get("dropped", [])
        if dropped:
            st.dataframe(pd.DataFrame([{"Date": d.get("published_at"), "Publisher": d.get("publisher"),
                                        "Title": d.get("title"), "Scope": d.get("scope"),
                                        "Relevance": d.get("relevance"), "Why": d.get("drop_reason"),
                                        "Link": d.get("url")} for d in dropped]),
                         hide_index=True, column_config={"Link": st.column_config.LinkColumn("Link")})
        excl = rep.get("excluded_items") or []
        if excl:
            st.markdown("**Excluded by the Analyst AI:** " + "; ".join(
                f"{x.get('evidence_id')}: {x.get('reason')}" for x in excl))
        if not dropped and not excl:
            st.caption("Nothing filtered out.")
    with st.expander("Diagnostics (sources, models, timing)", icon=":material/monitor_heart:"):
        diag = result.get("diagnostics", {})
        src = diag.get("sources", {})
        if src:
            st.dataframe(pd.DataFrame([{"Source": k, "Calls": v["calls"], "Results": v["results"],
                                        "Errors": " | ".join(v["errors"])[:300]} for k, v in src.items()]),
                         hide_index=True)
        if diag.get("llm"):
            st.dataframe(pd.DataFrame(diag["llm"]), hide_index=True)
        for n in diag.get("notes", []):
            st.caption(n)
        st.caption(f"Models: collector {meta.get('models', {}).get('collector')}, analyst "
                   f"{meta.get('models', {}).get('analyst')} · generated {meta.get('generated_at')} "
                   f"in {meta.get('seconds')} s · news window {' to '.join(meta.get('window', []))}")
    st.download_button("Download report (JSON)", json.dumps(result, indent=2, default=str).encode(),
                       file_name=f"catalyst_{meta.get('symbol')}_{meta.get('session')}.json",
                       mime="application/json", icon=":material/download:")
    st.caption("AI-generated from the cited sources. Decision support only, not investment advice.")
