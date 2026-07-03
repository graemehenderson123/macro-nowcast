#!/usr/bin/env python3
"""US Nowcast — full build (Liquidity + Growth + Inflation + Regime).

Runs all three pillars, computes regime, writes combined dashboard.html.
Usage: `python3 build_all.py`
"""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import pandas as pd
import numpy as np

from nowcast_core import (
    CHARTS, SKIPPED, z_color_class, fmt_z, top_movers, CSS,
)
import liquidity_pillar
import growth_phase2
import inflation_phase2
import regime_phase3

ROOT = Path(__file__).parent
OUT_HTML = ROOT / "dashboard.html"

REGIME_DESCRIPTIONS = {
    "Overheating":         "Growth strong + inflation rising — late-cycle reflation.",
    "Goldilocks":          "Growth strong + inflation cooling — disinflationary expansion.",
    "Stagflation":         "Growth weak + inflation rising — worst mix for risk assets.",
    "Deflation/Recession": "Growth weak + inflation falling — classic recession.",
    "Reflation":           "Growth accelerating with inflation neutral — early expansion.",
    "Slowdown":            "Growth decelerating with inflation neutral — late cycle cooling.",
    "Disinflation":        "Growth neutral with inflation falling — soft landing tone.",
    "Neutral":             "Both Growth and Inflation near trend — no strong regime signal.",
    "Unknown":              "Insufficient data.",
}

REGIME_COLORS = regime_phase3.REGIME_COLORS


def _latest(s: pd.Series):
    ss = s.dropna()
    if ss.empty:
        return (float("nan"), None)
    return (float(ss.iloc[-1]), ss.index[-1])


def _z_4w_ago(s: pd.Series):
    ss = s.dropna()
    if len(ss) < 5:
        return float("nan")
    target = ss.index[-1] - pd.Timedelta(days=28)
    idx = ss.index[ss.index <= target]
    if len(idx) == 0:
        return float("nan")
    return float(ss.loc[idx[-1]])


def _movers_table(res: dict, n: int = 5):
    z_now = {sid: _latest(s)[0] for sid, s in res["component_z"].items()}
    z_prev = {sid: _z_4w_ago(s) for sid, s in res["component_z"].items()}
    return top_movers(z_now, z_prev, res["labels"], n=n)


def _staleness(res: dict, spec: dict) -> str:
    """Return last observation date of the underlying series as YYYY-MM-DD."""
    sid = spec.get("source_id", spec["id"])
    raw = res.get("raw", {}).get(sid)
    if raw is None or raw.empty:
        return "—"
    return raw.dropna().index[-1].strftime("%Y-%m-%d")


def _pillar_component_rows(res: dict):
    """HTML rows listing every component with weight, current Z, staleness."""
    rows = []
    for sub_name, specs in (("Hard", res["hard_specs"]), ("Soft", res["soft_specs"])):
        for spec in specs:
            z_series = res["component_z"].get(spec["id"], pd.Series(dtype=float))
            zv, zdt = _latest(z_series)
            cls = z_color_class(zv)
            rows.append(
                f"<tr><td>{sub_name}</td><td>{spec['label']}</td>"
                f"<td class='num'>{spec.get('weight_norm', 0)*100:.1f}%</td>"
                f"<td class='num {cls}'>{fmt_z(zv)}</td>"
                f"<td class='num stale'>{_staleness(res, spec)}</td></tr>"
            )
    return "\n".join(rows)


def _movers_html(movers, res):
    if not movers:
        return "<tr><td colspan='4'>No movers data.</td></tr>"
    rows = []
    for m in movers:
        cls = z_color_class(m["chg"])
        rows.append(
            f"<tr><td>{m['label']}</td>"
            f"<td class='num'>{fmt_z(m['z_prev'])}</td>"
            f"<td class='num'>{fmt_z(m['z_now'])}</td>"
            f"<td class='num {cls}'>{m['chg']:+.2f}σ</td></tr>"
        )
    return "\n".join(rows)


