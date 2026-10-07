"""PART 3 - AI and news integration (to be built next).

Planned modules:
  collector.py  AI 1 (small, fast Groq model): builds the stakeholder map, plans
                searches (company, promoters, management, investors, customers &
                suppliers, peers, industry, government & regulators, brokerages,
                index events, macro), then tags each article with scope,
                impact link, event type, date and key numbers.
  sources.py    Tavily, Exa, FMP, FRED and yfinance fetchers (run by Python, not the AI).
  analyst.py    AI 2 (larger reasoning Groq model): news-first reasoning over the
                tagged evidence pack -> JSON report (see prompts/analyst_prompt.md).
  validator.py  Python checks: every claim cites a real evidence ID, dates are in
                the 7-day window, primary catalysts are company-specific or have a
                direct impact link.
"""
