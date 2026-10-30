"""Stock cards: one bordered tile per 52-week hit (used on the dashboard and for sector peers)."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

import common as c

CARD_WIDTH = 296          # px; three per row on a laptop, one per row on phones
PAGE_SIZE = 12

SORTS = {
    "Biggest breakout": ("abs_beyond", False),
    "Highest volume": ("vol_multiple", False),
    "Biggest day move": ("abs_change", False),
    "Strongest vs Nifty (1M)": ("rs_vs_nifty_1m", False),
    "Earliest hit today": ("first_hit", True),
    "Company A–Z": ("name", True),
}

STATUS_BADGE = {"confirmed": ":green-badge[Confirmed at close]", "intraday": ":gray-badge[Intraday]",
                "not_confirmed": ":red-badge[Not confirmed]"}


def sort_hits(df: pd.DataFrame, sort_label: str) -> pd.DataFrame:
    col, asc = SORTS.get(sort_label, SORTS["Biggest breakout"])
    d = df.assign(abs_change=df["change_pct"].abs())
    if col == "rs_vs_nifty_1m" and not d.empty and (d["type"] == "LOW").all():
        asc = True  # for lows, "strongest" relative move is the most negative
    return d.sort_values(col, ascending=asc, na_position="last")


def _signed(v, suffix="%", digits=1) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:+.{digits}f}{suffix}"


def _md_safe(text) -> str:
    """Escape characters that Streamlit markdown would treat as formatting."""
    s = str(text)
    for ch in ("[", "]", "*", "_", "`", "$"):
        s = s.replace(ch, "\\" + ch)
    return s


def headline(row: pd.Series) -> str:
    """Plain-English one-liner: how far past the old level, and the old level itself."""
    is_high = row["type"] == "HIGH"
    level = row["prior_52w_high"] if is_high else row["prior_52w_low"]
    beyond = abs(row["pct_beyond"]) if pd.notna(row["pct_beyond"]) else None
    pct = f"{beyond:.1f}%" if beyond is not None else "–"
    if is_high:
        return f":blue[**▲ {pct} above**] 52-week high {c.fmt_inr(level)}"
    return f":orange[**▼ {pct} below**] 52-week low {c.fmt_inr(level)}"


def stock_card(row: pd.Series, session: str, key: str, ai_ready: bool = False) -> None:
    """One tile: identity, price, the 52-week break in words, signal chips and a link to the deep dive."""
    with st.container(border=True, width=CARD_WIDTH, key=f"card_{key}", gap="xsmall"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(f"**{_md_safe(row['nse_symbol'])}**")
            st.space("stretch")
            st.markdown(STATUS_BADGE.get(str(row.get("status")), ""))
        name = re.sub(r"\s+(limited|ltd\.?)$", "", str(row["name"]).strip(), flags=re.I)
        st.caption(f"{_md_safe(name[:44])}  \n{_md_safe(row['sector'])} · {row['mcap_bucket']} cap")

        chg = row.get("change_pct")
        chg_md = "" if pd.isna(chg) else (f":green[{chg:+.2f}%]" if chg >= 0 else f":red[{chg:+.2f}%]")
        st.markdown(f"<span style='font-size:1.45rem;font-weight:600'>{c.fmt_inr(row['ltp'])}</span> "
                    f"&nbsp;{chg_md} today  \n{headline(row)}", unsafe_allow_html=True)

        chips = []
        vm = row.get("vol_multiple")
        if pd.notna(vm):
            chips.append(f":green-badge[Volume {vm:.1f}× ✓]" if row.get("volume_confirmed")
                         else f":gray-badge[Volume {vm:.1f}×]")
        if pd.notna(row.get("gap_pct")) and abs(row["gap_pct"]) >= 0.5:
            chips.append(f":gray-badge[Gap {row['gap_pct']:+.1f}%]")
        if row["type"] == "HIGH":
            chips.append(":blue-badge[Still above]" if bool(row.get("still_beyond")) else ":gray-badge[Fell back]")
        else:
            chips.append(":orange-badge[Still below]" if bool(row.get("still_beyond")) else ":gray-badge[Bounced back]")
        if row.get("short_history"):
            chips.append(":gray-badge[Listed < 1 yr]")
        if ai_ready:
            chips.append(":violet-badge[:material/auto_awesome: AI report ready]")
        st.markdown(" ".join(chips))

        rs = row.get("rs_vs_nifty_1m")
        first = row.get("first_hit") if isinstance(row.get("first_hit"), str) else None
        foot = [f"1-month vs Nifty {_signed(rs)}"] + ([f"first hit {first} IST"] if first else [])
        st.caption(" · ".join(foot))
        st.page_link(st.session_state["_pages"]["deep_dive"],
                     label="Read the AI report" if ai_ready else "Why did it move?",
                     icon=":material/arrow_forward:", icon_position="right",
                     query_params={"symbol": row["symbol"], "session": session})


def card_grid(df: pd.DataFrame, session: str, kind: str, ai_ready_keys: set) -> None:
    """Paged grid of stock cards with a 'Show more' button."""
    n_key = f"shown_{kind}_{session}"
    shown = st.session_state.get(n_key, PAGE_SIZE)
    page = df.head(shown)
    with st.container(horizontal=True, wrap=True, gap="small"):
        for i, (_, row) in enumerate(page.iterrows()):
            stock_card(row, session, key=f"{kind}_{i}_{row['symbol']}",
                       ai_ready=(row["symbol"], session, row["type"]) in ai_ready_keys)
    remaining = len(df) - len(page)
    if remaining > 0:
        if st.button(f"Show {min(PAGE_SIZE, remaining)} more ({remaining} not shown)", icon=":material/expand_more:",
                     key=f"more_{kind}_{session}"):
            st.session_state[n_key] = shown + PAGE_SIZE
            st.rerun()