def render_dashboard(l_res: dict, g_res: dict, i_res: dict, regime: dict):
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    g_z, _ = _latest(g_res["composite"])
    g_hard, _ = _latest(g_res["hard_z"])
    g_soft, _ = _latest(g_res["soft_z"])
    g_hss, _ = _latest(g_res["hss"])
    g_breadth, _ = _latest(g_res["breadth"])

    i_z, _ = _latest(i_res["composite"])
    i_hard, _ = _latest(i_res["hard_z"])
    i_soft, _ = _latest(i_res["soft_z"])
    i_hss, _ = _latest(i_res["hss"])
    i_breadth, _ = _latest(i_res["breadth"])

    l_z, _ = _latest(l_res["composite"])
    l_hard, _ = _latest(l_res["hard_z"])
    l_soft, _ = _latest(l_res["soft_z"])
    l_breadth, _ = _latest(l_res["breadth"])
    net_fed = None
    if l_res.get("net_fed_liquidity") is not None:
        nfv, nfd = _latest(l_res["net_fed_liquidity"])
        net_fed = (nfv, nfd)

    regime_label = regime["regime"]
    regime_desc = REGIME_DESCRIPTIONS.get(regime_label, "")
    regime_color = REGIME_COLORS.get(regime_label, "#666")
    liq_mod = regime["liq_mod"]
    days_in = regime.get("days_in_regime")
    since = regime.get("since")

    # Movers tables
    g_movers = _movers_html(_movers_table(g_res), g_res)
    i_movers = _movers_html(_movers_table(i_res), i_res)
    l_movers = _movers_html(_movers_table(l_res), l_res)

    # Skipped list
    skipped_html = ""
    if SKIPPED:
        skipped_html = "<ul>" + "".join(
            f"<li><code>{sid}</code> — {reason}</li>" for sid, reason in SKIPPED
        ) + "</ul>"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>US Nowcast — Full Dashboard</title>
<style>{CSS}</style>
</head>
<body>

<h1>US Macro Nowcast — Regime · Growth · Inflation · Liquidity</h1>
<div class="sub">Built {ts} UTC · Source: FRED · Z-scores 36m rolling. Composite regime updates daily.</div>

<!-- ================= REGIME HEADLINE ================= -->
<div class="card regime-card" style="background: linear-gradient(135deg, {regime_color}22, {regime_color}11); border-left: 6px solid {regime_color};">
  <div style="display:flex; align-items:baseline; gap:20px; flex-wrap:wrap;">
    <div>
      <div style="font-size:11px; color:#666; text-transform:uppercase; letter-spacing:1px;">Current regime</div>
      <div class="regime-label" style="color:{regime_color}">{regime_label}</div>
      <div class="regime-sub">{regime_desc}</div>
      <div class="regime-sub" style="margin-top:6px;"><strong>Liquidity modifier:</strong> {liq_mod or '—'}
        {f' · in this regime for <strong>{days_in} days</strong>' if days_in is not None else ''}
        {f' (since {since.date() if since else "?"})' if since is not None else ''}
      </div>
    </div>
    <div style="flex:1"></div>
    <div style="display:flex; gap:12px; flex-wrap:wrap;">
      <div class="stat {z_color_class(g_z)}"><div class="label">Growth Z</div><div class="value">{fmt_z(g_z)}</div><div class="meta">breadth {g_breadth:.0f}%</div></div>
      <div class="stat {z_color_class(i_z)}"><div class="label">Inflation Z</div><div class="value">{fmt_z(i_z)}</div><div class="meta">breadth {i_breadth:.0f}%</div></div>
      <div class="stat {z_color_class(l_z)}"><div class="label">Liquidity Z</div><div class="value">{fmt_z(l_z)}</div><div class="meta">breadth {l_breadth:.0f}%</div></div>
    </div>
  </div>
</div>

<div class="card">
  <h2>Regime Detail</h2>
  <div style="display:grid; grid-template-columns: 1fr 1fr; gap:24px; align-items:start;">
    <div><img src="charts/regime_grid.png"></div>
    <div><img src="charts/pillar_z_history.png"></div>
  </div>
  <div style="margin-top:16px;"><img src="charts/regime_strip.png"></div>
