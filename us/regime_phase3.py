#!/usr/bin/env python3
"""US Nowcast — Phase 3: Regime classification grid.

Given (Growth_Z, Inflation_Z, Liquidity_Z) at each date, assign a regime label
using a 4-quadrant Growth×Inflation grid modified by Liquidity as a 3rd axis.

  Growth ↑ + Inflation ↑ = Overheating
  Growth ↑ + Inflation ↓ = Goldilocks
  Growth ↓ + Inflation ↑ = Stagflation
  Growth ↓ + Inflation ↓ = Deflation/Recession
  |Z| < THRESHOLD           = Neutral (per axis)

Liquidity modifier: easing / neutral / tightening.
"""
from __future__ import annotations
import os
import datetime as dt
import pandas as pd
import numpy as np
from pathlib import Path

_SKIP_CHARTS = os.environ.get("NOWCAST_SKIP_CHARTS") == "1"
if not _SKIP_CHARTS:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle

from nowcast_core import CHARTS

REGIME_THRESHOLD = 0.30

REGIME_COLORS = {
    "Overheating":         "#c05621",  # deep orange
    "Goldilocks":          "#38a169",  # green
    "Stagflation":         "#c53030",  # red
    "Deflation/Recession": "#2b6cb0",  # blue
    "Reflation":           "#805ad5",  # purple (growth up, inflation neutral)
    "Disinflation":        "#4fd1c5",  # teal (growth neutral, inflation down)
    "Slowdown":            "#d69e2e",  # amber
    "Neutral":             "#a0aec0",  # grey
}


def classify_row(g: float, i: float, l: float, th: float = REGIME_THRESHOLD) -> tuple[str, str]:
    """Return (regime_label, liquidity_modifier)."""
    if pd.isna(g) or pd.isna(i):
        return "Unknown", ""
    g_up = g >  th
    g_dn = g < -th
    i_up = i >  th
    i_dn = i < -th

    if g_up and i_up:
        base = "Overheating"
    elif g_up and i_dn:
        base = "Goldilocks"
    elif g_dn and i_up:
        base = "Stagflation"
    elif g_dn and i_dn:
        base = "Deflation/Recession"
    elif g_up and not (i_up or i_dn):
        base = "Reflation"
    elif g_dn and not (i_up or i_dn):
        base = "Slowdown"
    elif i_dn and not (g_up or g_dn):
        base = "Disinflation"
    else:
        base = "Neutral"

    if pd.isna(l):
        liq_mod = ""
    elif l > th:
        liq_mod = "Fed easing"
    elif l < -th:
        liq_mod = "Fed tightening"
    else:
        liq_mod = "Liquidity neutral"
    return base, liq_mod


def classify_series(g: pd.Series, i: pd.Series, l: pd.Series) -> pd.DataFrame:
    idx = g.index.union(i.index).union(l.index)
    # Forward-fill each pillar Z across small gaps so the joined index has
    # non-NaN values on the latest day. Cap the fill so we don't propagate
    # very stale values past a reasonable window.
    ga = g.reindex(idx).ffill(limit=45)
    ia = i.reindex(idx).ffill(limit=45)
    la = l.reindex(idx).ffill(limit=45)
    rows = []
    for t in idx:
        base, mod = classify_row(ga.loc[t], ia.loc[t], la.loc[t])
        rows.append({"date": t, "regime": base, "liq_mod": mod,
                     "g": ga.loc[t], "i": ia.loc[t], "l": la.loc[t]})
    return pd.DataFrame(rows).set_index("date")


def draw_regime_strip(regime_df: pd.DataFrame, out_path: Path, months: int = 24):
    """Draw 24-month monthly regime strip."""
    end = regime_df.index.max()
    start = end - pd.DateOffset(months=months)
    sub = regime_df.loc[start:end]
    # Monthly labels
    monthly = sub["regime"].resample("MS").agg(lambda x: x.mode().iloc[0] if len(x) else "Unknown")
    fig, ax = plt.subplots(figsize=(14, 1.4))
    for i, (m, r) in enumerate(monthly.items()):
        color = REGIME_COLORS.get(r, "#ccc")
        ax.add_patch(Rectangle((i, 0), 1, 1, color=color))
        ax.text(i + 0.5, 0.5, m.strftime("%b"), ha="center", va="center",
                fontsize=7, color="white", fontweight="bold")
    ax.set_xlim(0, len(monthly))
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.set_title(f"Regime history — last {months} months", fontsize=10, fontweight="bold", loc="left")
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()


