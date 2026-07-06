#!/usr/bin/env python3
"""US Nowcast — Phase 2: Growth pillar.

Hard + Soft sub-pillars per INDICATOR-WEIGHTS.md. Positive Z = growth up.
Sign flipped on Initial Claims, Continuing Claims, Unemployment Rate.

Weights come from tier (A=1.0 B=0.7 C=0.5 D=0.3 E=0.15) and are normalised
within each sub-pillar. Sub-pillars are blended 50/50 into the composite.
"""
from __future__ import annotations
import os
import datetime as dt
from pathlib import Path
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
    normalise_weights, SKIPPED, CHARTS, top_movers,
)

# ---------------------------------------------------------------------------
# GROWTH pillar catalogue. Each entry is a FRED series with metadata.
# 'transform' is what the Z-score is computed on:
#   level     — raw index/spread/rate
#   diff      — first diff (for levels that trend)
#   mom       — monthly % change
#   yoy       — year-over-year % change
#   dyoy      — year-over-year change in level (for % rate series)
#
# 'sign' is applied AFTER Z is computed. -1 flips claims/unemp etc.
# ---------------------------------------------------------------------------

HARD_SERIES: list[dict] = [
    # Weekly labour
    {"id":"ICSA",       "tier":"A", "transform":"level", "sign":-1, "label":"Initial Jobless Claims"},
    {"id":"CCSA",       "tier":"B", "transform":"level", "sign":-1, "label":"Continuing Claims"},
    # Monthly labour (NFP is level of jobs, change is what we want -> diff on level, but PAYEMS is total employment; use diff = MoM change in payrolls)
    {"id":"PAYEMS",     "tier":"A", "transform":"diff",  "sign":+1, "label":"Nonfarm Payrolls MoM change"},
    {"id":"CES0500000003","tier":"B","transform":"yoy",  "sign":+1, "label":"AHE YoY (private, total)"},
    {"id":"UNRATE",     "tier":"A", "transform":"level", "sign":-1, "label":"Unemployment Rate"},
    {"id":"CIVPART",    "tier":"C", "transform":"level", "sign":+1, "label":"Labour Force Participation"},
    # Consumer / spending
    {"id":"RSXFS",      "tier":"A", "transform":"mom",   "sign":+1, "label":"Retail Sales ex-Food-Services MoM"},
    {"id":"PCEC96",     "tier":"B", "transform":"mom",   "sign":+1, "label":"Real Personal Spending MoM"},
    {"id":"PI",         "tier":"C", "transform":"mom",   "sign":+1, "label":"Personal Income MoM"},
    # Output
    {"id":"INDPRO",     "tier":"B", "transform":"mom",   "sign":+1, "label":"Industrial Production MoM"},
    {"id":"TCU",        "tier":"C", "transform":"level", "sign":+1, "label":"Capacity Utilization"},
    {"id":"DGORDER",    "tier":"C", "transform":"mom",   "sign":+1, "label":"Durable Goods Orders MoM"},
    {"id":"NEWORDER",   "tier":"B", "transform":"mom",   "sign":+1, "label":"Core Cap Goods Orders (ex-air) MoM"},
    {"id":"ANXAVS",     "tier":"B", "transform":"mom",   "sign":+1, "label":"Core Cap Goods Shipments (ex-air) MoM"},
    {"id":"AMTMNO",     "tier":"D", "transform":"mom",   "sign":+1, "label":"Factory Orders MoM"},
    # Housing
    {"id":"PERMIT",     "tier":"B", "transform":"mom",   "sign":+1, "label":"Building Permits MoM"},
    {"id":"HOUST",      "tier":"C", "transform":"mom",   "sign":+1, "label":"Housing Starts MoM"},
    {"id":"HSN1F",      "tier":"C", "transform":"mom",   "sign":+1, "label":"New Home Sales MoM"},
    {"id":"EXHOSLUSM495S","tier":"C", "transform":"mom",  "sign":+1, "label":"Existing Home Sales MoM"},
    {"id":"TTLCONS",    "tier":"D", "transform":"mom",   "sign":+1, "label":"Construction Spending MoM"},
    # JOLTS
    {"id":"JTSJOL",     "tier":"C", "transform":"level", "sign":+1, "label":"JOLTS Job Openings"},
    {"id":"JTSQUR",     "tier":"C", "transform":"level", "sign":+1, "label":"JOLTS Quits Rate"},
    # GDP
    {"id":"A191RL1Q225SBEA","tier":"E","transform":"level","sign":+1, "label":"Real GDP QoQ SAAR"},
    {"id":"OPHNFB",     "tier":"E", "transform":"yoy",   "sign":+1, "label":"Nonfarm Business Productivity YoY"},
]