</div>

<!-- ================= GROWTH ================= -->
<div class="card">
  <div class="pillar-h"><h1>🏭 Growth</h1><div class="z {z_color_class(g_z)}">{fmt_z(g_z)}</div></div>
  <div class="grid" style="margin-top:12px;">
    <div class="stat {z_color_class(g_hard)}"><div class="label">Hard sub-Z</div><div class="value">{fmt_z(g_hard)}</div><div class="meta">realised activity</div></div>
    <div class="stat {z_color_class(g_soft)}"><div class="label">Soft sub-Z</div><div class="value">{fmt_z(g_soft)}</div><div class="meta">surveys · sentiment</div></div>
    <div class="stat {z_color_class(g_hss)}"><div class="label">Hard-Soft spread</div><div class="value">{fmt_z(g_hss)}</div><div class="meta">+ve = hard > soft</div></div>
    <div class="stat"><div class="label">Breadth</div><div class="value">{g_breadth:.0f}%</div><div class="meta">of components positive</div></div>
  </div>
  <img src="charts/growth_z.png" style="margin-top:12px;">
  <h2 style="margin-top:16px;">Top 5 movers (vs 4 weeks ago)</h2>
  <table>
    <thead><tr><th>Series</th><th class="num">4w ago</th><th class="num">Now</th><th class="num">Δ</th></tr></thead>
    <tbody>{g_movers}</tbody>
  </table>
  <details style="margin-top:12px;"><summary style="cursor:pointer;color:#666;">All components ({len(g_res['hard_specs']) + len(g_res['soft_specs'])})</summary>
    <table>
      <thead><tr><th>Sub</th><th>Series</th><th class="num">Weight</th><th class="num">Z</th><th class="num">Last obs</th></tr></thead>
      <tbody>{_pillar_component_rows(g_res)}</tbody>
    </table>
  </details>
  <img src="charts/growth_components.png" style="margin-top:12px;">
</div>

<!-- ================= INFLATION ================= -->
<div class="card">
  <div class="pillar-h"><h1>🔥 Inflation</h1><div class="z {z_color_class(i_z)}">{fmt_z(i_z)}</div></div>
  <div class="grid" style="margin-top:12px;">
    <div class="stat {z_color_class(i_hard)}"><div class="label">Hard sub-Z</div><div class="value">{fmt_z(i_hard)}</div><div class="meta">CPI · PCE · PPI · wages</div></div>
    <div class="stat {z_color_class(i_soft)}"><div class="label">Soft sub-Z</div><div class="value">{fmt_z(i_soft)}</div><div class="meta">expectations · prices paid</div></div>
    <div class="stat {z_color_class(i_hss)}"><div class="label">Hard-Soft spread</div><div class="value">{fmt_z(i_hss)}</div><div class="meta">+ve = de-anchoring risk</div></div>
    <div class="stat"><div class="label">Breadth</div><div class="value">{i_breadth:.0f}%</div><div class="meta">of components positive</div></div>
  </div>
  <img src="charts/inflation_z.png" style="margin-top:12px;">
  <h2 style="margin-top:16px;">Top 5 movers</h2>
  <table>
    <thead><tr><th>Series</th><th class="num">4w ago</th><th class="num">Now</th><th class="num">Δ</th></tr></thead>
    <tbody>{i_movers}</tbody>
  </table>
  <details style="margin-top:12px;"><summary style="cursor:pointer;color:#666;">All components ({len(i_res['hard_specs']) + len(i_res['soft_specs'])})</summary>
    <table>
      <thead><tr><th>Sub</th><th>Series</th><th class="num">Weight</th><th class="num">Z</th><th class="num">Last obs</th></tr></thead>
      <tbody>{_pillar_component_rows(i_res)}</tbody>
    </table>
  </details>
  <img src="charts/inflation_components.png" style="margin-top:12px;">
