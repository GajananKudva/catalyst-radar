"""Deep dive into one stock that hit a 52-week high or low.

Top: what happened in plain words and the key numbers. Then the AI catalyst report ("why did it move?"),
then the price chart, sector peers and the stock's 52-week hit history in tabs.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import cards
import charts
import common as c
import report_view

latest = c.get_latest()
history = c.get_history()
sessions = c.dl.available_sessions(latest, history) if latest else []

qp = st.query_params
session = qp.get("session") or st.session_state.get("deep_session") or (sessions[0] if sessions else None)
if session is None:
    st.info("No scanner output yet.")
    st.stop()

hits = c.get_hits(session)
if hits.empty:
    st.info(f"No 52-week hits for {session}.")
    st.stop()

# ---------------------------------------------------------------- pick the stock
labels = (hits.sort_values(["type", "abs_beyond"], ascending=[True, False])
          .assign(label=lambda d: d["type"].map({"HIGH": "▲", "LOW": "▼"}) + " " + d["nse_symbol"] + " · "
                  + d["name"].astype(str).str.slice(0, 40)))
keys = list(zip(labels["symbol"], labels["type"]))
wanted = qp.get("symbol") or st.session_state.get("deep_symbol")
default_idx = next((i for i, (s, _) in enumerate(keys) if s == wanted), 0)
pages = st.session_state["_pages"]

with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
    st.page_link(pages["dashboard"], label="Dashboard", icon=":material/arrow_back:")
    choice = st.selectbox("Stock", range(len(keys)), index=default_idx, width=420,
                          format_func=lambda i: labels["label"].iloc[i], label_visibility="collapsed",
                          help="All 52-week highs (▲) and lows (▼) of this session")
    prev_i, next_i = (choice - 1) % len(keys), (choice + 1) % len(keys)
    st.page_link(pages["deep_dive"], label="Previous", icon=":material/chevron_left:",
                 query_params={"symbol": keys[prev_i][0], "session": session})
    st.page_link(pages["deep_dive"], label="Next", icon=":material/chevron_right:", icon_position="right",
                 query_params={"symbol": keys[next_i][0], "session": session})

row = labels.iloc[choice]
sym, kind = row["symbol"], row["type"]
if qp.get("symbol") != sym:
    st.query_params.update({"symbol": sym, "session": session})

is_high = kind == "HIGH"
word = "high" if is_high else "low"
uni = c.get_universe()
industry = None
if not uni.empty and "industry" in uni and (uni["yahoo"] == sym).any():
    industry = uni.loc[uni["yahoo"] == sym, "industry"].iloc[0]
    industry = None if pd.isna(industry) else industry

# ---------------------------------------------------------------- header
st.title(f"{row['name']}")
badge = ":blue-badge[▲ 52-week HIGH]" if is_high else ":orange-badge[▼ 52-week LOW]"
st.markdown(f"{badge} {cards.STATUS_BADGE.get(str(row.get('status')), '')} &nbsp; **NSE: {row['nse_symbol']}** · "
            f"{row['sector']}" + (f" · {industry}" if industry else "") + f" · {row['mcap_bucket']} cap · "
            f"session {session}")

level = row["prior_52w_high"] if is_high else row["prior_52w_low"]
extreme = row["day_high"] if is_high else row["day_low"]
beyond = abs(row["pct_beyond"]) if pd.notna(row["pct_beyond"]) else None
when = f" at {row['first_hit']} IST" if isinstance(row.get("first_hit"), str) else ""
set_on = f" (set on {row['prior_extreme_date']})" if pd.notna(row.get("prior_extreme_date")) else ""
hold = ("and is still holding above it" if is_high else "and is still below it") if row["still_beyond"] \
    else "but has since moved back inside the old range"
summary = (f"The stock {'rose' if is_high else 'fell'} to **{c.fmt_inr(extreme)}**{when}, "
           f"{'**' + format(beyond, '.1f') + '%** ' if beyond is not None else ''}"
           f"{'above' if is_high else 'below'} its previous 52-week {word} of {c.fmt_inr(level)}{set_on}, {hold}.")
st.markdown(summary)

with st.container(horizontal=True, gap="small"):
    st.metric("Last price", c.fmt_inr(row["ltp"]), c.fmt_pct(row["change_pct"]), border=True, width=168,
              help="Change vs the previous close")
    st.metric(f"Past the 52W {word}", c.fmt_pct(row["pct_beyond"]), border=True, width=168,
              help=f"Day's {word} vs the prior 52-week {word}")
    st.metric("Volume vs avg", f"{row['vol_multiple']:.1f}×" if pd.notna(row["vol_multiple"]) else "–",
              "confirmed" if row["volume_confirmed"] else "not confirmed", delta_color="off", delta_arrow="off",
              border=True, width=168, help="Volume vs the 20-day average; 1.5× or more counts as volume-confirmed")
    st.metric("Gap at open", c.fmt_pct(row["gap_pct"]), border=True, width=168, help="Open vs previous close")
    st.metric("1-month vs Nifty", c.fmt_pct(row["rs_vs_nifty_1m"]), border=True, width=168,
              help="The stock's 1-month return minus the Nifty 50's")

# ---------------------------------------------------------------- AI report (the main question)
with st.container(border=True):
    key = (sym, session, kind)
    cached = report_view.get_cached(key)
    head_l, head_r = st.columns([3, 1], vertical_alignment="center")
    with head_l:
        st.subheader(":material/auto_awesome: Why did it move?")
        st.caption("Collector AI maps the company's stakeholders and gathers dated news on the company, promoters, "
                   "customers, peers, industry and government (Tavily, Exa, NewsAPI, Yahoo). Analyst AI explains "
                   "the trigger and how surprising it was, citing every source. Takes about 30–90 seconds.")
    with head_r:
        clicked = st.button("Regenerate" if cached else "Generate AI report", type="secondary" if cached else "primary",
                            icon=":material/refresh:" if cached else ":material/auto_awesome:", width="stretch")

    if clicked:
        from ai import pipeline, settings as ai_settings

        missing = ai_settings.missing_keys()
        if missing:
            st.error(f"Missing secret(s): {', '.join(missing)}. Add them in Streamlit → Settings → Secrets.")
        else:
            with st.status("Building the AI catalyst report...", expanded=True) as box:
                def progress(step: str, msg: str) -> None:
                    box.write(msg)
                    box.update(label=msg)
                try:
                    result = pipeline.run(row.to_dict(), hits, uni, progress=progress)
                    report_view.put_cached(key, result)
                    cached = result
                    box.update(label="Report ready", state="complete", expanded=False)
                except Exception as exc:
                    box.update(label="The AI report failed", state="error", expanded=True)
                    st.error(f"{type(exc).__name__}: {exc}")

    if cached:
        report_view.render(cached)
    elif not clicked:
        st.caption(":material/info: No report yet for this stock and session. Reports are kept for 6 hours and "
                   "shared by everyone using the app.")


# ---------------------------------------------------------------- chart, peers, history
@st.cache_data(ttl=3600, show_spinner="Loading price history...")
def price_history(ticker: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        df = yf.download(ticker, period="1y", interval="1d", auto_adjust=False, progress=False,
                         multi_level_index=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


same = hits[(hits["sector"] == row["sector"]) & (hits["type"] == kind) & (hits["status"] != "not_confirmed")]
peers = same[same["symbol"] != sym].sort_values("abs_beyond", ascending=False)
past = history[(history["symbol"] == sym)] if not history.empty else pd.DataFrame()

t_chart, t_peers, t_hist = st.tabs([":material/candlestick_chart: Price chart",
                                    f":material/groups: Sector peers ({len(peers)})",
                                    f":material/history: 52-week hit history ({len(past)})"])
with t_chart:
    px = price_history(sym)
    if px.empty:
        st.info("Price history could not be loaded from Yahoo Finance right now. Try again in a few minutes.",
                icon=":material/cloud_off:")
    else:
        st.plotly_chart(charts.price_fig(px, level, kind, session), key="price")
        st.caption(f"Dashed line: the prior 52-week {word} the stock crossed. Triangle: the hit day.")

with t_peers:
    n_sector = int((uni["sector"] == row["sector"]).sum()) if not uni.empty else 0
    if row["sector"] == "Unclassified":
        st.caption("This stock has no sector label yet, so sector breadth isn't available.")
    else:
        st.markdown(f"**{len(same)}** of **{n_sector or '?'}** {row['sector']} stocks hit a 52-week {word} "
                    "in this session.")
        if len(same) >= 3:
            st.info("Several stocks in the same sector moved together: look for industry or government news "
                    "before assuming a company-specific trigger.", icon=":material/lightbulb:")
        if peers.empty:
            st.caption("No other stock in this sector made a 52-week " + word + " in this session.")
        else:
            ready = {k for k in report_view.cached_keys() if k[1] == session}
            with st.container(horizontal=True, wrap=True, gap="small"):
                for i, (_, p) in enumerate(peers.head(9).iterrows()):
                    cards.stock_card(p, session, key=f"peer_{i}_{p['symbol']}",
                                     ai_ready=(p["symbol"], session, p["type"]) in ready)
            if len(peers) > 9:
                st.caption(f"Showing the 9 biggest moves of {len(peers)} peers.")

with t_hist:
    if past.empty:
        st.caption("No earlier confirmed 52-week hits in the stored history.")
    else:
        st.dataframe(past.sort_values("session_date", ascending=False)[["session_date", "type", "pct_beyond",
                                                                        "change_pct", "vol_multiple"]],
                     hide_index=True, column_config={
                         "session_date": "Session", "type": "Type",
                         "pct_beyond": st.column_config.NumberColumn("Beyond 52W %", format="%+.2f%%"),
                         "change_pct": st.column_config.NumberColumn("Day change %", format="%+.2f%%"),
                         "vol_multiple": st.column_config.NumberColumn("Volume ×", format="%.1f×")})
        st.caption("A stock that keeps making new 52-week " + word + "s is in a persistent trend.")
