"""US country page — reuses the engines in ``nowcast/us/``."""
from __future__ import annotations
import datetime as dt
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# Make the country engines importable BEFORE we import them.
import shared.engines  # noqa: F401  (side-effect: adds nowcast/us to sys.path)

# Skip matplotlib chart writes — the app uses plotly.
os.environ.setdefault("NOWCAST_SKIP_CHARTS", "1")

from shared import charts as C
from shared.theme import (
    GLOBAL_CSS, REGIME_COLORS, REGIME_DESCRIPTIONS, TIME_RANGES,
    NAVY, TEAL, BRICK, ORANGE, GREEN,
    stat_card, fmt_z, z_class,
)

# Engine imports — resolved via shared.engines side-effect.
import liquidity_pillar    # type: ignore
import growth_phase2       # type: ignore
import inflation_phase2    # type: ignore
import regime_phase3       # type: ignore
from nowcast_core import SKIPPED  # type: ignore


# ---------------------------------------------------------------------------
# Cached build. Cache for 8 hours so weekly series refresh, but daily series
# still catch overnight updates.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=8 * 3600, show_spinner=False)
def _build_all(cache_bust: str):
    """Run all pillars + regime. cache_bust is a rebuild sentinel."""
    l_res = liquidity_pillar.build()
    g_res = growth_phase2.build()
    i_res = inflation_phase2.build()
    regime = regime_phase3.compute_regime(g_res, i_res, l_res)
    return l_res, g_res, i_res, regime, list(SKIPPED)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _latest(s: pd.Series):
    ss = s.dropna()
    if ss.empty:
        return (float("nan"), None)
    return (float(ss.iloc[-1]), ss.index[-1])


def _z_4w_ago(s: pd.Series) -> float:
    ss = s.dropna()
    if len(ss) < 5:
        return float("nan")
    target = ss.index[-1] - pd.Timedelta(days=28)
    idx = ss.index[ss.index <= target]
    if len(idx) == 0:
        return float("nan")
    return float(ss.loc[idx[-1]])


def _staleness(res: dict, spec: dict) -> str:
    sid = spec.get("source_id", spec["id"])
    raw = res.get("raw", {}).get(sid)
    if raw is None or raw.empty:
        return "—"
    return raw.dropna().index[-1].strftime("%Y-%m-%d")


def _movers(res: dict, n: int = 5) -> list[dict]:
    z_now = {sid: _latest(s)[0] for sid, s in res["component_z"].items()}
    z_prev = {sid: _z_4w_ago(s) for sid, s in res["component_z"].items()}
    rows = []
    for k, now in z_now.items():
        if math.isnan(now):
            continue
        prev = z_prev.get(k, float("nan"))
        chg = now - prev if not math.isnan(prev) else float("nan")
        if math.isnan(chg):
            continue
        rows.append({"id": k, "label": res["labels"].get(k, k),
                     "z_now": now, "z_prev": prev, "chg": chg})
    rows.sort(key=lambda r: abs(r["chg"]), reverse=True)
    return rows[:n]


def _stat_row(cards: list[str]):
    """Render a row of stat cards using Streamlit columns."""
    cols = st.columns(len(cards))
    for c, html in zip(cols, cards):
        with c:
            st.markdown(html, unsafe_allow_html=True)


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.0f}%"


