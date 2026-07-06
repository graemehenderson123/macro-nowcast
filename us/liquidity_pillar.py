#!/usr/bin/env python3
"""US Nowcast — Liquidity pillar builder (Phase 1 wrapped for combined dashboard).

Same series catalogue as liquidity_phase1.py but returns a structured dict
identical in shape to the growth/inflation pillars for regime_phase3 / build_all.
Also emits NET_FED_LIQUIDITY line as a bonus signal.
"""
from __future__ import annotations
import os
import datetime as dt
import pandas as pd
import numpy as np

_SKIP_CHARTS = os.environ.get("NOWCAST_SKIP_CHARTS") == "1"
if not _SKIP_CHARTS:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

from nowcast_core import (
    init_cache, fetch_series, zscore_36m, build_composite, breadth,
    normalise_weights, SKIPPED, CHARTS,
)

FED_SERIES = [
    {"id":"WALCL",      "tier":"A", "transform":"diff",  "sign":+1, "label":"Fed Balance Sheet (WALCL)"},
    {"id":"WTREGEN",    "tier":"A", "transform":"diff",  "sign":-1, "label":"Treasury General Account (TGA)"},
    {"id":"RRPONTSYD",  "tier":"A", "transform":"diff",  "sign":-1, "label":"Overnight Reverse Repo (RRP)"},
    {"id":"TOTRESNS",   "tier":"B", "transform":"diff",  "sign":+1, "label":"Bank Reserves (TOTRESNS)"},
]

MKT_SERIES = [
    {"id":"BAMLC0A0CM", "tier":"A", "transform":"level", "sign":-1, "label":"IG OAS"},
    {"id":"BAMLH0A0HYM2","tier":"A","transform":"level", "sign":-1, "label":"HY OAS"},
    {"id":"DGS2",       "tier":"B", "transform":"level", "sign":-1, "label":"2y UST yield"},
    {"id":"DGS10",      "tier":"B", "transform":"level", "sign":-1, "label":"10y UST yield"},
    {"id":"T10Y2Y",     "tier":"B", "transform":"level", "sign":+1, "label":"2s10s curve"},
    {"id":"T5YIFR",     "tier":"C", "transform":"level", "sign":+1, "label":"5y5y forward breakeven"},
    {"id":"VIXCLS",     "tier":"A", "transform":"level", "sign":-1, "label":"VIX"},
    {"id":"DTWEXBGS",   "tier":"A", "transform":"level", "sign":-1, "label":"Broad USD index"},
]


def build():
    print("[LIQUIDITY] fetching series...")
    from nowcast_core import get_released_at
    con = init_cache()
    raw: dict[str, pd.Series] = {}
    released: dict[str, str | None] = {}
    for spec in FED_SERIES + MKT_SERIES:
        print(f"  {spec['id']:12}")
        s = fetch_series(spec["id"], con, required=False)
        if s is not None and not s.empty:
            raw[spec["id"]] = s
            released[spec["id"]] = get_released_at(con, spec["id"])

    fed_specs = [s for s in FED_SERIES if s["id"] in raw]
    mkt_specs = [s for s in MKT_SERIES if s["id"] in raw]
    normalise_weights(fed_specs)
    normalise_weights(mkt_specs)

    fed_z: dict[str, pd.Series] = {}
    mkt_z: dict[str, pd.Series] = {}
    for spec in fed_specs:
        z = zscore_36m(raw[spec["id"]], spec["transform"]) * spec["sign"]
        fed_z[spec["id"]] = z
    for spec in mkt_specs:
        z = zscore_36m(raw[spec["id"]], spec["transform"]) * spec["sign"]
        mkt_z[spec["id"]] = z

    fed_w = {s["id"]: s["weight_norm"] for s in fed_specs}
    mkt_w = {s["id"]: s["weight_norm"] for s in mkt_specs}
    fed_comp = build_composite(fed_z, fed_w)
    mkt_comp = build_composite(mkt_z, mkt_w)

    idx = fed_comp.index.union(mkt_comp.index)
    f = fed_comp.reindex(idx)
    m = mkt_comp.reindex(idx)
    num = f.fillna(0) + m.fillna(0)
    den = f.notna().astype(float) + m.notna().astype(float)
    l_comp = num / den.where(den > 0)

    all_z = {**fed_z, **mkt_z}
    br = breadth(all_z)

    labels = {s["id"]: s["label"] for s in fed_specs + mkt_specs}

    # NET_FED_LIQUIDITY = WALCL - TGA - RRP, all in $bn (WALCL/TGA in $m -> /1000)
    net_fed = None
    if all(k in raw for k in ("WALCL", "WTREGEN", "RRPONTSYD")):
        idx2 = raw["WALCL"].index.union(raw["WTREGEN"].index).union(raw["RRPONTSYD"].index)
        walcl = raw["WALCL"].reindex(idx2).ffill(limit=14) / 1000.0
        tga   = raw["WTREGEN"].reindex(idx2).ffill(limit=14) / 1000.0
        rrp   = raw["RRPONTSYD"].reindex(idx2).ffill(limit=14)
        net_fed = walcl - tga - rrp

    result = {
        "pillar": "liquidity",
        "hard_z": fed_comp,     # Fed = "hard" here
        "soft_z": mkt_comp,     # Market = "soft" here
        "composite": l_comp,
        "hss": fed_comp - mkt_comp,
        "breadth": br,
        "component_z": all_z,
        "hard_specs": fed_specs,
        "soft_specs": mkt_specs,
        "raw": raw,
        "released": released,
        "labels": labels,
        "net_fed_liquidity": net_fed,
    }
    _draw_charts(result)
    return result


