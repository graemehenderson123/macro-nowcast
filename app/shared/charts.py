"""Plotly chart helpers for the nowcast app.

All charts respect an optional ``tail_days`` argument so a page-level time
range selector can shorten the horizon on every chart consistently.
"""
from __future__ import annotations
from typing import Mapping
import math
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .theme import NAVY, TEAL, BRICK, ORANGE, GREEN, AMBER, REGIME_COLORS


# ---------------------------------------------------------------------------
def _tail(series: pd.Series, tail_days: int | None) -> pd.Series:
    if tail_days is None:
        return series
    if series.empty:
        return series
    end = series.index.max()
    start = end - pd.Timedelta(days=int(tail_days))
    return series.loc[series.index >= start]


def _base_layout(title: str = "", height: int = 380) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=14, color="#222")) if title else None,
        margin=dict(l=40, r=20, t=40 if title else 15, b=30),
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        xaxis=dict(
            showgrid=True, gridcolor="#eef", zeroline=False,
            rangeslider=dict(visible=False),
        ),
        yaxis=dict(showgrid=True, gridcolor="#eef", zeroline=True, zerolinecolor="#888"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
    )


# ---------------------------------------------------------------------------
def pillar_z_chart(
    composite: pd.Series,
    hard: pd.Series,
    soft: pd.Series,
    labels: tuple[str, str, str] = ("Composite Z", "Hard sub-Z", "Soft sub-Z"),
    colors: tuple[str, str, str] = (NAVY, TEAL, BRICK),
    tail_days: int | None = 365 * 5,
    height: int = 360,
    title: str = "",
) -> go.Figure:
    fig = go.Figure()
    for s, name, col, lw in [
        (composite, labels[0], colors[0], 2.4),
        (hard,      labels[1], colors[1], 1.4),
        (soft,      labels[2], colors[2], 1.4),
    ]:
        ss = _tail(s.dropna(), tail_days)
        if ss.empty:
            continue
        fig.add_trace(go.Scatter(
            x=ss.index, y=ss.values, mode="lines", name=name,
            line=dict(color=col, width=lw),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}σ<extra>" + name + "</extra>",
        ))
    fig.add_hline(y=0, line=dict(color="black", width=0.8))
    fig.update_layout(**_base_layout(title=title, height=height))
    fig.update_yaxes(range=[-3, 3], title="Z-score (σ)")
    return fig


