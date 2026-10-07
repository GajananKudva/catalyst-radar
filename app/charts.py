"""Plotly figures for the dashboard (rendered with Streamlit's theme for light/dark)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from common import HIGH_COLOR, LOW_COLOR

GRID = "rgba(128,128,128,0.18)"
BASE_LAYOUT = dict(
    margin=dict(l=16, r=16, t=36, b=16),
    hovermode="closest",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
    barcornerradius=4,
)


def sector_breadth_fig(breadth: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Grouped horizontal bars: 52-week highs and lows per sector."""
    d = breadth.copy()
    d["total"] = d["highs"] + d["lows"]
    d = d[d["total"] > 0].sort_values(["highs", "lows"], ascending=False).head(top_n)
    d = d.iloc[::-1]  # largest at the top
    fig = go.Figure()
    for col, name, color in (("highs", "▲ 52W highs", HIGH_COLOR), ("lows", "▼ 52W lows", LOW_COLOR)):
        pct = d[f"pct_{'high' if col == 'highs' else 'low'}"]
        fig.add_bar(
            y=d["sector"], x=d[col], name=name, orientation="h", marker_color=color,
            text=d[col].where(d[col] > 0, ""), textposition="outside", cliponaxis=False, textfont=dict(size=12),
            customdata=pd.concat([d["stocks"], pct], axis=1).to_numpy(),
            hovertemplate="<b>%{y}</b><br>" + name + ": %{x}<br>"
                          "%{customdata[1]:.1f}% of %{customdata[0]} stocks in sector<extra></extra>",
        )
    fig.update_layout(**BASE_LAYOUT, barmode="group", bargap=0.25, bargroupgap=0.08,
                      height=max(320, 34 * len(d) + 80))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=False, title=None)
    fig.update_yaxes(showgrid=False, title=None, automargin=True)
    return fig


def trend_fig(counts: pd.DataFrame) -> go.Figure:
    """Daily count of confirmed 52-week highs and lows."""
    fig = go.Figure()
    for col, name, color in (("HIGH", "▲ 52W highs", HIGH_COLOR), ("LOW", "▼ 52W lows", LOW_COLOR)):
        fig.add_scatter(
            x=counts["session_date"], y=counts[col], name=name, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=8, color=color, line=dict(width=2, color="white")),
            hovertemplate="%{x}<br>" + name + ": %{y}<extra></extra>",
        )
        if len(counts):
            fig.add_annotation(x=counts["session_date"].iloc[-1], y=counts[col].iloc[-1],
                               text=f"{name.split(' ', 1)[1]}: {counts[col].iloc[-1]}",
                               showarrow=False, xanchor="left", xshift=10, font=dict(size=12))
    fig.update_layout(**{**BASE_LAYOUT, "hovermode": "x unified"}, height=340)
    fig.update_xaxes(type="category", showgrid=False, title=None)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, rangemode="tozero", title=None)
    return fig


def volume_scatter_fig(df: pd.DataFrame, kind: str) -> go.Figure:
    """How far past the old extreme vs how unusual the volume is (one dot per stock)."""
    color = HIGH_COLOR if kind == "HIGH" else LOW_COLOR
    d = df.dropna(subset=["vol_multiple", "abs_beyond"])
    fig = go.Figure(go.Scatter(
        x=d["vol_multiple"].clip(lower=0.05), y=d["abs_beyond"], mode="markers",
        marker=dict(size=10, color=color, opacity=0.85, line=dict(width=2, color="white")),
        text=d["nse_symbol"], customdata=d[["name", "sector"]].to_numpy(),
        hovertemplate="<b>%{text}</b> · %{customdata[0]}<br>%{customdata[1]}<br>"
                      "Volume: %{x:.1f}× 20-day avg<br>Beyond old extreme: %{y:.2f}%<extra></extra>",
    ))
    fig.add_vline(x=1.5, line=dict(color="rgba(128,128,128,0.6)", dash="dot", width=1))
    fig.add_annotation(x=1.5, y=1, yref="paper", text="1.5× volume", showarrow=False,
                       xanchor="left", xshift=4, font=dict(size=11))
    fig.update_layout(**BASE_LAYOUT, height=360, showlegend=False,
                      title=dict(text="Volume vs distance past the 52-week level", font=dict(size=14)))
    fig.update_xaxes(type="log", title="Volume (× 20-day average, log scale)", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(title="% beyond prior 52-week level", showgrid=True, gridcolor=GRID, rangemode="tozero")
    return fig


def price_fig(px: pd.DataFrame, level: float | None, kind: str, session: str | None) -> go.Figure:
    """One year of daily candles with the prior 52-week level, plus volume underneath."""
    color = HIGH_COLOR if kind == "HIGH" else LOW_COLOR
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.04)
    fig.add_candlestick(x=px.index, open=px["Open"], high=px["High"], low=px["Low"], close=px["Close"],
                        name="Price", increasing_line_color="#1baf7a", decreasing_line_color="#e34948",
                        row=1, col=1)
    if level:
        label = "Prior 52W high" if kind == "HIGH" else "Prior 52W low"
        fig.add_hline(y=level, line=dict(color=color, dash="dash", width=2), row=1, col=1)
        fig.add_annotation(x=px.index[0], y=level, text=f"{label} ₹{level:,.2f}", showarrow=False,
                           xanchor="left", yanchor="bottom", font=dict(size=12, color=color), row=1, col=1)
    if session is not None:
        ts = pd.Timestamp(session)
        if ts in px.index:
            y = px.loc[ts, "High"] if kind == "HIGH" else px.loc[ts, "Low"]
            fig.add_scatter(x=[ts], y=[y], mode="markers", name="Hit day",
                            marker=dict(size=12, color=color, symbol="triangle-up" if kind == "HIGH" else "triangle-down",
                                        line=dict(width=2, color="white")), row=1, col=1,
                            hovertemplate="52-week " + kind.lower() + " day<br>%{x|%d %b %Y}: ₹%{y:,.2f}<extra></extra>")
    fig.add_bar(x=px.index, y=px["Volume"], name="Volume", marker_color="rgba(128,128,128,0.55)",
                row=2, col=1, hovertemplate="%{x|%d %b %Y}<br>Volume: %{y:,.0f}<extra></extra>")
    fig.update_layout(margin=dict(l=60, r=16, t=10, b=30), height=520, showlegend=False,
                      xaxis_rangeslider_visible=False, hovermode="x unified", bargap=0.1)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, row=1, col=1, tickprefix="₹", automargin=True)
    fig.update_yaxes(showgrid=False, row=2, col=1, automargin=True, title=dict(text="Volume", font=dict(size=11)))
    fig.update_xaxes(showgrid=False, rangebreaks=[dict(bounds=["sat", "mon"])])
    return fig