def _draw_charts(res: dict):
    if _SKIP_CHARTS:
        return
    tail_days = 365 * 5
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for name, s, col, lw in [
        ("Composite Liquidity Z", res["composite"], "#1a365d", 2.2),
        ("Fed sub-Z",             res["hard_z"],   "#2c7a7b", 1.2),
        ("Market sub-Z",          res["soft_z"],   "#c0392b", 1.2),
    ]:
        s = s.dropna().tail(tail_days)
        if not s.empty:
            ax.plot(s.index, s.values, color=col, linewidth=lw, alpha=0.9, label=name)
    ax.axhline(0, color="black", linewidth=0.8)
    latest = res["composite"].dropna()
    latest_v = latest.iloc[-1] if not latest.empty else float("nan")
    latest_dt = latest.index[-1].date() if not latest.empty else "?"
    ax.set_title(f"LIQUIDITY Z-SCORE  (36m rolling, +ve = easier)   Latest composite: {latest_v:+.2f}σ  ({latest_dt})",
                 fontweight="bold")
    ax.set_ylabel("Z-score (σ)")
    ax.set_ylim(-3, 3)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(CHARTS / "liquidity_z.png", dpi=120, bbox_inches="tight")
    plt.close()

    # Net fed liquidity chart
    if res.get("net_fed_liquidity") is not None:
        s = res["net_fed_liquidity"].dropna().tail(365 * 5)
        if not s.empty:
            fig, ax = plt.subplots(figsize=(12, 4.5))
            ax.plot(s.index, s.values, color="#1a365d", linewidth=1.8)
            ax.fill_between(s.index, s.values, s.values.min(), color="#1a365d", alpha=0.08)
            ax.set_title(f"NET FED LIQUIDITY  (WALCL − TGA − RRP, $bn)   Latest: {s.iloc[-1]:,.0f}bn  ({s.index[-1].date()})",
                         fontweight="bold")
            ax.set_ylabel("$ billions")
            ax.grid(alpha=0.3)
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            plt.tight_layout()
            plt.savefig(CHARTS / "net_fed_liquidity.png", dpi=120, bbox_inches="tight")
            plt.close()

    all_specs = res["hard_specs"] + res["soft_specs"]
    n = len(all_specs)
    if n:
        cols = 4
        rows = int(np.ceil(n / cols))
        fig, axes = plt.subplots(rows, cols, figsize=(15, rows * 1.9), sharex=False)
        axes = axes.flatten()
        for i, spec in enumerate(all_specs):
            ax = axes[i]
            z = res["component_z"].get(spec["id"], pd.Series(dtype=float)).dropna().tail(tail_days)
            if not z.empty:
                ax.plot(z.index, z.values, color="#1a365d", linewidth=1.2)
                ax.axhline(0, color="black", linewidth=0.5, alpha=0.6)
                ax.fill_between(z.index, z.values, 0, where=(z.values > 0), color="green", alpha=0.15)
                ax.fill_between(z.index, z.values, 0, where=(z.values < 0), color="red", alpha=0.15)
                ax.text(0.02, 0.92, f"{z.iloc[-1]:+.2f}σ", transform=ax.transAxes,
                        fontsize=8, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7))
            ax.set_title(spec["label"][:36], fontsize=8)
            ax.set_ylim(-3, 3)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=0.3)
        for j in range(n, len(axes)):
            axes[j].set_visible(False)
        plt.suptitle("Liquidity pillar — component Z-scores (36m rolling)", fontweight="bold", y=1.00)
        plt.tight_layout()
        plt.savefig(CHARTS / "liquidity_components.png", dpi=110, bbox_inches="tight")
        plt.close()


if __name__ == "__main__":
    r = build()
    latest = r["composite"].dropna()
    print(f"\nLiquidity composite Z (latest): {latest.iloc[-1]:+.2f}  as of {latest.index[-1].date()}")
    if SKIPPED:
        print("\nSkipped:")
        for sid, reason in SKIPPED:
            print(f"  {sid}: {reason}")