# NOTE on ISM / NFIB / NAHB / Conference Board:
# These datasets were pulled from FRED in 2024 due to licensing changes.
# We substitute with the aggregate of regional Fed manufacturing surveys
# (NY / Philadelphia / Dallas / Richmond) which historically correlate
# ~0.85 with ISM Manufacturing PMI. See INDICATOR-WEIGHTS.md notes.
SOFT_SERIES: list[dict] = [
    # Regional Fed manufacturing surveys — collectively the best FRED-hosted
    # substitute for ISM Manufacturing PMI. Weighted at A/B tiers so they
    # sum to roughly the ISM headline+new-orders weight originally intended.
    {"id":"GACDISA066MSFRBNY",   "tier":"A", "transform":"level", "sign":+1, "label":"Empire Manufacturing (NY Fed)"},
    {"id":"GACDFSA066MSFRBPHI",  "tier":"A", "transform":"level", "sign":+1, "label":"Philadelphia Fed Business Outlook"},
    {"id":"BACTSAMFRBDAL",        "tier":"B", "transform":"level", "sign":+1, "label":"Dallas Fed Mfg Business Activity"},
    # Forward-looking sub-indices from the same surveys (new orders / capex)
    {"id":"NOCDISA066MSFRBNY",   "tier":"B", "transform":"level", "sign":+1, "label":"NY Fed New Orders (Manuf)"},
    {"id":"NOCDFSA066MSFRBPHI",  "tier":"B", "transform":"level", "sign":+1, "label":"Philly Fed New Orders (Manuf)"},
    {"id":"CEFDFSA066MSFRBPHI",  "tier":"C", "transform":"level", "sign":+1, "label":"Philly Fed Future CapEx"},
    # Chicago Fed composites (national activity + coincident + financial cond)
    {"id":"CFNAI",                "tier":"C", "transform":"level", "sign":+1, "label":"Chicago Fed National Activity Index"},
    {"id":"CFSBCACTIVITYMFG",     "tier":"C", "transform":"level", "sign":+1, "label":"Chicago Fed Mfg Activity (Survey)"},
    # U.S. Coincident + Leading (Philly Fed publishes)
    {"id":"USPHCI",               "tier":"C", "transform":"mom",   "sign":+1, "label":"US Coincident Economic Activity Idx MoM"},
    {"id":"USSLIND",              "tier":"C", "transform":"level", "sign":+1, "label":"US State Leading Index (Philly Fed)"},
    # Consumer sentiment (U.Mich still on FRED as headline)
    {"id":"UMCSENT",              "tier":"B", "transform":"level", "sign":+1, "label":"U. of Mich. Consumer Sentiment"},
    # NY Fed Weekly Economic Index — realtime nowcast
    {"id":"WEI",                  "tier":"A", "transform":"level", "sign":+1, "label":"NY Fed Weekly Economic Index"},
]

