"""Offline tests for the AI pipeline: fake Groq client + mocked news sources (no network, no keys)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai import collector, llm, pipeline, settings, sources, validator  # noqa: E402

SESSION = "2026-10-07"


# --------------------------------------------------------------- fakes
class FakeCompletions:
    def __init__(self, analyst_answers):
        self.calls = []
        self.analyst_answers = list(analyst_answers)

    def create(self, model, messages, **kw):
        self.calls.append({"model": model, "messages": messages, **kw})
        system, user = messages[0]["content"], messages[1]["content"]
        if "research planner" in user:
            data = {"aliases": ["Acme"], "group_or_parent": "Acme Group", "exclude_entities": ["Acme Finance"],
                    "key_people": ["R. Rao"], "products": ["solar glass"], "raw_materials": ["soda ash"],
                    "customers": ["solar module makers"], "peers": ["Borosil Renewables"],
                    "regulators": ["DGTR"],
                    "queries": [{"category": "company", "q": "Acme Solar Glass order"},
                                {"category": "government_policy", "q": "anti-dumping duty solar glass India"},
                                {"category": "bogus", "q": "Acme results"}]}
        elif "news tagger" in user:
            items = []
            for line in user.split("CANDIDATES")[1].splitlines():
                if line.startswith("C"):
                    cid = line.split(" |")[0]
                    if "duty" in line:
                        items.append({"cid": cid, "keep": True, "scope": "GOVERNMENT", "impact_link": "direct",
                                      "event_type": "regulatory_policy", "fact": "DGTR duty on Chinese solar glass",
                                      "relevance": 5})
                    elif "Acme Solar Glass wins" in line:
                        items.append({"cid": cid, "keep": True, "scope": "COMPANY", "impact_link": "direct",
                                      "event_type": "order_win", "fact": "Rs 300 cr order", "relevance": 4})
                    elif "Sector" in line:
                        items.append({"cid": cid, "keep": True, "scope": "COMPANY", "impact_link": "direct",
                                      "event_type": "sector_rally", "fact": "sector up", "relevance": 3})
                    else:
                        items.append({"cid": cid, "keep": False, "scope": "OTHER", "impact_link": "none",
                                      "event_type": "other", "fact": "", "relevance": 0})
            data = {"items": items}
        else:
            import re
            gov = re.search(r"\[(E\d+)\] [0-9-]+ \| GOVERNMENT", user)
            data = json.loads(json.dumps(self.analyst_answers.pop(0)).replace("GOVID", gov.group(1) if gov else "E0"))
        msg = SimpleNamespace(content=json.dumps(data))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


def fake_client(answers):
    comp = FakeCompletions(answers)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


GOOD = {
    "verdict": "A new anti-dumping duty on Chinese solar glass (06-10) [GOVID]",
    "trigger_type": "Regulatory or policy", "trigger_scope": "GOVERNMENT", "confidence": "High",
    "confidence_reason": "dated notification before the gap",
    "surprise": {"scheduled": False, "expectation_gap": "not found in evidence", "market_reaction": "gap +4%",
                 "surprise_score": 85, "why_surprising": "unscheduled"},
    "primary_catalysts": [{"evidence_id": "GOVID", "date": "2026-10-06", "source": "pib.gov.in",
                           "what_happened": "duty", "why_it_moves_price": "pricing power", "timing": "before"}],
    "price_news_alignment": "news before open", "context_not_company_specific": [],
    "fundamental_base": "ok", "conflicts_and_rumours": [], "news_flow_quality": "Fresh", "what_to_watch": [],
    "excluded_items": [],
}


@pytest.fixture
def mocked_sources(monkeypatch):
    def tavily(q, start, end, *, category, diag, include_domains=None, topic="news", max_results=6):
        diag.record("tavily", 1)
        if include_domains and "pib.gov.in" in include_domains:
            return [sources._item("tavily", "Govt imposes anti-dumping duty on solar glass", "https://pib.gov.in/x",
                                  "2026-10-06", "DGTR duty on Chinese solar glass imports", category)]
        return [sources._item("tavily", "Acme Solar Glass wins Rs 300 cr order", "https://news.example/a",
                              "2026-10-05T08:00:00Z", "Acme Solar Glass Ltd bagged an order", category),
                sources._item("tavily", "Old story", "https://news.example/old", "2026-08-01", "old", category)]

    monkeypatch.setattr(sources, "tavily_search", tavily)
    monkeypatch.setattr(sources, "exa_search", lambda *a, **k: [sources._item(
        "exa", "Sector stocks rally", "https://news.example/s", "2026-10-07", "solar stocks up", "industry")])
    monkeypatch.setattr(sources, "newsapi_search", lambda *a, **k: [sources._item(
        "newsapi", "Acme Solar Glass wins Rs 300 cr order", "https://news.example/a?utm=1", "2026-10-05",
        "duplicate", "company")])
    monkeypatch.setattr(sources, "finnhub_news", lambda *a, **k: [])
    monkeypatch.setattr(sources, "yahoo_news", lambda *a, **k: [])
    monkeypatch.setattr(sources, "yahoo_profile", lambda *a, **k: {"summary": "Makes solar glass",
                                                                    "officers": ["R. Rao"]})
    monkeypatch.setattr(sources, "yahoo_calendar", lambda *a, **k: ["Earnings Date: 2026-10-28"])
    monkeypatch.setattr(sources, "fmp_context", lambda *a, **k: {"earnings": [], "grades": []})
    monkeypatch.setattr(sources, "fred_snapshot", lambda *a, **k: {})
    monkeypatch.setenv("GROQ_API_KEY", "test-key")


ROW = {"session_date": SESSION, "symbol": "ACME.NS", "nse_symbol": "ACME", "name": "Acme Solar Glass Limited",
       "sector": "Capital Goods", "mcap_bucket": "Small", "type": "HIGH", "status": "confirmed",
       "day_high": 110.0, "day_low": 100.0, "prior_52w_high": 105.0, "prior_52w_low": 60.0,
       "pct_beyond": 4.76, "gap_pct": 4.0, "change_pct": 6.0, "vol_multiple": 3.2, "vol_pace": 3.2,
       "ltp": 109.0, "still_beyond": True, "rs_vs_nifty_1m": 10.0, "first_hit": "09:20",
       "prior_extreme_date": "2026-03-01"}
HITS = pd.DataFrame([ROW, {**ROW, "symbol": "BORO.NS", "nse_symbol": "BORO", "name": "Boro"}])
UNI = pd.DataFrame({"yahoo": ["ACME.NS", "BORO.NS", "X.NS"], "sector": ["Capital Goods"] * 3,
                    "industry": [None, None, None]})


# --------------------------------------------------------------- tests
def test_pipeline_end_to_end(mocked_sources):
    client, comp = fake_client([GOOD])
    out = pipeline.run(ROW, HITS, UNI, client=client)
    ev = {e["id"]: e for e in out["evidence"]}
    assert out["report"]["_validation"] == []
    assert out["report"]["trigger_scope"] == "GOVERNMENT"
    # newest first; duplicate NewsAPI article and the old story are gone
    dates = [e["published_at"] for e in out["evidence"]]
    assert dates == sorted(dates, reverse=True) and ev["E1"]["published_at"] == "2026-10-07"
    assert any(e["scope"] == "GOVERNMENT" for e in out["evidence"])
    titles = [e["title"] for e in out["evidence"]]
    assert titles.count("Acme Solar Glass wins Rs 300 cr order") == 1 and "Old story" not in titles
    # the 'Sector stocks rally' item was tagged COMPANY but never names Acme -> re-tagged by Python
    sector = next(e for e in out["evidence"] if e["title"] == "Sector stocks rally")
    assert sector["scope"] == "STAKEHOLDER" and "re-tagged" in sector["note"]
    # bogus query category normalised; models: two collector calls + one analyst call
    assert all(q["category"] in collector.CATEGORIES for q in out["queries"])
    models = [c["model"] for c in comp.calls]
    assert models == [settings.DEFAULTS["GROQ_QUICK_MODEL"]] * 2 + [settings.DEFAULTS["GROQ_ANALYST_MODEL"]]
    assert comp.calls[-1]["extra_body"]["reasoning_effort"] == "medium"
    assert "1 of 3 Capital Goods" not in out["context"]["breadth"] and "2 of 3" in out["context"]["breadth"]


def test_validator_triggers_one_retry(mocked_sources, monkeypatch):
    bad = json.loads(json.dumps(GOOD))
    bad["primary_catalysts"][0]["evidence_id"] = "E99"
    monkeypatch.setattr("time.sleep", lambda s: None)
    client, comp = fake_client([bad, GOOD])
    out = pipeline.run(ROW, HITS, UNI, client=client)
    assert len(comp.calls) == 4 and out["report"]["_validation"] == []
    assert "FAILED THESE CHECKS" in comp.calls[-1]["messages"][1]["content"]


def test_validator_rules():
    ev = [{"id": "E1", "scope": "INDUSTRY", "impact_link": "indirect", "published_at": "2026-10-06"},
          {"id": "E2", "scope": "COMPANY", "impact_link": "direct", "published_at": None}]
    rep = json.loads(json.dumps(GOOD))
    rep["primary_catalysts"] = [{"evidence_id": "E1", "timing": "before"}, {"evidence_id": "E2"}]
    probs = validator.validate(rep, ev, SESSION, "2026-09-27")
    assert any("INDUSTRY scope" in p for p in probs) and any("no publication date" in p for p in probs)
    rep2 = json.loads(json.dumps(GOOD))
    rep2["primary_catalysts"], rep2["trigger_type"] = [], "No verified catalyst"
    assert validator.validate(rep2, ev, SESSION, "2026-09-27") == []


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(settings, "get", lambda name, default=None: None)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        pipeline.run(ROW, HITS, UNI)


def test_helpers():
    assert sources.to_date("2026-10-05T23:30:00Z") == "2026-10-06"          # converted to IST
    assert sources.to_date("Mon, 05 Oct 2026 10:00:00 GMT") == "2026-10-05"
    assert sources.to_date(1791200000) is not None and sources.to_date("garbage") is None
    assert llm.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json('Here you go: {"a": 2} thanks') == {"a": 2}
    assert collector.short_name("Jaykay Enterprises Limited") == "Jaykay Enterprises"
    terms = collector.alias_terms("HFCL Limited", "HFCL", ["Himachal Futuristic"])
    assert collector.mentions({"title": "HFCL bags 5G order", "snippet": ""}, terms)
    assert not collector.mentions({"title": "Telecom stocks rally", "snippet": ""}, terms)
