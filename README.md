# 52-Week High Catalyst Radar

Group F1 · Gajanan · Abhinav · Archana · Adaa

Finds every NSE stock whose **day's high reached or crossed its prior 52-week high** (and the same for lows), shows them on a dashboard, and explains each move with news-first AI reasoning.

| Part | Status | Folder |
|---|---|---|
| 1. Background scanner (52-week highs & lows) | **Live** | `scanner/`, `.github/workflows/` |
| 2. Dashboard (filters, KPIs, sector breadth, deep dive) | **Built** | `app/` |
| 3. AI + news APIs (Collector AI, Analyst AI, report) | Planned | `ai/` |

---

## How the scanner works

```
Nightly job (18:30 IST)                         Intraday job (every 15 min, 09:15-15:45 IST)
- download ~400 days of daily bars (yfinance)   - download only TODAY's bar so far
- confirm today's highs/lows (end-of-day)       - compare with last night's thresholds
- build thresholds for the NEXT session         - add new hits to today's sticky list
        |                                                   |
        +----------> data branch on GitHub <----------------+
                     (latest.json, hits/DATE.csv, thresholds.csv ...)
                                   |
                         Streamlit dashboard reads it (loads in ~1 s)
```

**The rule:** stock X is a 52-week HIGH on day T if `High(T) >= max(High over the 252 sessions before T)`. It uses the intraday high, never the last traded price, so once a stock hits it stays on today's list even if the price falls back (the `still_beyond` column shows whether it is still above). Lows work the same way with `Low(T) <= min(Low ...)`.

**Data sources, with fallbacks:**

| Need | Primary | Fallback |
|---|---|---|
| Stock list (~2,000+ EQ/BE stocks) | NSE `EQUITY_L.csv` (refreshed weekly) | cached `universe.csv` |
| Sector & market-cap bucket | NSE index lists (Total Market, Nifty 100 / Midcap 150 / Smallcap 250) | "Unclassified" / "Micro" |
| History & thresholds | yfinance, split-adjusted (`auto_adjust=False`) | NSE adjusted 52-week high/low report + bhavcopy |
| End-of-day check | yfinance daily bars | NSE bhavcopy for stocks Yahoo missed |
| Intraday snapshot | yfinance (today's daily bar) | keep the last good snapshot |
| Trading calendar | a day is a trading day only if Nifty 50 (`^NSEI`) has a bar | - |

**Columns in `hits/YYYY-MM-DD.csv`:** symbol, name, sector, mcap_bucket, type (HIGH/LOW), status (intraday / confirmed / not_confirmed), first_hit_time, day OHLC, ltp, change_pct, prior 52-week high/low and its date, pct_beyond, still_beyond, volume, avg_vol_20, vol_multiple, vol_pace (volume adjusted for time of day), volume_confirmed (pace >= 1.5x), gap_pct, range_position, rs_vs_nifty_1m, short_history, source.

---

## Setup (one time, ~10 minutes)

1. **Create a GitHub repo** (public is best: Actions minutes are unlimited on public repos; private repos on the Free plan get 2,000 min/month).
2. Make sure the two workflow files are in `.github/workflows/` (if you got the project as a folder with `workflows_move_to_dot_github/`, move both `.yml` files into `.github/workflows/` and delete that folder). Then push to the `main` branch.
3. In the repo: **Settings → Actions → General → Workflow permissions → "Read and write permissions"** → Save.
4. **Bootstrap:** Actions tab → *Nightly thresholds + end-of-day check* → **Run workflow** (tick *refresh_universe*). This creates the `data` branch. It takes ~5–15 minutes.
5. From then on both workflows run on schedule. You can trigger *Intraday 52-week scan* by hand with **force** to test it.

Make one commit to `main` now and then: GitHub disables scheduled workflows in repos with no activity for a long time.

## Run locally

```bash
pip install -r requirements-dev.txt
pytest -q                          # offline tests, no network needed
python -m scanner.nightly          # builds ./data (needs internet access to Yahoo/NSE)
python -m scanner.intraday --force # one intraday snapshot
streamlit run app/streamlit_app.py
```

If NSE blocks the stock-list download, save `EQUITY_L.csv` from nseindia.com and run `python -m scanner.universe --from-file EQUITY_L.csv`.

## Dashboard

`app/streamlit_app.py` is a three-page Streamlit app:

- **Dashboard** – status line (session, market state, last update, coverage), KPI tiles (52-week highs, lows,
  volume-confirmed highs, net breadth, % of universe making highs, with change vs the previous session),
  tabs for highs / lows (sortable table, row select → *Dive deeper*, CSV download, volume-vs-distance chart),
  sector breadth, daily trend and scan details. Sidebar filters: session, sector, market cap, minimum % beyond
  the level, volume-confirmed, still holding, hide new listings, hide unconfirmed, search; settings: auto-refresh
  every 5 minutes and refresh now.
- **Deep dive** – one stock: hit metrics, one-year candles with the prior 52-week level and the hit day,
  sector context (how many peers hit too), the stock's hit history, and the AI report section (part 3).
- **How it works** – plain-language explanation of the rule, timings and columns.

On Streamlit Cloud point the app at `app/streamlit_app.py` and add the secret:

```
DATA_URL = "https://raw.githubusercontent.com/<user>/<repo>/data"
```

Sector labels: NSE's index lists label ~750 stocks; the nightly job looks up the rest on Yahoo Finance
(up to 400 per night, today's hits first), maps them to NSE's sector names and caches them in
`data/sector_cache.csv`.

## Settings

All in `config.py` (each can be overridden by an environment variable), e.g. `YF_BATCH_SIZE`, `YF_PAUSE_SEC`, `MIN_SESSIONS` (skip listings younger than this), `VOLUME_CONFIRM`, `KEEP_HIT_DAYS`.

## Known limits

- yfinance is unofficial; Yahoo may throttle GitHub's servers. The scanner batches, retries, and falls back to NSE files, and `latest.json` reports `coverage_pct` so the dashboard can warn when coverage is low.
- NSE sometimes blocks cloud servers too; every NSE call is optional and logged.
- GitHub may delay scheduled runs by several minutes at busy times.
- Yahoo's intraday NSE data can lag the exchange by a few minutes; the nightly job re-checks everything with final data and marks intraday-only hits as `not_confirmed`.
