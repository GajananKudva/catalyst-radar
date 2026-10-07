"""Dashboard: today's 52-week highs and lows with filters, KPIs, sector breadth and trend."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import common as c
from scanner.logic import sector_breadth

latest = c.get_latest()
st.title("52-Week High Catalyst Radar")

if not latest:
    st.info("No scanner output yet. Run the **Nightly thresholds + end-of-day check** workflow once on GitHub "
            "(or `python -m scanner.nightly` locally), then refresh.", icon=":material/hourglass_empty:")
    st.stop()

history = c.get_history()
sessions = c.dl.available_sessions(latest, history) or [latest.get("session_date")]

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Filters")
    session = st.selectbox("Session", sessions, index=0,
                           help="Today's list updates every 15 minutes during market hours. "
                                "Past sessions show the end-of-day confirmed list.")
    hits = c.get_hits(session)
    sector_opts = hits["sector"].value_counts().index.tolist() if not hits.empty else []
    f = c.Filters(
        sectors=st.multiselect("Sector", sector_opts, placeholder="All sectors"),
        mcaps=st.multiselect("Market cap", c.MCAP_ORDER, placeholder="All sizes",
                             help="Large = Nifty 100, Mid = Midcap 150, Small = Smallcap 250, Micro = the rest"),
        min_beyond=st.slider("Min. % beyond the 52-week level", 0.0, 10.0, 0.0, 0.25,
                             help="How far the day's high (low) went past the prior 52-week high (low)."),
        volume_confirmed=st.toggle("Volume-confirmed only", help="Volume pace at least 1.5× the 20-day average"),
        still_beyond=st.toggle("Still holding the level", help="Last price is still above the old high (below the old low)"),
        hide_short_history=st.toggle("Hide stocks listed < 1 year"),
        hide_unconfirmed=st.toggle("Hide intraday hits not confirmed at close", value=True),
        search=st.text_input("Search symbol or company", placeholder="e.g. HFCL"),
    )
    st.divider()
    st.subheader("Settings")
    auto = st.toggle("Auto-refresh every 5 minutes", value=latest.get("market_state") in ("open", "closing"))
    if st.button("Refresh now", icon=":material/refresh:", width="stretch"):
        c.refresh_all()
        st.rerun()
    st.caption("Data: NSE stock list, Yahoo Finance prices, NSE 52-week report. Scanner runs on GitHub Actions.")


def go_deep(symbol: str) -> None:
    st.session_state["deep_symbol"] = symbol
    st.session_state["deep_session"] = session
    st.switch_page(st.session_state["_pages"]["deep_dive"], query_params={"symbol": symbol, "session": session})


COLUMN_CONFIG = {
    "nse_symbol": st.column_config.TextColumn("Stock", pinned=True),
    "name": st.column_config.TextColumn("Company", width="medium"),
    "sector": st.column_config.TextColumn("Sector", width="medium"),
    "mcap_bucket": st.column_config.TextColumn("Cap", width="small"),
    "pct_beyond": st.column_config.NumberColumn("Beyond 52W %", format="%+.2f%%",
                                                help="Day's high (low) vs the prior 52-week high (low)"),
    "day_high": st.column_config.NumberColumn("Day high ₹", format="%.2f"),
    "day_low": st.column_config.NumberColumn("Day low ₹", format="%.2f"),
    "prior_52w_high": st.column_config.NumberColumn("Prior 52W high ₹", format="%.2f"),
    "prior_52w_low": st.column_config.NumberColumn("Prior 52W low ₹", format="%.2f"),
    "ltp": st.column_config.NumberColumn("Last ₹", format="%.2f"),
    "change_pct": st.column_config.NumberColumn("Chg %", format="%+.2f%%"),
    "vol_multiple": st.column_config.NumberColumn("Vol ×", format="%.1f×", help="Volume vs 20-day average"),
    "vol_pace": st.column_config.NumberColumn("Vol pace ×", format="%.1f×",
                                              help="Volume vs 20-day average, adjusted for time of day"),
    "gap_pct": st.column_config.NumberColumn("Gap %", format="%+.2f%%", help="Open vs previous close"),
    "range_position": st.column_config.ProgressColumn("Close in range", min_value=0.0, max_value=1.0,
                                                      format="percent",
                                                      help="Where the last price sits in the day's range (100% = at the high)"),
    "rs_vs_nifty_1m": st.column_config.NumberColumn("vs Nifty 1M", format="%+.1f%%",
                                                    help="1-month return minus Nifty 50's"),
    "first_hit": st.column_config.TextColumn("First hit", help="Time (IST) the stock first crossed the level today"),
    "still_beyond": st.column_config.CheckboxColumn("Holding", help="Still beyond the old level at the last price"),
    "status": st.column_config.TextColumn("Status", width="small"),
}
HIGH_COLS = ["nse_symbol", "name", "sector", "mcap_bucket", "pct_beyond", "day_high", "prior_52w_high", "ltp",
             "change_pct", "vol_multiple", "vol_pace", "gap_pct", "range_position", "rs_vs_nifty_1m",
             "first_hit", "still_beyond", "status"]
LOW_COLS = [x.replace("day_high", "day_low").replace("prior_52w_high", "prior_52w_low") for x in HIGH_COLS]


def hits_table(df: pd.DataFrame, kind: str) -> None:
    if df.empty:
        st.info("No stocks match the current filters.", icon=":material/filter_alt_off:")
        return
    d = df.sort_values("abs_beyond", ascending=False)
    cols = [x for x in (HIGH_COLS if kind == "HIGH" else LOW_COLS) if x in d.columns]
    event = st.dataframe(d[cols], column_config=COLUMN_CONFIG, hide_index=True, on_select="rerun",
                         selection_mode="single-row", key=f"table_{kind}", height=min(38 * len(d) + 40, 560))
    rows = event.selection.rows if event and event.selection else []
    left, right = st.columns([3, 2], vertical_alignment="center")
    with left:
        if rows:
            sel = d.iloc[rows[0]]
            if st.button(f"Dive deeper into {sel['nse_symbol']}", type="primary", icon=":material/troubleshoot:",
                         key=f"dive_{kind}"):
                go_deep(sel["symbol"])
        else:
            st.caption("Select a row to dive deeper into that stock.")
    with right:
        st.download_button("Download CSV", d[cols].to_csv(index=False).encode(), icon=":material/download:",
                           file_name=f"52w_{kind.lower()}s_{session}.csv", mime="text/csv",
                           key=f"dl_{kind}", width="stretch")
    with st.expander("Volume vs distance chart"):
        st.plotly_chart(charts.volume_scatter_fig(d, kind), key=f"scatter_{kind}")


def render() -> None:
    lt = c.get_latest()
    if session == lt.get("session_date"):
        c.status_line(lt)
    else:
        st.caption(f"Session **{session}** · end-of-day confirmed list")

    data = c.get_hits(session)
    view = c.apply_filters(data, f) if not data.empty else data
    highs = view[view["type"] == "HIGH"] if not view.empty else view
    lows = view[view["type"] == "LOW"] if not view.empty else view

    # KPIs, with the change vs the previous session where history allows
    counts = c.session_counts(history)
    prev = counts[counts["session_date"] < session].tail(1)
    p_hi = int(prev["HIGH"].iloc[0]) if not prev.empty else None
    p_lo = int(prev["LOW"].iloc[0]) if not prev.empty else None
    universe_n = lt.get("universe_size") or 0
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("▲ 52W highs", len(highs), None if p_hi is None else len(highs) - p_hi, border=True,
              help="Stocks whose day's high reached or crossed the prior 52-week high")
    k2.metric("▼ 52W lows", len(lows), None if p_lo is None else len(lows) - p_lo, delta_color="inverse",
              border=True, help="Stocks whose day's low reached or fell below the prior 52-week low")
    k3.metric("Vol-confirmed highs", int(highs["volume_confirmed"].sum()) if len(highs) else 0, border=True,
              help="Highs with volume pace at least 1.5× the 20-day average")
    k4.metric("Net breadth", f"{len(highs) - len(lows):+d}", border=True, help="Highs minus lows")
    k5.metric("% making highs", f"{(100 * len(highs) / universe_n):.1f}%" if universe_n else "–",
              border=True, help=f"Share of the {universe_n:,} scanned stocks")

    t_hi, t_lo, t_sec, t_trend, t_info = st.tabs(
        [f"▲ 52W highs ({len(highs)})", f"▼ 52W lows ({len(lows)})", "Sector breadth", "Trend", "Scan details"])
    with t_hi:
        hits_table(highs, "HIGH")
    with t_lo:
        hits_table(lows, "LOW")
    with t_sec:
        uni = c.get_universe()
        incl = st.toggle("Include 'Unclassified'", value=False, key="incl_uncl",
                         help="Stocks without a sector label yet (labels are filled in a few hundred per night)")
        br = sector_breadth(view if not view.empty else data, uni if not uni.empty else None)
        if not incl:
            br = br[br["sector"] != "Unclassified"]
        if br.empty or (br["highs"] + br["lows"]).sum() == 0:
            st.info("No sector data for the current selection.")
        else:
            st.plotly_chart(charts.sector_breadth_fig(br), key="sector_fig")
            st.caption("Many stocks in one sector making highs together usually points to industry or government "
                       "news rather than a company-specific event.")
            st.dataframe(br.rename(columns={"sector": "Sector", "stocks": "Stocks", "highs": "52W highs",
                                            "lows": "52W lows", "pct_high": "% making highs",
                                            "pct_low": "% making lows"}), hide_index=True)
    with t_trend:
        if len(counts) < 2:
            st.info(f"The trend chart needs at least two sessions of history; {len(counts)} so far. "
                    "It fills in automatically each evening.", icon=":material/insights:")
        if len(counts):
            st.plotly_chart(charts.trend_fig(counts), key="trend_fig")
            st.dataframe(counts.rename(columns={"session_date": "Session", "HIGH": "52W highs", "LOW": "52W lows"}),
                         hide_index=True)
    with t_info:
        meta = c.get_meta()
        a, b = st.columns(2)
        with a:
            st.markdown(f"""
- **Last update:** {lt.get('generated_at', '-')} ({lt.get('job', '-')} job)
- **Market state:** {c.MARKET_LABEL.get(lt.get('market_state', ''), lt.get('market_state', '-'))}
- **Thresholds as of:** {lt.get('thresholds_as_of', '-')}
- **Coverage:** {lt.get('scanned_ok', 0):,} / {lt.get('universe_size', 0):,} stocks ({lt.get('coverage_pct', 0)}%)
- **Note:** {lt.get('note', '')}
""")
        with b:
            src = meta.get("sources", {})
            st.markdown("**Where each stock's 52-week level came from**")
            st.markdown("\n".join(f"- {k}: {v:,}" for k, v in src.items()) or "-")
            st.caption("yfinance = computed from 1 year of daily prices; nse_report = NSE's adjusted "
                       "52-week report (used for newer listings or missing Yahoo data).")


if auto:
    st.fragment(run_every="5m")(render)()
else:
    render()
