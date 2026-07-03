#!/usr/bin/env python3
"""US Nowcast — Phase 2: Inflation pillar.

Hard + Soft sub-pillars per INDICATOR-WEIGHTS.md. Positive Z = inflation up.
Blend Hard/Soft as 40/60 (skewed to soft, since expectations lead prints).
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
    normalise_weights, SKIPPED, CHARTS,
)

# ---------------------------------------------------------------------------
HARD_SERIES: list[dict] = [
    # Core PCE — PCEPILFE is price index (level), take mom/yoy
    {"id":"PCEPILFE",  "tier":"A", "transform":"mom", "sign":+1, "label":"Core PCE Price Index MoM"},
    {"id":"PCEPILFE_yoy","tier":"B","transform":"yoy","sign":+1, "label":"Core PCE Price Index YoY",
     "source_id":"PCEPILFE"},
    {"id":"PCEPI",     "tier":"B", "transform":"mom", "sign":+1, "label":"Headline PCE Price Index MoM"},
    # CPI
    {"id":"CPILFESL",  "tier":"A", "transform":"mom", "sign":+1, "label":"Core CPI MoM"},
    {"id":"CPILFESL_yoy","tier":"B","transform":"yoy","sign":+1, "label":"Core CPI YoY",
     "source_id":"CPILFESL"},
    {"id":"CPIAUCSL",  "tier":"B", "transform":"mom", "sign":+1, "label":"Headline CPI MoM"},
    {"id":"CPIAUCSL_yoy","tier":"C","transform":"yoy","sign":+1, "label":"Headline CPI YoY",
     "source_id":"CPIAUCSL"},
    # PPI
    {"id":"PPIFIS",    "tier":"C", "transform":"mom", "sign":+1, "label":"PPI Final Demand MoM"},
    {"id":"WPSFD4131", "tier":"C", "transform":"mom", "sign":+1, "label":"PPI Ex Food & Energy MoM"},
    # Wages
    {"id":"CES0500000003","tier":"B","transform":"mom","sign":+1, "label":"AHE MoM (private, total)"},
    {"id":"CES0500000003_yoy","tier":"B","transform":"yoy","sign":+1, "label":"AHE YoY (private, total)",
     "source_id":"CES0500000003"},
    # Import prices
    {"id":"IR",        "tier":"D", "transform":"mom", "sign":+1, "label":"Import Price Index MoM"},
    # Unit labour costs (quarterly)
    {"id":"ULCNFB",    "tier":"E", "transform":"yoy", "sign":+1, "label":"Unit Labor Costs YoY"},
    # ECI (quarterly employment cost index — a wages measure watched by Fed)
    {"id":"ECIWAG",    "tier":"C", "transform":"yoy", "sign":+1, "label":"Employment Cost Index Wages YoY"},
]

# NOTE: ISM Prices Paid (NAPMPRI/NMFPI) removed from FRED in 2024. We substitute
# with NY Fed / Philly Fed Prices Paid diffusion indices — same signal, same
# monthly cadence, cross-sectional agreement with ISM historically ~0.9.
# U.Mich 5-10y (MICH5Y) also removed — replaced with Cleveland Fed 5y expected
# inflation (EXPINF5YR), model-based and daily.
SOFT_SERIES: list[dict] = [
    # Regional Fed prices paid (ISM Prices Paid substitute)
    {"id":"PPCDISA066MSFRBNY",   "tier":"A", "transform":"level", "sign":+1, "label":"NY Fed Prices Paid (Manuf)"},
    {"id":"PPCDFSA066MSFRBPHI",  "tier":"A", "transform":"level", "sign":+1, "label":"Philly Fed Prices Paid (Manuf)"},
    # U.Mich 1y expectations
    {"id":"MICH",                 "tier":"B", "transform":"level", "sign":+1, "label":"U.Mich 1y Inflation Expectations"},
    # Cleveland Fed 5y expected inflation (substitute for U.Mich 5-10y)
    {"id":"EXPINF5YR",            "tier":"A", "transform":"level", "sign":+1, "label":"CleveFed 5y Expected Inflation (long-anchor)"},
    # 1y expected inflation (CleveFed / NY Fed proxy)
    {"id":"EXPINF1YR",            "tier":"B", "transform":"level", "sign":+1, "label":"CleveFed 1y Expected Inflation"},
    # 10y expected inflation
    {"id":"EXPINF10YR",           "tier":"C", "transform":"level", "sign":+1, "label":"CleveFed 10y Expected Inflation"},
    # Market-implied breakevens
    {"id":"T5YIFR",               "tier":"B", "transform":"level", "sign":+1, "label":"5y5y forward TIPS breakeven"},
    {"id":"T5YIE",                "tier":"C", "transform":"level", "sign":+1, "label":"5y TIPS breakeven"},
    {"id":"T10YIE",               "tier":"C", "transform":"level", "sign":+1, "label":"10y TIPS breakeven"},
]

# For entries with 'source_id' (a duplicate transform on the same raw series),
# we want to fetch the source once. Build a mapping.
def _resolve_fetch_ids(specs: list[dict]) -> list[str]:
    ids = []
    seen = set()
    for spec in specs:
        fid = spec.get("source_id", spec["id"])
        if fid not in seen:
            ids.append(fid)
            seen.add(fid)
    return ids


def build():
    print("[INFLATION] fetching series...")
    con = init_cache()

    fetch_ids = _resolve_fetch_ids(HARD_SERIES + SOFT_SERIES)
    raw: dict[str, pd.Series] = {}
    for fid in fetch_ids:
        print(f"  {fid}")
        s = fetch_series(fid, con, required=False)
        if s is not None and not s.empty:
            raw[fid] = s

    def survives(spec):
        fid = spec.get("source_id", spec["id"])
        return fid in raw

    hard_specs = [s for s in HARD_SERIES if survives(s)]
    soft_specs = [s for s in SOFT_SERIES if survives(s)]
    normalise_weights(hard_specs)
    normalise_weights(soft_specs)

    hard_z: dict[str, pd.Series] = {}
    soft_z: dict[str, pd.Series] = {}
    for spec in hard_specs:
        fid = spec.get("source_id", spec["id"])
        z = zscore_36m(raw[fid], spec["transform"]) * spec["sign"]
        hard_z[spec["id"]] = z
    for spec in soft_specs:
        fid = spec.get("source_id", spec["id"])
        z = zscore_36m(raw[fid], spec["transform"]) * spec["sign"]
        soft_z[spec["id"]] = z

    hard_weights = {s["id"]: s["weight_norm"] for s in hard_specs}
    soft_weights = {s["id"]: s["weight_norm"] for s in soft_specs}
    hard_comp = build_composite(hard_z, hard_weights)
    soft_comp = build_composite(soft_z, soft_weights)

    # 40% hard, 60% soft per spec
    idx = hard_comp.index.union(soft_comp.index)
    h = hard_comp.reindex(idx)
    s = soft_comp.reindex(idx)
    num = h.fillna(0) * 0.4 + s.fillna(0) * 0.6
    den = h.notna().astype(float) * 0.4 + s.notna().astype(float) * 0.6
    i_comp = num / den.where(den > 0)
    ihss = h - s

    all_z = {**hard_z, **soft_z}
    br = breadth(all_z)

    labels = {sp["id"]: sp["label"] for sp in hard_specs + soft_specs}

    result = {
        "pillar": "inflation",
        "hard_z": hard_comp,
        "soft_z": soft_comp,
        "composite": i_comp,
        "hss": ihss,
        "breadth": br,
        "component_z": all_z,
        "hard_specs": hard_specs,
        "soft_specs": soft_specs,
        "raw": raw,
        "labels": labels,
    }
    _draw_charts(result)
    return result


def _draw_charts(res: dict):
    if _SKIP_CHARTS:
        return
    tail_days = 365 * 5
    fig, ax = plt.subplots(figsize=(12, 4.5))
    for name, s, col, lw in [
        ("Composite Inflation Z", res["composite"], "#7b341e", 2.2),
        ("Hard sub-Z",            res["hard_z"],   "#c05621", 1.2),
        ("Soft sub-Z",            res["soft_z"],   "#2c5282", 1.2),
    ]:
        s = s.dropna().tail(tail_days)
        if not s.empty:
            ax.plot(s.index, s.values, color=col, linewidth=lw, alpha=0.9, label=name)
    ax.axhline(0, color="black", linewidth=0.8)
    latest = res["composite"].dropna()
    latest_v = latest.iloc[-1] if not latest.empty else float("nan")
    latest_dt = latest.index[-1].date() if not latest.empty else "?"
    ax.set_title(f"INFLATION Z-SCORE  (36m rolling)   Latest composite: {latest_v:+.2f}σ  ({latest_dt})",
                 fontweight="bold")
    ax.set_ylabel("Z-score (σ)")
    ax.set_ylim(-3, 3)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(CHARTS / "inflation_z.png", dpi=120, bbox_inches="tight")
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
                ax.plot(z.index, z.values, color="#7b341e", linewidth=1.2)
                ax.axhline(0, color="black", linewidth=0.5, alpha=0.6)
                ax.fill_between(z.index, z.values, 0, where=(z.values > 0), color="orange", alpha=0.2)
                ax.fill_between(z.index, z.values, 0, where=(z.values < 0), color="blue", alpha=0.15)
                ax.text(0.02, 0.92, f"{z.iloc[-1]:+.2f}σ", transform=ax.transAxes,
                        fontsize=8, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7))
            ax.set_title(spec["label"][:36], fontsize=8)
            ax.set_ylim(-3, 3)
            ax.tick_params(labelsize=7)
            ax.grid(alpha=0.3)
        for j in range(n, len(axes)):
            axes[j].set_visible(False)
        plt.suptitle("Inflation pillar — component Z-scores (36m rolling)", fontweight="bold", y=1.00)
        plt.tight_layout()
        plt.savefig(CHARTS / "inflation_components.png", dpi=110, bbox_inches="tight")
        plt.close()


if __name__ == "__main__":
    r = build()
    latest = r["composite"].dropna()
    print(f"\nInflation composite Z (latest): {latest.iloc[-1]:+.2f}  as of {latest.index[-1].date()}")
    print(f"Hard sub-Z: {r['hard_z'].dropna().iloc[-1]:+.2f}")
    print(f"Soft sub-Z: {r['soft_z'].dropna().iloc[-1]:+.2f}")
    print(f"Breadth: {r['breadth'].dropna().iloc[-1]:.0f}%")
    if SKIPPED:
        print("\nSkipped:")
        for sid, reason in SKIPPED:
            print(f"  {sid}: {reason}")