def component_z_chart(
    z: pd.Series,
    label: str,
    color: str = NAVY,
    tail_days: int | None = 365 * 5,
    height: int = 240,
) -> go.Figure:
    fig = go.Figure()
    ss = _tail(z.dropna(), tail_days)
    if ss.empty:
        return fig
    # Split into pos/neg for shading
    fig.add_trace(go.Scatter(
        x=ss.index, y=ss.values, mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy", fillcolor="rgba(56, 161, 105, 0.14)",
        name=label,
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}σ<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#888", width=0.6))
    fig.update_layout(
        title=dict(text=label[:60], font=dict(size=12)),
        margin=dict(l=35, r=10, t=30, b=25),
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        hovermode="x",
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(range=[-3, 3], showgrid=True, gridcolor="#eef"),
    )
    return fig


def sparkline(
    z: pd.Series,
    tail_days: int | None = 365 * 3,
    height: int = 60,
    color: str = NAVY,
) -> go.Figure:
    fig = go.Figure()
    ss = _tail(z.dropna(), tail_days)
    if ss.empty:
        return fig
    fig.add_trace(go.Scatter(
        x=ss.index, y=ss.values, mode="lines",
        line=dict(color=color, width=1.4),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}σ<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#aaa", width=0.5))
    fig.update_layout(
        margin=dict(l=0, r=0, t=4, b=4),
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        hovermode="x",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, range=[-3, 3]),
    )
    return fig


def raw_series_chart(
    raw: pd.Series,
    label: str,
    color: str = NAVY,
    tail_days: int | None = 365 * 5,
    height: int = 240,
) -> go.Figure:
    fig = go.Figure()
    ss = _tail(raw.dropna(), tail_days)
    if ss.empty:
        return fig
    fig.add_trace(go.Scatter(
        x=ss.index, y=ss.values, mode="lines",
        line=dict(color=color, width=1.4),
        name=label,
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=label[:60] + " (raw)", font=dict(size=12)),
        margin=dict(l=40, r=10, t=30, b=30),
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
        hovermode="x",
        xaxis=dict(showgrid=True, gridcolor="#eef"),
        yaxis=dict(showgrid=True, gridcolor="#eef"),
    )
    return fig


# ---------------------------------------------------------------------------
def regime_strip(regime_history: pd.DataFrame, months: int = 24) -> go.Figure:
    """Heatmap-style horizontal strip of monthly regime labels."""
    if regime_history.empty:
        return go.Figure()
    end = regime_history.index.max()
    start = end - pd.DateOffset(months=months)
    sub = regime_history.loc[start:end]
    monthly = sub["regime"].resample("MS").agg(
        lambda x: x.mode().iloc[0] if len(x) else "Unknown"
    )
    # Assign each regime an ordinal for the heatmap
    unique = list(dict.fromkeys(monthly.values))
    idx_map = {r: i for i, r in enumerate(unique)}
    colors = [REGIME_COLORS.get(r, "#ccc") for r in unique]
    # Build discrete colorscale
    if len(unique) == 1:
        colorscale = [[0, colors[0]], [1, colors[0]]]
    else:
        step = 1.0 / (len(unique) - 1)
        colorscale = []
        for i, c in enumerate(colors):
            colorscale.append([i * step, c])
    z = [[idx_map[r] for r in monthly.values]]
    xlabels = [d.strftime("%b '%y") for d in monthly.index]
    text = [[r for r in monthly.values]]
    fig = go.Figure(data=go.Heatmap(
        z=z, x=xlabels, y=["Regime"],
        text=text, hovertemplate="%{x}<br><b>%{text}</b><extra></extra>",
        colorscale=colorscale,
        showscale=False,
        xgap=2, ygap=0,
        zmin=0, zmax=max(len(unique) - 1, 1),
    ))
    # Overlay regime name on each cell
    annotations = []
    for i, (m, r) in enumerate(monthly.items()):
        annotations.append(dict(
            x=xlabels[i], y="Regime",
            text=m.strftime("%b"), showarrow=False,
            font=dict(color="white", size=10, family="sans-serif"),
        ))
    fig.update_layout(
        title=dict(text=f"Regime history — last {months} months", font=dict(size=13)),
        annotations=annotations,
        height=110,
        margin=dict(l=20, r=20, t=35, b=10),
        xaxis=dict(showgrid=False, tickangle=-45, tickfont=dict(size=9)),
        yaxis=dict(showgrid=False, showticklabels=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


def regime_grid_scatter(g: float, i: float, threshold: float = 0.30) -> go.Figure:
    """2D scatter with quadrant labels, showing current (G, I)."""
    fig = go.Figure()
    lim = 2.5
    # threshold bands
    fig.add_shape(type="rect", x0=-lim, y0=-threshold, x1=lim, y1=threshold,
                  fillcolor="rgba(160,174,192,0.10)", line_width=0)
    fig.add_shape(type="rect", x0=-threshold, y0=-lim, x1=threshold, y1=lim,
                  fillcolor="rgba(160,174,192,0.10)", line_width=0)
    fig.add_hline(y=0, line=dict(color="black", width=0.8))
    fig.add_vline(x=0, line=dict(color="black", width=0.8))
    # Quadrant labels
    quad_labels = [
        ( 1.5,  1.9, "Overheating",   REGIME_COLORS["Overheating"]),
        ( 1.5, -1.9, "Goldilocks",    REGIME_COLORS["Goldilocks"]),
        (-1.5,  1.9, "Stagflation",   REGIME_COLORS["Stagflation"]),
        (-1.5, -1.9, "Recession",     REGIME_COLORS["Deflation/Recession"]),
    ]
    for x, y, name, col in quad_labels:
        fig.add_annotation(x=x, y=y, text=f"<b>{name}</b>", showarrow=False,
                           font=dict(size=12, color=col))
    if not (math.isnan(g) or math.isnan(i)):
        fig.add_trace(go.Scatter(
            x=[g], y=[i], mode="markers+text",
            marker=dict(size=22, color="#f6e05e", line=dict(color="black", width=2)),
            text=[f"Now"], textposition="top center",
            hovertemplate=f"Growth Z: {g:+.2f}σ<br>Inflation Z: {i:+.2f}σ<extra></extra>",
            showlegend=False,
        ))
    fig.update_layout(
        title=dict(text="Regime grid (Growth × Inflation)", font=dict(size=13)),
        height=440,
        margin=dict(l=40, r=20, t=40, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(range=[-lim, lim], title="Growth Z", showgrid=True, gridcolor="#eef"),
        yaxis=dict(range=[-lim, lim], title="Inflation Z", showgrid=True, gridcolor="#eef"),
        showlegend=False,
    )
    return fig


def three_pillar_history(
    growth: pd.Series, inflation: pd.Series, liquidity: pd.Series,
    tail_days: int | None = 365 * 5,
    threshold: float = 0.30,
    height: int = 380,
) -> go.Figure:
    fig = go.Figure()
    for name, s, col in [("Growth", growth, TEAL), ("Inflation", inflation, ORANGE), ("Liquidity", liquidity, NAVY)]:
        ss = _tail(s.dropna(), tail_days)
        if ss.empty:
            continue
        fig.add_trace(go.Scatter(
            x=ss.index, y=ss.values, mode="lines", name=name,
            line=dict(color=col, width=1.7),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}σ<extra>" + name + "</extra>",
        ))
    fig.add_hline(y=0, line=dict(color="black", width=0.7))
    fig.add_hline(y=threshold, line=dict(color="grey", width=0.5, dash="dash"))
    fig.add_hline(y=-threshold, line=dict(color="grey", width=0.5, dash="dash"))
    fig.update_layout(**_base_layout(title="Pillar Z-scores (blended composite)", height=height))
    fig.update_yaxes(range=[-3, 3], title="Z-score (σ)")
    return fig


def net_fed_liquidity_chart(s: pd.Series, tail_days: int | None = 365 * 5, height: int = 320) -> go.Figure:
    fig = go.Figure()
    ss = _tail(s.dropna(), tail_days)
    if ss.empty:
        return fig
    fig.add_trace(go.Scatter(
        x=ss.index, y=ss.values, mode="lines",
        line=dict(color=NAVY, width=1.8),
        fill="tozeroy", fillcolor="rgba(26,54,93,0.08)",
        name="Net Fed Liquidity",
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}bn<extra></extra>",
    ))
    fig.update_layout(**_base_layout(
        title=f"Net Fed Liquidity (WALCL − TGA − RRP)  ·  latest ${ss.iloc[-1]:,.0f}bn",
        height=height,
    ))
    fig.update_yaxes(title="$ billions")
    return fig