</div>

<!-- ================= LIQUIDITY ================= -->
<div class="card">
  <div class="pillar-h"><h1>💧 Liquidity</h1><div class="z {z_color_class(l_z)}">{fmt_z(l_z)}</div></div>
  <div class="grid" style="margin-top:12px;">
    <div class="stat {z_color_class(l_hard)}"><div class="label">Fed sub-Z</div><div class="value">{fmt_z(l_hard)}</div><div class="meta">balance sheet flow</div></div>
    <div class="stat {z_color_class(l_soft)}"><div class="label">Market sub-Z</div><div class="value">{fmt_z(l_soft)}</div><div class="meta">credit · vol · rates</div></div>
    {f'<div class="stat"><div class="label">Net Fed liquidity</div><div class="value">${net_fed[0]:,.0f}bn</div><div class="meta">WALCL − TGA − RRP · {net_fed[1].date()}</div></div>' if net_fed else ''}
    <div class="stat"><div class="label">Breadth</div><div class="value">{l_breadth:.0f}%</div><div class="meta">of components positive</div></div>
  </div>
  <img src="charts/liquidity_z.png" style="margin-top:12px;">
  {"<img src='charts/net_fed_liquidity.png' style='margin-top:12px;'>" if net_fed else ""}
  <h2 style="margin-top:16px;">Top 5 movers</h2>
  <table>
    <thead><tr><th>Series</th><th class="num">4w ago</th><th class="num">Now</th><th class="num">Δ</th></tr></thead>
    <tbody>{l_movers}</tbody>
  </table>
  <details style="margin-top:12px;"><summary style="cursor:pointer;color:#666;">All components ({len(l_res['hard_specs']) + len(l_res['soft_specs'])})</summary>
    <table>
      <thead><tr><th>Sub</th><th>Series</th><th class="num">Weight</th><th class="num">Z</th><th class="num">Last obs</th></tr></thead>
      <tbody>{_pillar_component_rows(l_res)}</tbody>
    </table>
  </details>
  <img src="charts/liquidity_components.png" style="margin-top:12px;">
</div>

<div class="footer">
  Built per <code>memory/macro/nowcast/us/INDICATOR-WEIGHTS.md</code>.<br>
  Rebuild: <code>cd nowcast/us && python3 build_all.py</code>.<br>
  Data: FRED (cached 24h in <code>fred_cache.sqlite</code>).<br>
  {f"<strong>Skipped series ({len(SKIPPED)}):</strong>{skipped_html}" if SKIPPED else ""}
</div>

</body>
</html>
"""
    OUT_HTML.write_text(html)
    print(f"[dashboard] {OUT_HTML}")


def main():
    print("=" * 70)
    print("US NOWCAST — full build (Liquidity + Growth + Inflation + Regime)")
    print("=" * 70)

    l_res = liquidity_pillar.build()
    g_res = growth_phase2.build()
    i_res = inflation_phase2.build()

    regime = regime_phase3.compute_regime(g_res, i_res, l_res)

    render_dashboard(l_res, g_res, i_res, regime)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Regime:      {regime['regime']}  ({regime['liq_mod']})")
    print(f"  as of:     {regime['as_of'].date()}")
    if regime.get('since'):
        print(f"  since:     {regime['since'].date()} ({regime['days_in_regime']} days)")
    print(f"Growth Z:    {regime['g']:+.2f}   breadth {_latest(g_res['breadth'])[0]:.0f}%")
    print(f"Inflation Z: {regime['i']:+.2f}   breadth {_latest(i_res['breadth'])[0]:.0f}%")
    print(f"Liquidity Z: {regime['l']:+.2f}   breadth {_latest(l_res['breadth'])[0]:.0f}%")
    if SKIPPED:
        print(f"\nSkipped {len(SKIPPED)} series:")
        for sid, reason in SKIPPED:
            print(f"  {sid}: {reason[:80]}")
    print(f"\nDashboard: {OUT_HTML}")


if __name__ == "__main__":
    main()
