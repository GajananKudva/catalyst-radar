"""AI 1 - the Collector (fast Groq model).

1. plan():    stakeholder map + 9-12 targeted searches (one LLM call)
2. gather():  Python runs the searches on Tavily, Exa, NewsAPI, Finnhub and Yahoo
3. prefilter(): date window, de-duplication, ranking (no LLM)
4. tag():     the Collector tags each candidate: scope, impact link, event, fact, relevance (one LLM call)
5. select():  Python keeps the best items (max MAX_EVIDENCE) and numbers them E1..En
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from ai import llm, settings, sources
from ai.sources import Diagnostics

PROMPTS = Path(__file__).resolve().parent / "prompts"
SCOPES = ["COMPANY", "STAKEHOLDER", "PEER", "INDUSTRY", "GOVERNMENT", "MACRO"]
CATEGORIES = ["company", "promoters_group", "management", "investors_deals", "customers_suppliers", "peers",
              "industry", "government_policy", "brokerages", "index_events"]
LEGAL_SUFFIX = re.compile(r"\b(limited|ltd\.?|pvt\.?|private|india|industries|corporation|corp\.?|company|co\.?)\b", re.I)


def fill(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", "-" if v is None or v == "" else str(v))
    return template


def short_name(name: str) -> str:
    """'Jaykay Enterprises Limited' -> 'Jaykay Enterprises' (used for exact-phrase news search)."""
    s = re.sub(r"\b(limited|ltd\.?)\s*$", "", str(name).strip(), flags=re.I).strip(" .,")
    return s or str(name)


def alias_terms(company: str, symbol: str, aliases: list[str]) -> list[str]:
    terms = {symbol.lower(), short_name(company).lower()}
    core = LEGAL_SUFFIX.sub("", company).strip(" .,-")
    if len(core) >= 4:
        terms.add(re.sub(r"\s+", " ", core).lower())
    for a in aliases or []:
        if a and len(a) >= 3:
            terms.add(a.lower())
    return sorted(t for t in terms if t)


def mentions(item: dict, terms: list[str]) -> bool:
    text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


# ------------------------------------------------------------------ 1. plan
def plan(profile: dict, *, diag: Diagnostics, client=None) -> dict:
    prompt = fill((PROMPTS / "collector_plan.md").read_text(encoding="utf-8"), {
        "KIND": profile["kind"], "COMPANY": profile["company"], "SYMBOL": profile["symbol"],
        "SECTOR": profile["sector"], "INDUSTRY": profile.get("industry"), "MCAP": profile.get("mcap"),
        "SUMMARY": profile.get("summary") or "not available", "OFFICERS": ", ".join(profile.get("officers") or []),
        "SESSION": profile["session"], "START": profile["start"], "END": profile["end"],
        "PEERS_TODAY": ", ".join(profile.get("peers_today") or []) or "none",
    })
    res = llm.chat_json(settings.get("GROQ_QUICK_MODEL"), "You return only JSON.", prompt,
                        max_tokens=1500, effort="low", client=client)
    diag.llm.append({"step": "plan", "model": res.model, "prompt_tokens": res.prompt_tokens,
                     "completion_tokens": res.completion_tokens, "seconds": round(res.seconds, 1)})
    data = res.data
    queries = []
    for q in data.get("queries", [])[:12]:
        if isinstance(q, dict) and q.get("q"):
            cat = q.get("category") if q.get("category") in CATEGORIES else "company"
            queries.append({"category": cat, "q": str(q["q"])[:120]})
    data["queries"] = queries
    return data


# ---------------------------------------------------------------- 2. gather
def gather(profile: dict, stake: dict, *, diag: Diagnostics) -> list[dict]:
    start, end = pd.Timestamp(profile["start"]).date(), pd.Timestamp(profile["end"]).date()
    name, sym, yahoo = profile["company"], profile["symbol"], profile["yahoo"]
    jobs = []
    for q in stake.get("queries", []):
        if q["category"] == "government_policy":
            jobs.append(lambda q=q: sources.tavily_search(q["q"], start, end, category=q["category"], diag=diag,
                                                          include_domains=settings.GOV_DOMAINS, topic="general"))
        jobs.append(lambda q=q: sources.tavily_search(q["q"], start, end, category=q["category"], diag=diag))
    # fixed searches that don't depend on the plan
    jobs.append(lambda: sources.tavily_search(f"{short_name(name)} announcement", start, end, category="company",
                                              diag=diag, include_domains=settings.FILING_DOMAINS, topic="general"))
    jobs.append(lambda: sources.exa_search(f"{short_name(name)} {sym} news", start, category="company", diag=diag))
    jobs.append(lambda: sources.exa_search(f"{profile['sector']} sector India news", start, category="industry",
                                           diag=diag, num=4))
    jobs.append(lambda: sources.newsapi_search(short_name(name), start, end, diag=diag))
    jobs.append(lambda: sources.finnhub_news(yahoo, start, end, diag=diag))
    jobs.append(lambda: sources.yahoo_news(yahoo, diag=diag))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda f: f(), jobs))
    return [item for batch in results for item in batch]


# ------------------------------------------------------------- 3. prefilter
def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower())[:70]


def prefilter(items: list[dict], profile: dict, terms: list[str], exclude: list[str]) -> list[dict]:
    start, end = profile["start"], profile["end"]
    seen_url, seen_title, out = set(), set(), []
    for it in items:
        if not it.get("title") or not it.get("url"):
            continue
        u = re.sub(r"[?#].*$", "", it["url"]).rstrip("/").lower()
        t = _norm_title(it["title"])
        if u in seen_url or t in seen_title:
            continue
        d = it.get("published_at")
        if d and not (start <= d <= end):
            continue
        seen_url.add(u)
        seen_title.add(t)
        it = dict(it)
        it["names_company"] = mentions(it, terms)
        it["names_excluded"] = bool(exclude) and mentions(it, [e.lower() for e in exclude if e]) \
            and not it["names_company"]
        out.append(it)

    session = profile["session"]

    def rank(it):
        days = abs((pd.Timestamp(it["published_at"]) - pd.Timestamp(session)).days) if it.get("published_at") else 30
        return (not it["names_company"], it["query_category"] != "company", days)

    out.sort(key=rank)
    return out[:settings.MAX_CANDIDATES_FOR_TAGGING]


# ------------------------------------------------------------------- 4. tag
def tag(cands: list[dict], profile: dict, stake: dict, *, diag: Diagnostics, client=None) -> list[dict]:
    if not cands:
        return []
    lines = []
    for i, c in enumerate(cands, 1):
        c["cid"] = f"C{i}"
        lines.append(f"C{i} | {c.get('published_at') or 'no date'} | {c.get('publisher')} | {c['title']} | {c['snippet']}")
    prompt = fill((PROMPTS / "collector_tag.md").read_text(encoding="utf-8"), {
        "KIND": profile["kind"], "SESSION": profile["session"], "COMPANY": profile["company"],
        "SYMBOL": profile["symbol"], "ALIASES": ", ".join(stake.get("aliases") or []) or "-",
        "SECTOR": profile["sector"], "PRODUCTS": ", ".join(stake.get("products") or []) or "-",
        "EXCLUDE": ", ".join(stake.get("exclude_entities") or []) or "none",
        "CANDIDATES": "\n".join(lines),
    })
    res = llm.chat_json(settings.get("GROQ_QUICK_MODEL"), "You return only JSON.", prompt,
                        max_tokens=2400, effort="low", client=client)
    diag.llm.append({"step": "tag", "model": res.model, "prompt_tokens": res.prompt_tokens,
                     "completion_tokens": res.completion_tokens, "seconds": round(res.seconds, 1)})
    tags = {t.get("cid"): t for t in res.data.get("items", []) if isinstance(t, dict)}
    out = []
    for c in cands:
        t = tags.get(c["cid"])
        if not t:
            continue
        c = dict(c)
        c["keep"] = bool(t.get("keep", True))
        c["scope"] = str(t.get("scope", "OTHER")).upper().strip()
        c["impact_link"] = str(t.get("impact_link", "none")).lower().strip()
        c["event_type"] = t.get("event_type") or "other"
        c["fact"] = clean_fact(t.get("fact") or c["snippet"])
        try:
            c["relevance"] = max(0, min(5, int(t.get("relevance", 0))))
        except (TypeError, ValueError):
            c["relevance"] = 0
        out.append(c)
    return out


def clean_fact(s: str) -> str:
    return sources.clean(s, 260)


# ---------------------------------------------------------------- 5. select
def select(tagged: list[dict]) -> tuple[list[dict], list[dict]]:
    """Python backstops on the Collector's tags, then picks the evidence pack."""
    kept, dropped = [], []
    for c in tagged:
        reason = None
        if not c.get("keep") or c["scope"] not in SCOPES:
            reason = "tagged irrelevant"
        elif c["relevance"] < 2:
            reason = "low relevance"
        elif c["scope"] == "COMPANY" and not c.get("names_company"):
            # the article never names the company: cannot be company news
            c["scope"], c["impact_link"] = "STAKEHOLDER", "indirect"
            c["note"] = "re-tagged: article does not name the company"
        elif c.get("names_excluded") and c["scope"] == "COMPANY":
            c["scope"] = "STAKEHOLDER"
            c["note"] = "re-tagged: names a different group entity"
        (dropped if reason else kept).append({**c, "drop_reason": reason} if reason else c)

    scope_rank = {"COMPANY": 0, "GOVERNMENT": 1, "INDUSTRY": 2, "STAKEHOLDER": 3, "PEER": 4, "MACRO": 5}
    kept.sort(key=lambda c: (-c["relevance"], scope_rank.get(c["scope"], 9), c.get("published_at") is None))
    pack, rest = kept[:settings.MAX_EVIDENCE], kept[settings.MAX_EVIDENCE:]
    pack.sort(key=lambda c: c.get("published_at") or "0000", reverse=True)
    for i, c in enumerate(pack, 1):
        c["id"] = f"E{i}"
    dropped += [{**c, "drop_reason": "outside top evidence"} for c in rest]
    return pack, dropped