# ---------------------------------------------------------------------------
# Renderers per pillar
# ---------------------------------------------------------------------------
def _render_regime(regime: dict, g_res: dict, i_res: dict, l_res: dict, tail_days: int | None):
    label = regime["regime"]
    desc = REGIME_DESCRIPTIONS.get(label, "")
    color = REGIME_COLORS.get(label, "#666")
    liq_mod = regime.get("liq_mod") or "—"
    days_in = regime.get("days_in_regime")
    since = regime.get("since")
    since_str = since.date().isoformat() if isinstance(since, (pd.Timestamp,)) else "?"

    g_z, _ = _latest(g_res["composite"])
    i_z, _ = _latest(i_res["composite"])
    l_z, _ = _latest(l_res["composite"])
    g_br, _ = _latest(g_res["breadth"])
    i_br, _ = _latest(i_res["breadth"])
    l_br, _ = _latest(l_res["breadth"])

    st.markdown(
        f"""<div class='nc-regime-card' style='background: linear-gradient(135deg, {color}22, {color}0a); border-left: 6px solid {color};'>
  <div class='nc-regime-eyebrow'>Current regime</div>
  <div class='nc-regime-label' style='color:{color}'>{label}</div>
  <div class='nc-regime-sub'>{desc}</div>
  <div class='nc-regime-sub' style='margin-top:6px;'>
    <strong>Liquidity modifier:</strong> {liq_mod}
    {f" · in this regime for <strong>{days_in} days</strong>" if days_in is not None else ""}
    {f" (since {since_str})" if since is not None else ""}
  </div>
</div>""",
        unsafe_allow_html=True,
    )

    _stat_row([
        stat_card("Growth Z", fmt_z(g_z), f"breadth {_fmt_pct(g_br)}", z=g_z),
        stat_card("Inflation Z", fmt_z(i_z), f"breadth {_fmt_pct(i_br)}", z=i_z),
        stat_card("Liquidity Z", fmt_z(l_z), f"breadth {_fmt_pct(l_br)}", z=l_z),
    ])

    st.plotly_chart(
        C.three_pillar_history(g_res["composite"], i_res["composite"], l_res["composite"], tail_days=tail_days),
        use_container_width=True,
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        st.plotly_chart(C.regime_grid_scatter(g_z, i_z), use_container_width=True)
    with col2:
        st.plotly_chart(C.regime_strip(regime["history"], months=24), use_container_width=True)


def _render_movers_table(movers: list[dict]):
    if not movers:
        st.caption("No movers data.")
        return
    df = pd.DataFrame(movers)[["label", "z_prev", "z_now", "chg"]]
    df.columns = ["Series", "4w ago", "Now", "Δ (σ)"]
    st.dataframe(
        df.style
          .format({"4w ago": "{:+.2f}σ", "Now": "{:+.2f}σ", "Δ (σ)": "{:+.2f}σ"})
          .map(lambda v: "color:#2c7a7b;font-weight:600" if isinstance(v, (int, float)) and v > 0.25
                        else ("color:#c0392b;font-weight:600" if isinstance(v, (int, float)) and v < -0.25 else ""),
               subset=["4w ago", "Now", "Δ (σ)"]),
        use_container_width=True,
        hide_index=True,
    )


def _render_components(res: dict, tail_days: int | None, pillar_color: str, key_prefix: str):
    """Component-level drill-down: table + sparklines + raw-series charts."""
    all_specs = res["hard_specs"] + res["soft_specs"]
    rows = []
    for spec in all_specs:
        sid = spec["id"]
        zv, _ = _latest(res["component_z"].get(sid, pd.Series(dtype=float)))
        sub = "Hard" if spec in res["hard_specs"] else "Soft"
        rows.append({
            "Sub": sub,
            "Series": spec["label"],
            "Transform": spec["transform"],
            "Sign": "+" if spec["sign"] > 0 else "−",
            "Weight": spec.get("weight_norm", 0) * 100,
            "Z": zv,
            "Last obs": _staleness(res, spec),
            "_id": sid,
            "_label": spec["label"],
        })
    df = pd.DataFrame(rows)

    st.markdown("#### All components")
    display = df.drop(columns=["_id", "_label"]).copy()
    st.dataframe(
        display.style
              .format({"Weight": "{:.1f}%", "Z": "{:+.2f}σ"})
              .map(lambda v: "color:#2c7a7b;font-weight:600" if isinstance(v, (int, float)) and v > 0.25
                            else ("color:#c0392b;font-weight:600" if isinstance(v, (int, float)) and v < -0.25 else ""),
                   subset=["Z"]),
        use_container_width=True,
        hide_index=True,
        height=min(38 * (len(display) + 1) + 10, 420),
    )

    st.markdown("#### Component Z-score charts")
    # 3 charts per row
    per_row = 3
    for i in range(0, len(all_specs), per_row):
        cols = st.columns(per_row)
        for j, spec in enumerate(all_specs[i:i + per_row]):
            with cols[j]:
                z = res["component_z"].get(spec["id"], pd.Series(dtype=float))
                st.plotly_chart(
                    C.component_z_chart(z, spec["label"], color=pillar_color, tail_days=tail_days, height=220),
                    use_container_width=True,
                    key=f"{key_prefix}_{spec['id']}",
                )

    # Raw underlying series (kept flat — Streamlit forbids nesting expanders,
            # and this section already lives inside the “All components” expander)
    st.markdown("---")
    st.markdown("#### Raw underlying series (pre-transform, pre-Z)")
    options = [(s["label"], s.get("source_id", s["id"])) for s in all_specs]
    picked = st.multiselect(
        "Pick series to inspect",
        [o[0] for o in options],
        key=f"{key_prefix}_raw_select",
    )
    for lbl in picked:
        fid = dict(options)[lbl]
        raw = res.get("raw", {}).get(fid)
        if raw is not None and not raw.empty:
            st.plotly_chart(
                C.raw_series_chart(raw, lbl, color=pillar_color, tail_days=tail_days, height=260),
                use_container_width=True,
                key=f"{key_prefix}_raw_{fid}",
            )


def _render_pillar(
    name: str, emoji: str, res: dict, tail_days: int | None,
    color: str, notes: str = "",
    show_hss: bool = True,
    hard_label: str = "Hard sub-Z", soft_label: str = "Soft sub-Z",
    hard_meta: str = "", soft_meta: str = "",
    key_prefix: str = "",
):
    z, _ = _latest(res["composite"])
    hard, _ = _latest(res["hard_z"])
    soft, _ = _latest(res["soft_z"])
    hss, _ = _latest(res["hss"]) if res.get("hss") is not None else (float("nan"), None)
    br, _ = _latest(res["breadth"])

    header_cls = z_class(z)
    header_color = {"pos": "#2c7a7b", "neg": "#c0392b", "neu": "#555"}[header_cls]
    st.markdown(
        f"<div style='display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;'>"
        f"<h2 style='margin:0;'>{emoji} {name}</h2>"
        f"<div style='font-size:26px;font-weight:800;color:{header_color};'>{fmt_z(z)}</div>"
        f"<div style='color:#666;font-size:12px;'>breadth {_fmt_pct(br)}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if notes:
        st.caption(notes)

    cards = [
        stat_card(hard_label, fmt_z(hard), hard_meta, z=hard),
        stat_card(soft_label, fmt_z(soft), soft_meta, z=soft),
    ]
    if show_hss:
        cards.append(stat_card("Hard-Soft spread", fmt_z(hss), "+ve = hard > soft", z=hss))
    cards.append(stat_card("Breadth", _fmt_pct(br), "% components positive"))
    _stat_row(cards)

    st.plotly_chart(
        C.pillar_z_chart(
            res["composite"], res["hard_z"], res["soft_z"],
            labels=("Composite Z", hard_label, soft_label),
            colors=(color, TEAL, BRICK),
            tail_days=tail_days, height=340,
        ),
        use_container_width=True,
        key=f"{key_prefix}_headline",
    )

    st.markdown("#### Top 5 movers (vs 4 weeks ago)")
    _render_movers_table(_movers(res, n=5))

    with st.expander(f"All components ({len(res['hard_specs']) + len(res['soft_specs'])}) — drill-down"):
        _render_components(res, tail_days=tail_days, pillar_color=color, key_prefix=key_prefix)


# ---------------------------------------------------------------------------
# Page entry
# ---------------------------------------------------------------------------
def render():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    # Sidebar controls
    with st.sidebar:
        st.markdown("### View controls")
        range_label = st.radio(
            "Time range",
            list(TIME_RANGES.keys()),
            index=list(TIME_RANGES.keys()).index("5y"),
            horizontal=True,
        )
        tail_days = TIME_RANGES[range_label]

        st.markdown("---")
        st.markdown("### Data")
        force_rebuild = st.button("🔄 Force rebuild from FRED", use_container_width=True,
                                   help="Wipes both the in-memory cache AND the on-disk SQLite cache, then re-fetches every series from FRED.")
        if force_rebuild:
            # 1. Clear Streamlit's in-memory cache
            _build_all.clear()
            # 2. Wipe the SQLite disk cache so nowcast_core actually re-hits FRED
            #    (otherwise its own 24h TTL keeps serving stale rows).
            try:
                import nowcast_core  # type: ignore
                db_path = Path(nowcast_core.__file__).parent / "fred_cache.sqlite"
                if db_path.exists():
                    db_path.unlink()
                    st.toast(f"Cleared SQLite cache ({db_path.name}) \u2014 next build will re-hit FRED for every series.", icon="🗑️")
            except Exception as e:
                st.warning(f"Could not clear SQLite cache: {e}")
            st.rerun()

    # Cache-bust: manual rebuilds clear cache above; otherwise cache handles TTL.
    cache_bust = "v1"

    with st.spinner("Loading pillars from FRED cache…"):
        try:
            l_res, g_res, i_res, regime, skipped = _build_all(cache_bust)
        except Exception as e:
            st.error(f"Failed to build pillars: {e}")
            st.stop()

    # Header
    now = dt.datetime.utcnow()
    st.markdown(
        f"<div style='color:#666;font-size:12px;'>"
        f"US macro nowcast · built <strong>{now.strftime('%Y-%m-%d %H:%M')} UTC</strong>"
        f" · FRED source · Z-scores 36-month rolling"
        f" · showing <strong>{range_label}</strong>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Regime headline
    _render_regime(regime, g_res, i_res, l_res, tail_days=tail_days)

    st.markdown("---")

    # Pillars
    _render_pillar(
        "Growth", "🏭", g_res, tail_days=tail_days, color=TEAL,
        hard_meta="realised activity", soft_meta="surveys · sentiment",
        key_prefix="growth",
    )
    st.markdown("---")

    _render_pillar(
        "Inflation", "🔥", i_res, tail_days=tail_days, color=ORANGE,
        hard_meta="CPI · PCE · PPI · wages", soft_meta="expectations · prices paid",
        key_prefix="inflation",
    )
    st.markdown("---")

    # Liquidity — has hard=Fed, soft=Market, plus optional net-fed chart
    _render_pillar(
        "Liquidity", "💧", l_res, tail_days=tail_days, color=NAVY,
        hard_label="Fed sub-Z", soft_label="Market sub-Z",
        hard_meta="balance sheet flow", soft_meta="credit · vol · rates",
        key_prefix="liquidity",
    )
    if l_res.get("net_fed_liquidity") is not None:
        st.plotly_chart(
            C.net_fed_liquidity_chart(l_res["net_fed_liquidity"], tail_days=tail_days),
            use_container_width=True,
        )

    # Footer
    st.markdown("---")
    footer_parts = [
        "Built per <code>memory/macro/nowcast/us/INDICATOR-WEIGHTS.md</code>.",
        "Data: FRED (cached in <code>fred_cache.sqlite</code>, TTL 24h per series).",
    ]
    if skipped:
        skipped_list = "<br>".join(f"• <code>{sid}</code> — {reason[:120]}" for sid, reason in skipped)
        footer_parts.append(f"<strong>Skipped series ({len(skipped)}):</strong><br>{skipped_list}")
    st.markdown(
        f"<div class='nc-footer'>{'<br>'.join(footer_parts)}</div>",
        unsafe_allow_html=True,
    )