def build():
    print("[GROWTH] fetching series...")
    from nowcast_core import get_released_at
    con = init_cache()
    hard_raw = {}
    soft_raw = {}
    released = {}   # series_id -> ISO datetime string (FRED last_updated)

    for spec in HARD_SERIES:
        print(f"  [hard] {spec['id']:20} {spec['label']}")
        s = fetch_series(spec["id"], con, required=False)
        if s is not None and not s.empty:
            hard_raw[spec["id"]] = s
            released[spec["id"]] = get_released_at(con, spec["id"])
    for spec in SOFT_SERIES:
        print(f"  [soft] {spec['id']:20} {spec['label']}")
        s = fetch_series(spec["id"], con, required=False)
        if s is not None and not s.empty:
            soft_raw[spec["id"]] = s
            released[spec["id"]] = get_released_at(con, spec["id"])

    # Keep only specs that survived the fetch
    hard_specs = [s for s in HARD_SERIES if s["id"] in hard_raw]
    soft_specs = [s for s in SOFT_SERIES if s["id"] in soft_raw]
    normalise_weights(hard_specs)
    normalise_weights(soft_specs)

    # Compute per-series Z (sign-adjusted)
    hard_z: dict[str, pd.Series] = {}
    soft_z: dict[str, pd.Series] = {}
    for spec in hard_specs:
        z = zscore_36m(hard_raw[spec["id"]], spec["transform"]) * spec["sign"]
        hard_z[spec["id"]] = z
    for spec in soft_specs:
        z = zscore_36m(soft_raw[spec["id"]], spec["transform"]) * spec["sign"]
        soft_z[spec["id"]] = z

    hard_weights = {s["id"]: s["weight_norm"] for s in hard_specs}
    soft_weights = {s["id"]: s["weight_norm"] for s in soft_specs}
    hard_comp = build_composite(hard_z, hard_weights)
    soft_comp = build_composite(soft_z, soft_weights)
    # 50/50 blend for pillar composite
    idx = hard_comp.index.union(soft_comp.index)
    g_comp = (hard_comp.reindex(idx).fillna(0) + soft_comp.reindex(idx).fillna(0)) / (
        (hard_comp.reindex(idx).notna().astype(float) + soft_comp.reindex(idx).notna().astype(float)).replace(0, np.nan)
    )
    ghss = hard_comp.reindex(idx) - soft_comp.reindex(idx)

    # Breadth (all components)
    all_z = {**hard_z, **soft_z}
    br = breadth(all_z)

    labels = {s["id"]: s["label"] for s in hard_specs + soft_specs}
    result = {
        "pillar": "growth",
        "hard_z": hard_comp,
        "soft_z": soft_comp,
        "composite": g_comp,
        "hss": ghss,  # hard-soft spread
        "breadth": br,
        "component_z": all_z,
        "hard_specs": hard_specs,
        "soft_specs": soft_specs,
        "raw": {**hard_raw, **soft_raw},
        "released": released,
        "labels": labels,
    }
    _draw_charts(result)
    return result


def _draw_charts(res: dict):
    if _SKIP_CHARTS:
        return
    tail_years = 5
    tail_days = 365 * tail_years
    # Composite chart
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for name, s, col, lw in [
        ("Composite Growth Z", res["composite"], "#1a365d", 2.2),
        ("Hard sub-Z",         res["hard_z"],   "#2c7a7b", 1.2),
        ("Soft sub-Z",         res["soft_z"],   "#c0392b", 1.2),
    ]:
        s = s.dropna().tail(tail_days)
        if not s.empty:
            ax.plot(s.index, s.values, color=col, linewidth=lw, alpha=0.9, label=name)
    ax.axhline(0, color="black", linewidth=0.8)
    latest = res["composite"].dropna().iloc[-1] if not res["composite"].dropna().empty else float("nan")
    latest_dt = res["composite"].dropna().index[-1].date() if not res["composite"].dropna().empty else "?"
    ax.set_title(f"GROWTH Z-SCORE  (36m rolling)   Latest composite: {latest:+.2f}σ  ({latest_dt})",
                 fontweight="bold")
    ax.set_ylabel("Z-score (σ)")
    ax.set_ylim(-3, 3)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(CHARTS / "growth_z.png", dpi=120, bbox_inches="tight")
    plt.close()

    # Components strip
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
        plt.suptitle("Growth pillar — component Z-scores (36m rolling)", fontweight="bold", y=1.00)
        plt.tight_layout()
        plt.savefig(CHARTS / "growth_components.png", dpi=110, bbox_inches="tight")
        plt.close()


if __name__ == "__main__":
    r = build()
    latest = r["composite"].dropna()
    print(f"\nGrowth composite Z (latest): {latest.iloc[-1]:+.2f}  as of {latest.index[-1].date()}")
    print(f"Hard sub-Z: {r['hard_z'].dropna().iloc[-1]:+.2f}")
    print(f"Soft sub-Z: {r['soft_z'].dropna().iloc[-1]:+.2f}")
    print(f"Breadth: {r['breadth'].dropna().iloc[-1]:.0f}%")
    if SKIPPED:
        print("\nSkipped:")
        for sid, reason in SKIPPED:
            print(f"  {sid}: {reason}")
