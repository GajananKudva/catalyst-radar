"""Deep dive into one stock that hit a 52-week high or low.

Part 2: price action, the 52-week level, sector context and the stock's hit history.
Part 3 adds the AI catalyst report (Collector AI + Analyst AI over Tavily, Exa, FMP, FRED).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import charts
import common as c

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

# pick the stock: from the dashboard link, or let the user choose
labels = (hits.sort_values(["type", "abs_beyond"], ascending=[True, False])
          .assign(label=lambda d: d["nse_symbol"] + " · " + d["name"].astype(str).str.slice(0, 40)
                  + " (" + d["type"].map({"HIGH": "▲ high", "LOW": "▼ low"}) + ")"))
keys = list(zip(labels["symbol"], labels["type"]))
wanted = qp.get("symbol") or st.session_state.get("deep_symbol")
default_idx = next((i for i, (s, _) in enumerate(keys) if s == wanted), 0)

top_l, top_r = st.columns([4, 1], vertical_alignment="bottom")
with top_l:
    choice = st.selectbox("Stock", range(len(keys)), index=default_idx,
                          format_func=lambda i: labels["label"].iloc[i], label_visibility="collapsed")
with top_r:
    if st.button("Back to dashboard", icon=":material/arrow_back:", width="stretch"):
        st.switch_page(st.session_state["_pages"]["dashboard"])

row = labels.iloc[choice]
sym, kind = row["symbol"], row["type"]
if qp.get("symbol") != sym:
    st.query_params.update({"symbol": sym, "session": session})

is_high = kind == "HIGH"
uni = c.get_universe()
industry = None
if not uni.empty and "industry" in uni and (uni["yahoo"] == sym).any():
    industry = uni.loc[uni["yahoo"] == sym, "industry"].iloc[0]
    industry = None if pd.isna(industry) else industry

st.title(f"{row['name']}")
badge = ":blue-badge[▲ 52-week HIGH]" if is_high else ":orange-badge[▼ 52-week LOW]"
status = {"confirmed": ":green-badge[Confirmed at close]", "intraday": ":gray-badge[Intraday]",
          "not_confirmed": ":red-badge[Not confirmed at close]"}.get(str(row.get("status")), "")
st.markdown(f"{badge} {status} &nbsp; **NSE: {row['nse_symbol']}** · {row['sector']}"
            + (f" · {industry}" if industry else "") + f" · {row['mcap_bucket']} cap · session {session}")

level = row["prior_52w_high"] if is_high else row["prior_52w_low"]
extreme = row["day_high"] if is_high else row["day_low"]
m = st.columns(3) + st.columns(3)
m[0].metric("Day high" if is_high else "Day low", c.fmt_inr(extreme), c.fmt_pct(row["pct_beyond"]),
            delta_color="normal" if is_high else "inverse", border=True,
            help=f"vs prior 52-week {'high' if is_high else 'low'} of {c.fmt_inr(level)}"
                 f" set on {row.get('prior_extreme_date', '-')}")
m[1].metric("Last price", c.fmt_inr(row["ltp"]), c.fmt_pct(row["change_pct"]), border=True)
m[2].metric("Volume vs 20D avg", f"{row['vol_multiple']:.1f}×" if pd.notna(row["vol_multiple"]) else "–",
            f"pace {row['vol_pace']:.1f}×" if pd.notna(row["vol_pace"]) else None, delta_color="off", border=True)
m[3].metric("Gap at open", c.fmt_pct(row["gap_pct"]), border=True)
m[4].metric("vs Nifty, 1 month", c.fmt_pct(row["rs_vs_nifty_1m"]), border=True)
m[5].metric("First hit (IST)", row["first_hit"] if isinstance(row["first_hit"], str) else "–",
            "holding" if row["still_beyond"] else "fell back", delta_color="off", border=True)


# --------------------------------------------------------------- price chart
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


left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Price action")
    px = price_history(sym)
    if px.empty:
        st.info("Price history could not be loaded from Yahoo Finance right now. Try again in a few minutes.",
                icon=":material/cloud_off:")
    else:
        st.plotly_chart(charts.price_fig(px, level, kind, session), key="price")
        st.caption("Dashed line: the prior 52-week level the stock crossed. Triangle: the hit day.")

with right:
    st.subheader("Sector context")
    same = hits[(hits["sector"] == row["sector"]) & (hits["type"] == kind) & (hits["status"] != "not_confirmed")]
    n_sector = int((uni["sector"] == row["sector"]).sum()) if not uni.empty else 0
    if row["sector"] == "Unclassified":
        st.caption("This stock has no sector label yet, so sector breadth isn't available.")
    else:
        st.markdown(f"**{len(same)}** of **{n_sector or '?'}** {row['sector']} stocks hit a 52-week "
                    f"{'high' if is_high else 'low'} in this session.")
        if len(same) >= 3:
            st.info("Several stocks in the same sector moved together: look for industry or government news "
                    "before assuming a company-specific trigger.", icon=":material/lightbulb:")
        peers = same[same["symbol"] != sym].sort_values("abs_beyond", ascending=False)
        if not peers.empty:
            st.dataframe(peers[["nse_symbol", "name", "pct_beyond", "vol_multiple"]], hide_index=True,
                         column_config={"nse_symbol": "Stock", "name": "Company",
                                        "pct_beyond": st.column_config.NumberColumn("Beyond %", format="%+.2f%%"),
                                        "vol_multiple": st.column_config.NumberColumn("Vol ×", format="%.1f×")},
                         height=min(36 * len(peers) + 40, 300))

    st.subheader("52-week hits history")
    past = history[(history["symbol"] == sym)] if not history.empty else pd.DataFrame()
    if past.empty:
        st.caption("No earlier confirmed 52-week hits in the stored history.")
    else:
        st.dataframe(past.sort_values("session_date", ascending=False)[["session_date", "type", "pct_beyond"]],
                     hide_index=True, column_config={
                         "session_date": "Session", "type": "Type",
                         "pct_beyond": st.column_config.NumberColumn("Beyond %", format="%+.2f%%")})

# ---------------------------------------------------------------- AI report
st.divider()
st.subheader("Why did it move? AI catalyst report")
st.caption("Collector AI maps the company's stakeholders and gathers dated news on the company, its promoters, "
           "customers, peers, industry and government announcements (Tavily, Exa, NewsAPI, Finnhub, Yahoo). "
           "Analyst AI then explains the trigger, how surprising it was, and cites every source.")

import report_view  # noqa: E402

key = (sym, session, kind)
cached = report_view.get_cached(key)
c1, c2 = st.columns([1, 3], vertical_alignment="center")
with c1:
    clicked = st.button("Regenerate AI report" if cached else "Generate AI report", type="primary",
                        icon=":material/auto_awesome:", width="stretch")
with c2:
    st.caption("Takes about 30–90 seconds. Reports are kept for 6 hours and shared by all users, "
               "to stay within the free API limits.")

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
