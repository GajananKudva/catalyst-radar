COMPANY: {{COMPANY}} | NSE: {{SYMBOL}} | Sector: {{SECTOR}} | Industry: {{INDUSTRY}} | Cap: {{MCAP}}
GROUP / PARENT: {{GROUP}} | PEERS: {{PEERS}}
EVENT: 52-week {{KIND}} on {{SESSION}} (first crossed at {{FIRST_HIT}} IST)

PRICE ACTION
- Day {{KIND_LOWER}} Rs {{EXTREME}} vs prior 52-week {{KIND_LOWER}} Rs {{LEVEL}} set on {{LEVEL_DATE}} ({{BEYOND}}% beyond)
- Gap at open {{GAP}}% | change {{CHANGE}}% | volume {{VOLMULT}}x the 20-day average (pace {{VOLPACE}}x)
- Last price {{LTP}}; still beyond the level: {{HOLDING}} | 1-month return vs Nifty 50: {{RS}}%

SECTOR BREADTH TODAY: {{BREADTH}}
SCHEDULED EVENTS (Yahoo calendar): {{CALENDAR}}
EARNINGS VS ESTIMATES (FMP, latest first): {{EARNINGS}}
ANALYST GRADE CHANGES (FMP): {{GRADES}}
FUNDAMENTAL SNAPSHOT (Yahoo): {{FUNDAMENTALS}}
MACRO (FRED, context only, 1-week change): {{MACRO}}

EVIDENCE PACK (filtered to {{START}}..{{END}}, newest first; id | date | scope | impact | event | publisher | fact)
{{EVIDENCE}}

TASK: Explain why {{COMPANY}} hit its 52-week {{KIND_LOWER}} on {{SESSION}}. Lead with the news and how surprising it was. Return ONLY JSON in this schema:
{
  "verdict": "one sentence: the primary trigger and its date, or 'No verified catalyst'",
  "trigger_type": "Earnings beat | Order win | Guidance change | Rating or target change | Corporate action | Stake change | Regulatory or policy | M&A | Management change | Sector or industry move | Macro | Technical or flow | No verified catalyst",
  "trigger_scope": "COMPANY | STAKEHOLDER | PEER | INDUSTRY | GOVERNMENT | MACRO | NONE",
  "confidence": "High | Medium | Low",
  "confidence_reason": "one or two sentences",
  "surprise": {
    "scheduled": true,
    "expectation_gap": "e.g. PAT +38% YoY vs about 15% expected [E2], or 'not found in evidence'",
    "market_reaction": "e.g. gap +6.1%, 4.2x volume",
    "surprise_score": 0,
    "why_surprising": "what the market did not expect"
  },
  "primary_catalysts": [
    {"evidence_id": "E1", "date": "YYYY-MM-DD", "source": "publisher", "what_happened": "specific, with numbers",
     "why_it_moves_price": "link to earnings, cash flow or valuation", "timing": "before | same day | after"}
  ],
  "price_news_alignment": "did the news come before the gap and volume spike?",
  "context_not_company_specific": [
    {"evidence_id": "E5 or HYPOTHESIS", "scope": "STAKEHOLDER | PEER | INDUSTRY | GOVERNMENT | MACRO", "note": "..."}
  ],
  "fundamental_base": "at most two sentences, cite IDs or the snapshot",
  "conflicts_and_rumours": ["..."],
  "news_flow_quality": "Fresh (<=48h) | Recent (<=7d) | Thin | Stale, plus the date of the latest item",
  "what_to_watch": ["upcoming dated events or risks"],
  "excluded_items": [{"evidence_id": "E7", "reason": "..."}]
}
