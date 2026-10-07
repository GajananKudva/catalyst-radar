"""PART 3 - AI catalyst report.

  settings.py   API keys (Streamlit secrets / env) and limits
  llm.py        Groq wrapper returning parsed JSON
  sources.py    Tavily, Exa, NewsAPI, Finnhub, Yahoo (yfinance), FMP, FRED fetchers + diagnostics
  collector.py  AI 1 (fast model): stakeholder map + search plan, then tags each article
                (scope, impact link, event, fact, relevance); Python filters and picks the evidence pack
  analyst.py    AI 2 (reasoning model): news-first explanation citing evidence IDs
  validator.py  Python checks on the Analyst's JSON (one automatic retry)
  pipeline.py   runs everything for one stock and returns report + evidence + diagnostics
"""