def draw_regime_grid(g_latest: float, i_latest: float, out_path: Path):
    """2D scatter of Growth × Inflation with quadrant labels."""
    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(0, color="black", linewidth=0.8)
    # Threshold bands
    ax.axhspan(-REGIME_THRESHOLD, REGIME_THRESHOLD, alpha=0.05, color="grey")
    ax.axvspan(-REGIME_THRESHOLD, REGIME_THRESHOLD, alpha=0.05, color="grey")
    lim = 2.5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    # Quadrant labels
    ax.text( 1.5,  1.8, "Overheating",       ha="center", fontsize=10, fontweight="bold", color=REGIME_COLORS["Overheating"])
    ax.text( 1.5, -1.8, "Goldilocks",        ha="center", fontsize=10, fontweight="bold", color=REGIME_COLORS["Goldilocks"])
    ax.text(-1.5,  1.8, "Stagflation",       ha="center", fontsize=10, fontweight="bold", color=REGIME_COLORS["Stagflation"])
    ax.text(-1.5, -1.8, "Recession",         ha="center", fontsize=10, fontweight="bold", color=REGIME_COLORS["Deflation/Recession"])
    # Current point
    if not pd.isna(g_latest) and not pd.isna(i_latest):
        ax.scatter([g_latest], [i_latest], s=280, c="black", zorder=5)
        ax.scatter([g_latest], [i_latest], s=180, c="#f6e05e", zorder=6, edgecolor="black", linewidth=1.5)
        ax.annotate(f" Now: G={g_latest:+.2f}, I={i_latest:+.2f}",
                    xy=(g_latest, i_latest), xytext=(g_latest + 0.15, i_latest + 0.15),
                    fontsize=9, fontweight="bold")
    ax.set_xlabel("Growth Z", fontweight="bold")
    ax.set_ylabel("Inflation Z", fontweight="bold")
    ax.set_title("Regime grid (Growth × Inflation)", fontweight="bold")
    ax.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()


def draw_pillar_z_history(g: pd.Series, i: pd.Series, l: pd.Series, out_path: Path):
    fig, ax = plt.subplots(figsize=(12, 4.5))
    tail = 365 * 5
    for name, s, col in [("Growth", g, "#2c7a7b"), ("Inflation", i, "#c05621"), ("Liquidity", l, "#1a365d")]:
        s = s.dropna().tail(tail)
        if not s.empty:
            ax.plot(s.index, s.values, color=col, linewidth=1.6, label=name)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axhline( REGIME_THRESHOLD, color="grey", linestyle="--", linewidth=0.6)
    ax.axhline(-REGIME_THRESHOLD, color="grey", linestyle="--", linewidth=0.6)
    ax.set_ylim(-3, 3)
    ax.set_ylabel("Z-score (σ)")
    ax.set_title("Pillar Z-scores — 5-year history", fontweight="bold")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()


def compute_regime(growth_result: dict, inflation_result: dict, liquidity_result: dict) -> dict:
    g = growth_result["composite"]
    i = inflation_result["composite"]
    l = liquidity_result["composite"]

    regimes = classify_series(g, i, l)
    known = regimes[regimes["regime"] != "Unknown"]
    if known.empty:
        latest = regimes.iloc[-1]
    else:
        latest = known.iloc[-1]

    # Days in current regime
    cur = latest["regime"]
    since = latest.name
    for t, r in regimes["regime"].sort_index(ascending=False).items():
        if r != cur:
            since = t
            break
    else:
        since = regimes.index.min()
    # Advance to the first entry INTO cur
    prior = regimes["regime"] != cur
    if prior.any():
        last_diff = regimes.index[prior].max()
        entered = regimes.index[regimes.index > last_diff].min()
        since = entered
    days_in = (latest.name - since).days if since else None

    # Draw charts (skipped in the streamlit app path)
    if not _SKIP_CHARTS:
        draw_regime_strip(regimes, CHARTS / "regime_strip.png", months=24)
        draw_regime_grid(latest["g"], latest["i"], CHARTS / "regime_grid.png")
        draw_pillar_z_history(g, i, l, CHARTS / "pillar_z_history.png")

    return {
        "regime": cur,
        "liq_mod": latest["liq_mod"],
        "g": latest["g"],
        "i": latest["i"],
        "l": latest["l"],
        "as_of": latest.name,
        "since": since,
        "days_in_regime": days_in,
        "history": regimes,
    }


if __name__ == "__main__":
    # Rebuild everything for a standalone regime run
    import growth_phase2, inflation_phase2, liquidity_pillar
    g_res = growth_phase2.build()
    i_res = inflation_phase2.build()
    l_res = liquidity_pillar.build()
    r = compute_regime(g_res, i_res, l_res)
    print(f"\nCurrent regime: {r['regime']}  ({r['liq_mod']})")
    print(f"  Growth Z:    {r['g']:+.2f}")
    print(f"  Inflation Z: {r['i']:+.2f}")
    print(f"  Liquidity Z: {r['l']:+.2f}")
    print(f"  As of:       {r['as_of'].date()}")
    print(f"  Days in regime: {r['days_in_regime']}")
