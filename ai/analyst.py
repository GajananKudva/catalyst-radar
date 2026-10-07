"""AI 2 - the Analyst (reasoning Groq model): news-first explanation with citations."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from ai import llm, settings
from ai.collector import fill
from ai.sources import Diagnostics
from ai.validator import validate

PROMPTS = Path(__file__).resolve().parent / "prompts"


def _num(v, fmt="{:.2f}"):
    try:
        if v is None or pd.isna(v):
            return "n/a"
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "n/a"


def evidence_lines(evidence: list[dict]) -> str:
    if not evidence:
        return "(no evidence passed the filters)"
    return "\n".join(
        f"[{e['id']}] {e.get('published_at') or 'no date'} | {e['scope']} | {e.get('impact_link')} | "
        f"{e.get('event_type')} | {e.get('publisher')} | {e.get('fact') or e.get('title')}"
        for e in evidence)


def build_user_prompt(ctx: dict, evidence: list[dict]) -> str:
    row, prof, stake = ctx["row"], ctx["profile"], ctx["stake"]
    is_high = row["type"] == "HIGH"
    y = ctx.get("yahoo") or {}
    fundamentals = ", ".join(f"{k}={v}" for k, v in {
        "trailing P/E": _num(y.get("trailing_pe"), "{:.1f}"), "forward P/E": _num(y.get("forward_pe"), "{:.1f}"),
        "revenue growth": _num(y.get("revenue_growth"), "{:.1%}"),
        "earnings growth": _num(y.get("earnings_growth"), "{:.1%}"),
        "profit margin": _num(y.get("profit_margin"), "{:.1%}"),
        "promoter/insider holding": _num(y.get("held_by_insiders"), "{:.1%}"),
        "analyst view": y.get("recommendation") or "n/a",
    }.items())
    fmp = ctx.get("fmp") or {}
    return fill((PROMPTS / "analyst_user.md").read_text(encoding="utf-8"), {
        "COMPANY": prof["company"], "SYMBOL": prof["symbol"], "SECTOR": prof["sector"],
        "INDUSTRY": prof.get("industry"), "MCAP": prof.get("mcap"),
        "GROUP": stake.get("group_or_parent") or "none known", "PEERS": ", ".join(stake.get("peers") or []) or "-",
        "KIND": "HIGH" if is_high else "LOW", "KIND_LOWER": "high" if is_high else "low",
        "SESSION": prof["session"], "FIRST_HIT": row.get("first_hit") or "n/a",
        "EXTREME": _num(row["day_high"] if is_high else row["day_low"]),
        "LEVEL": _num(row["prior_52w_high"] if is_high else row["prior_52w_low"]),
        "LEVEL_DATE": row.get("prior_extreme_date") or "n/a", "BEYOND": _num(row.get("pct_beyond")),
        "GAP": _num(row.get("gap_pct")), "CHANGE": _num(row.get("change_pct")),
        "VOLMULT": _num(row.get("vol_multiple"), "{:.1f}"), "VOLPACE": _num(row.get("vol_pace"), "{:.1f}"),
        "LTP": _num(row.get("ltp")), "HOLDING": "yes" if row.get("still_beyond") else "no",
        "RS": _num(row.get("rs_vs_nifty_1m"), "{:.1f}"),
        "BREADTH": ctx.get("breadth_text") or "n/a",
        "CALENDAR": "; ".join(ctx.get("calendar") or []) or "none found",
        "EARNINGS": json.dumps(fmp.get("earnings") or [])[:600] or "none",
        "GRADES": json.dumps(fmp.get("grades") or [])[:500] or "none",
        "FUNDAMENTALS": fundamentals,
        "MACRO": "; ".join(f"{k} {v['value']} ({v['change_1w_pct']:+}%)" for k, v in (ctx.get("macro") or {}).items())
                 or "n/a",
        "START": prof["start"], "END": prof["end"], "EVIDENCE": evidence_lines(evidence),
    })


def analyse(ctx: dict, evidence: list[dict], *, diag: Diagnostics, client=None) -> dict:
    prof = ctx["profile"]
    system = fill((PROMPTS / "analyst_system.md").read_text(encoding="utf-8"),
                  {"KIND": prof["kind"], "SESSION": prof["session"], "SYMBOL": prof["symbol"]})
    user = build_user_prompt(ctx, evidence)
    model = settings.get("GROQ_ANALYST_MODEL")
    res = llm.chat_json(model, system, user, max_tokens=4000, effort="medium", client=client)
    diag.llm.append({"step": "analyse", "model": res.model, "prompt_tokens": res.prompt_tokens,
                     "completion_tokens": res.completion_tokens, "seconds": round(res.seconds, 1)})
    report = res.data
    problems = validate(report, evidence, prof["session"], prof["start"])
    if problems:
        # stay inside Groq's free-tier 8K tokens/minute: wait for the window to clear before the retry
        used = res.prompt_tokens + res.completion_tokens
        if used > 3500:
            time.sleep(max(0.0, 62 - res.seconds))
        fix = (user + "\n\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS - fix them and return the full JSON again:\n- "
               + "\n- ".join(problems) + "\n\nPREVIOUS ANSWER:\n" + json.dumps(report)[:2500])
        try:
            res2 = llm.chat_json(model, system, fix, max_tokens=4000, effort="medium", client=client)
            diag.llm.append({"step": "analyse_retry", "model": res2.model, "prompt_tokens": res2.prompt_tokens,
                             "completion_tokens": res2.completion_tokens, "seconds": round(res2.seconds, 1)})
            report2 = res2.data
            problems2 = validate(report2, evidence, prof["session"], prof["start"])
            if len(problems2) <= len(problems):
                report, problems = report2, problems2
        except llm.LLMError as exc:
            diag.notes.append(f"retry failed: {exc}")
    report["_validation"] = problems
    return report
