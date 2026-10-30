"""Dashboard: today's 52-week highs and lows as stock cards, with quick filters and a market overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import cards
import charts
import common as c
import report_view
from scanner.logic import sector_breadth

latest = c.get_latest()

if not latest:
    st.title("52-Week High Catalyst Radar")
    st.info("No scanner output yet. Run the **Nightly thresholds + end-of-day check** workflow once on GitHub "
            "(or `python -m scanner.nightly` locally), then refresh.", icon=":material/hourglass_empty:")
    st.stop()

history = c.get_history()
sessions = c.dl.available_sessions(latest, history) or [latest.get("session_date")]

# ------------------------------------------------------------------ sidebar: session + settings only
with st.sidebar:
    session = st.selectbox("Session", sessions, index=0,
                           help="Today's list updates every 15 minutes during market hours. "
                                "Past sessions show the end-of-day confirmed list.")
    auto = st.toggle("Auto-refresh every 5 minutes", value=latest.get("market_state") in ("open", "closing"))
    if st.button("Refresh now", icon=":material/refresh:", width="stretch"):
        c.refresh_all()
        st.rerun()
    st.caption("Data: NSE stock list, Yahoo Finance prices, NSE 52-week report. "
               "The scanner runs on GitHub Actions every 15 minutes in market hours.")

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
    "gap_pct": st.column_config.NumberColumn("Gap %", format="%+.2f%%", help="Open vs previous close"),
    "rs_vs_nifty_1m": st.column_config.NumberColumn("vs Nifty 1M", format="%+.1f%%",
                                                    help="1-month return minus Nifty 50's"),
    "first_hit": st.column_config.TextColumn("First hit", help="Time (IST) the stock first crossed the level"),
    "still_beyond": st.column_config.CheckboxColumn("Holding", help="Still beyond the old level at the last price"),
    "status": st.column_config.TextColumn("Status", width="small"),
}
HIGH_COLS = ["nse_symbol", "name", "sector", "mcap_bucket", "pct_beyond", "day_high", "prior_52w_high", "ltp",
             "change_pct", "vol_multiple", "gap_pct", "rs_vs_nifty_1m", "first_hit", "still_beyond", "status"]
LOW_COLS = [x.replace("day_high", "day_low").replace("prior_52w_high", "prior_52w_low") for x in HIGH_COLS]
QUICK = {"vol": "Volume-confirmed", "hold": "Still beyond the level", "seasoned": "Listed > 1 year"}


def hits_table(df: pd.DataFrame, kind: str) -> None:
    cols = [x for x in (HIGH_COLS if kind == "HIGH" else LOW_COLS) if x in df.columns]
    event = st.dataframe(df[cols], column_config=COLUMN_CONFIG, hide_index=True, on_select="rerun",
                         selection_mode="single-row", key=f"table_{kind}", height=min(38 * len(df) + 40, 560))
    rows = event.selection.rows if event and event.selection else []
    if rows:
        sel = df.iloc[rows[0]]
        st.page_link(st.session_state["_pages"]["deep_dive"], label=f"Open {sel['nse_symbol']}",
                     icon=":material/arrow_forward:", query_params={"symbol": sel["symbol"], "session": session})
    else:
        st.caption("Select a row to open that stock.")


def render() -> None:
    lt = c.get_latest()
    st.title("52-Week High Catalyst Radar")
    st.caption("Every NSE stock at a new 52-week high or low, and an AI explanation of why it moved.")
    if session == lt.get("session_date"):
        c.market_banner(lt)
    else:
        st.markdown(f":blue-badge[:material/history: Past session] &nbsp; Session **{session}** · "
                    "end-of-day confirmed list")

    data = c.get_hits(session)
    if data.empty:
        st.info(f"No 52-week hits stored for {session}.", icon=":material/search_off:")
        return

    # --------------------------------------------------------------- controls
    side = st.segmented_control("Show", ["HIGH", "LOW"], default="HIGH", required=True, key="side",
                                format_func=lambda k: "▲ 52-week highs" if k == "HIGH" else "▼ 52-week lows",
                                label_visibility="collapsed")
    ctl = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
    with ctl:
        search = st.text_input("Search", placeholder="Search symbol or company", label_visibility="collapsed",
                               icon=":material/search:", width=260, key="search")
        quick = st.pills("Quick filters", list(QUICK), selection_mode="multi", format_func=QUICK.get,
                         label_visibility="collapsed", key="quick", wrap=True)
        with st.popover("More filters", icon=":material/tune:"):
            sector_opts = data["sector"].value_counts().index.tolist()
            sectors = st.multiselect("Sector", sector_opts, placeholder="All sectors", key="f_sector")
            mcaps = st.multiselect("Market cap", c.MCAP_ORDER, placeholder="All sizes", key="f_mcap",
                                   help="Large = Nifty 100, Mid = Midcap 150, Small = Smallcap 250, Micro = the rest")
            min_beyond = st.slider("Min. % beyond the 52-week level", 0.0, 10.0, 0.0, 0.25, key="f_beyond")
            hide_unconf = st.toggle("Hide intraday hits not confirmed at close", value=True, key="f_unconf")
    f = c.Filters(sectors=sectors, mcaps=mcaps, min_beyond=min_beyond, volume_confirmed="vol" in quick,
                  still_beyond="hold" in quick, hide_short_history="seasoned" in quick,
                  hide_unconfirmed=hide_unconf, search=search or "")
    view = c.apply_filters(data, f)
    highs, lows = view[view["type"] == "HIGH"], view[view["type"] == "LOW"]

    # --------------------------------------------------------------- KPIs (wrap to 2 per row on phones)
    counts = c.session_counts(history)
    prev = counts[counts["session_date"] < session].tail(1)
    p_hi = int(prev["HIGH"].iloc[0]) if not prev.empty else None
    p_lo = int(prev["LOW"].iloc[0]) if not prev.empty else None
    net = len(highs) - len(lows)
    with st.container(horizontal=True, gap="small"):
        st.metric("▲ 52W highs", len(highs), None if p_hi is None else len(highs) - p_hi, border=True,
                  width=165, help="Stocks whose day's high reached or crossed the prior 52-week high. "
                                  "Change vs the previous session.")
        st.metric("▼ 52W lows", len(lows), None if p_lo is None else len(lows) - p_lo, delta_color="inverse",
                  border=True, width=165, help="Stocks whose day's low reached or fell below the prior 52-week low")
        st.metric("Net breadth", f"{net:+d}", "more highs" if net > 0 else ("more lows" if net < 0 else "even"),
                  delta_color="normal" if net >= 0 else "inverse", delta_arrow="off", border=True, width=165,
                  help="Highs minus lows: a quick read of whether the whole market is strong or weak")
        st.metric("Vol-confirmed", int(highs["volume_confirmed"].sum()) if len(highs) else 0,
                  border=True, width=165, help="52-week highs with volume at least 1.5× the 20-day average")

    # --------------------------------------------------------------- cards / table
    picked = highs if side == "HIGH" else lows
    word = "highs" if side == "HIGH" else "lows"
    bar = st.container(horizontal=True, vertical_alignment="center", gap="small")
    with bar:
        sort = st.selectbox("Sort by", list(cards.SORTS), key="sort", width=230, label_visibility="collapsed")
        layout = st.segmented_control("Layout", ["Cards", "Table"], default="Cards", required=True, key="layout",
                                      format_func=lambda v: {"Cards": ":material/grid_view: Cards",
                                                             "Table": ":material/table_rows: Table"}[v],
                                      label_visibility="collapsed")
        st.space("stretch")
        if not picked.empty:
            st.download_button("CSV", picked.to_csv(index=False).encode(), icon=":material/download:",
                               file_name=f"52w_{word}_{session}.csv", mime="text/csv", key="dl")
    st.caption(f"{len(picked)} {word} match your filters"
               + (f" (of {int((data['type'] == side).sum())} in total)" if len(picked) != (data['type'] == side).sum()
                  else ""))
    if picked.empty:
        st.info("No stocks match the current filters. Clear a filter above to see more.",
                icon=":material/filter_alt_off:")
    else:
        ordered = cards.sort_hits(picked, sort)
        if layout == "Table":
            hits_table(ordered, side)
        else:
            ready = {k for k in report_view.cached_keys() if k[1] == session}
            cards.card_grid(ordered, session, side, ready)

    # --------------------------------------------------------------- market overview
    st.divider()
    st.subheader("Market overview")
    t_sec, t_trend, t_scatter, t_info = st.tabs(
        [":material/bar_chart: Sector breadth", ":material/show_chart: Trend", ":material/scatter_plot: Volume vs move",
         ":material/info: Scan details"])
    with t_sec:
        uni = c.get_universe()
        incl = st.toggle("Include 'Unclassified'", value=False, key="incl_uncl",
                         help="Stocks without a sector label yet (labels are filled in a few hundred per night)")
        br = sector_breadth(view, uni if not uni.empty else None)
        if not incl:
            br = br[br["sector"] != "Unclassified"]
        if br.empty or (br["highs"] + br["lows"]).sum() == 0:
            st.info("No sector data for the current selection.")
        else:
            st.plotly_chart(charts.sector_breadth_fig(br), key="sector_fig")
            st.caption("Many stocks in one sector making highs together usually points to industry or government "
                       "news rather than a company-specific event.")
    with t_trend:
        if len(counts) < 2:
            st.info(f"The trend chart needs at least two sessions of history; {len(counts)} so far.",
                    icon=":material/insights:")
        else:
            st.plotly_chart(charts.trend_fig(counts), key="trend_fig")
            st.caption("Confirmed 52-week highs and lows per session. When lows far outnumber highs, the weakness "
                       "is market-wide: check the market and sector before reading company news.")
    with t_scatter:
        if picked.empty:
            st.info("Nothing to plot for the current filters.")
        else:
            st.plotly_chart(charts.volume_scatter_fig(picked, side), key="scatter")
            st.caption("Top-right = breakouts that went furthest on the heaviest volume: usually the strongest signals.")
    with t_info:
        meta = c.get_meta()
        a, b = st.columns(2)
        with a:
            st.markdown(f"""
- **Last update:** {lt.get('generated_at', '-')} ({lt.get('job', '-')} job)
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
