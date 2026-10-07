"""How the radar works (for users and evaluators)."""
import streamlit as st

st.title("How it works")
st.markdown("""
**52-Week High Catalyst Radar** scans every NSE stock (series EQ and BE, about 2,500 companies) and lists the
ones whose **day's high reached or crossed the highest price of the previous 252 trading days** — and the
mirror case for 52-week lows. It uses the day's high or low, never just the last price, so a stock that
touches its high at 11:00 stays on the list even if it falls back later.

#### When the data updates
| Job | Time (IST) | What it does |
|---|---|---|
| Intraday scan | every 15 min, 09:15–15:45 | today's high/low so far vs last night's 52-week levels |
| Nightly job | about 18:30 | confirms the day's list with final data and prepares tomorrow's levels |

GitHub may delay a scheduled run by a few minutes at busy times; the status line shows when the data was last updated.

#### Columns
- **Beyond 52W %** – how far the day's high went past the prior 52-week high (or the low below the prior low)
- **Vol ×** – today's volume vs the 20-day average; **Vol pace** adjusts for the time of day
- **Gap %** – opening price vs the previous close
- **Close in range** – where the last price sits in the day's range (100% = at the high)
- **vs Nifty 1M** – the stock's 1-month return minus Nifty 50's
- **Holding** – whether the last price is still beyond the old level
- **Status** – *intraday* (from the 15-minute scan), *confirmed* (checked with final data), *not confirmed*

#### AI catalyst report (Deep dive -> Generate AI report)
1. **Collector AI** (fast Groq model) maps the company's stakeholders (aliases, promoter group, key people,
   products, raw materials, customers, peers, regulators) and writes 9-12 targeted searches.
2. Python runs them on **Tavily, Exa, NewsAPI, Finnhub and Yahoo Finance**, keeps articles from 10 days before
   to 1 day after the session, and removes duplicates.
3. The Collector AI tags every article: scope (company, stakeholder, peer, industry, government, macro), impact
   link (direct / indirect / none), event type, the key fact and a relevance score. Python re-checks that
   "company" news really names the company and keeps the best 12 items as the **evidence pack**.
4. **Analyst AI** (reasoning Groq model) explains the move news-first: the trigger, how surprising it was,
   whether the news came before the price move, context, fundamentals as the base, rumours and what to watch,
   citing every claim with an evidence ID. Earnings vs estimates and analyst grades (FMP), the Yahoo calendar,
   macro data (FRED) and today's sector breadth are added as context.
5. Python validates the answer (real evidence IDs, dates inside the window, only company or directly-linked
   news as the trigger) and asks the Analyst to fix it once if needed.

#### Sources
NSE equity list and index lists (sector and market-cap bucket), Yahoo Finance daily prices (split-adjusted),
NSE's corporate-action-adjusted 52-week report and bhavcopy as fallbacks. Sector labels for smaller companies
come from Yahoo Finance, mapped to NSE's sector names.

*Decision support only. Nothing here is investment advice.*

Group F1 · Gajanan · Abhinav · Archana · Adaa
""")
