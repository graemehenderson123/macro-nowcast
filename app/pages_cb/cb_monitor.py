"""Central Bank Stance Monitor — dedicated page.

Grid of one card per central bank. Phase 1 = Fed with real data; the rest
of G10 render as "Coming soon" placeholders so the roadmap is visible.

Data source: ``app/data/<cb>_stance.json`` snapshots rebuilt nightly by the
`cb_monitor` backend on the workspace host. Do not fetch anything here.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from shared.cb_theme import (
    CB_CSS,
    band_color,
    band_label,
    commentary_label,
    delta_phrase,
    direction_arrow,
    truncate,
)


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Registry — one entry per CB card. Only entries with ``code`` mapped to a
# snapshot file render live; the rest render as placeholders.
# ---------------------------------------------------------------------------
CB_REGISTRY: list[dict] = [
    {"code": "fed",     "label": "FED",       "flag": "🇺🇸", "snapshot": "fed_stance.json", "status": "live"},
    {"code": "ecb",     "label": "ECB",       "flag": "🇪🇺", "snapshot": None, "status": "soon"},
    {"code": "boe",     "label": "BOE",       "flag": "🇬🇧", "snapshot": None, "status": "soon"},
    {"code": "boj",     "label": "BOJ",       "flag": "🇯🇵", "snapshot": None, "status": "soon"},
    {"code": "rba",     "label": "RBA",       "flag": "🇦🇺", "snapshot": None, "status": "soon"},
    {"code": "rbnz",    "label": "RBNZ",      "flag": "🇳🇿", "snapshot": None, "status": "soon"},
    {"code": "boc",     "label": "BOC",       "flag": "🇨🇦", "snapshot": None, "status": "soon"},
    {"code": "snb",     "label": "SNB",       "flag": "🇨🇭", "snapshot": None, "status": "soon"},
    {"code": "riksbank","label": "RIKSBANK",  "flag": "🇸🇪", "snapshot": None, "status": "soon"},
    {"code": "norges",  "label": "NORGES",    "flag": "🇳🇴", "snapshot": None, "status": "soon"},
]


# ---------------------------------------------------------------------------
# Snapshot loader
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60 * 15, show_spinner=False)
def _load_snapshot(filename: str, _cache_bust: str) -> dict | None:
    """Load a CB snapshot JSON. Returns None if missing/broken."""
    path = DATA_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _fourteen_day_delta(history: list[dict]) -> float | None:
    """Current surprise minus surprise 14 days ago (using last available point)."""
    if not history:
        return None
    df = pd.DataFrame(history)
    if "surprise_score" not in df.columns or df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 2:
        return None
    current = float(df["surprise_score"].iloc[-1])
    lookback = df.iloc[-15] if len(df) >= 15 else df.iloc[0]
    prior = float(lookback["surprise_score"])
    return current - prior


def _hex_to_rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    if len(h) != 6:
        return f"rgba(107,114,128,{alpha})"  # neutral fallback
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _sparkline(history: list[dict], colour: str) -> go.Figure:
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").tail(30)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["surprise_score"],
            mode="lines",
            line=dict(color=colour, width=2),
            hovertemplate="%{x|%b %d}<br>surprise=%{y:+.2f}σ<extra></extra>",
            fill="tozeroy",
            fillcolor=_hex_to_rgba(colour, 0.13),
        )
    )
    fig.add_hline(y=0, line=dict(color="#d1d5db", width=1, dash="dot"))
    fig.update_layout(
        height=60,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        xaxis=dict(visible=False, showgrid=False),
        yaxis=dict(visible=False, showgrid=False, zeroline=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


# ---------------------------------------------------------------------------
# Card renderers
# ---------------------------------------------------------------------------
def _render_live_card(cb: dict, snap: dict) -> None:
    surprise = float(snap.get("surprise_score", 0.0))
    commentary = float(snap.get("commentary_score", 0.0))
    n14 = int(snap.get("n_items_14d", 0))
    history = snap.get("history_90d", [])
    movers = snap.get("top_movers", [])

    colour = band_color(surprise)
    b_label = band_label(surprise)

    delta_14d = _fourteen_day_delta(history)
    arrow, arrow_col, arrow_pt = direction_arrow(delta_14d)

    # Header row (name + arrow)
    st.markdown(
        f"""
<div class='cb-card'>
  <div class='cb-header'>
    <span class='cb-name'>{cb['flag']} {cb['label']}</span>
    <span class='cb-arrow' style='color:{arrow_col}; font-size:{arrow_pt}px;'>{arrow}</span>
  </div>
  <div class='cb-big' style='color:{colour};'>{surprise:+.2f}σ</div>
  <div class='cb-band-label' style='color:{colour};'>{b_label}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Sparkline (rendered outside the html because plotly needs a real DOM node)
    if history:
        st.plotly_chart(
            _sparkline(history, colour),
            use_container_width=True,
            config={"displayModeBar": False},
            key=f"spark_{cb['code']}",
        )

    # Direction of travel + absolute score
    if delta_14d is not None:
        delta_txt = f"Δ 14d: {delta_14d:+.2f}σ ({delta_phrase(delta_14d)})"
    else:
        delta_txt = "Δ 14d: —"
    st.markdown(
        f"<div class='cb-delta'>{delta_txt}</div>"
        f"<div class='cb-absolute'>Commentary: {commentary:+.2f} "
        f"({commentary_label(commentary)}) · {n14} items 14d</div>",
        unsafe_allow_html=True,
    )

    # Top 2 movers
    if movers:
        top2 = movers[:2]
        mover_html = ""
        for m in top2:
            speaker = m.get("speaker", "—")
            phrase = truncate(m.get("phrase", "") or "", 60)
            mover_html += (
                f"<div class='cb-mover'>▸ <span class='sp'>{speaker}</span>: "
                f"<span style='color:#4b5563;'>{phrase}</span></div>"
            )
        st.markdown(mover_html, unsafe_allow_html=True)

        with st.expander(f"View all movers ({len(movers)})"):
            rows = []
            for m in movers:
                rows.append({
                    "Date": (m.get("published_at") or "")[:10],
                    "Speaker": m.get("speaker", ""),
                    "Stance": m.get("stance"),
                    "Prior": m.get("prior"),
                    "Surprise": m.get("surprise"),
                    "Weight": m.get("weight"),
                    "Phrase": (m.get("phrase") or "")[:200],
                })
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style.format({
                    "Stance": "{:+.2f}", "Prior": "{:+.2f}",
                    "Surprise": "{:+.2f}", "Weight": "{:.3f}",
                }),
                use_container_width=True,
                hide_index=True,
                height=min(38 * (len(df) + 1) + 10, 320),
            )

    # Reprice-risk banner if |surprise| > 1
    if abs(surprise) > 1.0:
        st.markdown(
            "<div class='cb-banner'>⚠ Market repricing risk — surprise magnitude high</div>",
            unsafe_allow_html=True,
        )


def _render_empty_card(cb: dict) -> None:
    st.markdown(
        f"""
<div class='cb-card empty'>
  <div class='cb-empty-body'>
    <div class='flag'>{cb['flag']}</div>
    <div class='name'>{cb['label']}</div>
    <div class='soon'>Coming soon</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sorting helpers
# ---------------------------------------------------------------------------
def _card_sort_key(entry: dict, mode: str) -> tuple:
    """Return a sort key so live cards sort by data, empty cards go to bottom."""
    snap = entry.get("snap")
    if snap is None:
        # Empty cards: keep original registry order
        return (1, entry["_idx"])

    surprise = float(snap.get("surprise_score", 0.0))
    delta = _fourteen_day_delta(snap.get("history_90d", [])) or 0.0

    if mode == "Surprise magnitude":
        return (0, -abs(surprise))
    if mode == "Direction of travel":
        # Most hawkish delta first
        return (0, -delta)
    # Alphabetical
    return (0, entry["cb"]["label"])


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------
def render() -> None:
    st.markdown(CB_CSS, unsafe_allow_html=True)

    # --- Header ------------------------------------------------------------
    st.title("🦅🕊️ Central Bank Stance Monitor")

    # Determine latest snapshot for the header timestamp
    cache_bust = st.session_state.get("_cb_cache_bust", "v1")
    fed_snap = _load_snapshot("fed_stance.json", cache_bust)
    as_of = (fed_snap or {}).get("as_of", "") if fed_snap else ""
    as_of_str = as_of[:16].replace("T", " ") + " UTC" if as_of else "—"

    st.caption(
        f"Speaker-relative hawk/dove tracking across G10 central banks. "
        f"Last updated: **{as_of_str}**"
    )

    with st.expander("How to read this dashboard"):
        st.markdown(
            """
**What it shows.** For each central bank, we score every speaker headline
(prepared speech, minutes, off-the-cuff) on a −5 (ultra-dovish) to +5
(ultra-hawkish) scale using a small LLM, then aggregate with these weights:

- **Speaker weight:** Chair 1.0 → Vice/Deputy 0.7 → Voting member 0.6 → Non-voter 0.4.
- **Event weight:** Prepared speech 1.0 → Off-the-cuff 0.75 → Minutes 0.5.
- **Recency:** 7-day exponential half-life over the trailing 14 days.

**Big number.** The `surprise_score` (in σ) — current stance vs each speaker's
own 60-day rolling mean. This is the *primary* trading signal: it flags "Fed
member X sounded more hawkish/dovish than usual", which is where markets
actually reprice.

**Colour bands.**
`< −1.5σ` deep green (very dovish) · `−1.5…−0.5` green (dovish) ·
`−0.5…+0.5` grey (neutral) · `+0.5…+1.5` red (hawkish) · `> +1.5σ` deep red
(very hawkish).

**Direction of travel.** Arrow + `Δ 14d` compare current surprise to
14 days ago. Rising = drifting more hawkish; falling = drifting more dovish.

**Absolute score.** The `commentary_score` (unadjusted stance, ±5) — useful
to know whether the CB is *hawkish at all* vs just hawkish *for them*.

**Banner.** When `|surprise| > 1.0σ` we flag repricing risk — historically
where curves and FX pairs have moved most.
            """
        )

    # --- Controls ----------------------------------------------------------
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        sort_mode = st.selectbox(
            "Sort by",
            ["Surprise magnitude", "Direction of travel", "Alphabetical"],
            index=0,
        )
    with c2:
        only_big = st.toggle("Show only |surprise| > 1σ", value=False)
    with c3:
        if st.button("↻ Refresh", use_container_width=True):
            # bump cache bust so @st.cache_data misses
            st.session_state["_cb_cache_bust"] = datetime.now(timezone.utc).isoformat()
            st.rerun()

    # --- Build card list ---------------------------------------------------
    entries: list[dict] = []
    for idx, cb in enumerate(CB_REGISTRY):
        snap = None
        if cb.get("snapshot"):
            snap = _load_snapshot(cb["snapshot"], cache_bust)
        entries.append({"cb": cb, "snap": snap, "_idx": idx})

    # Optional filter — only affects live cards; empty stay hidden if toggled
    def _keep(e: dict) -> bool:
        if not only_big:
            return True
        snap = e["snap"]
        if snap is None:
            return False
        return abs(float(snap.get("surprise_score", 0.0))) > 1.0

    entries = [e for e in entries if _keep(e)]
    entries.sort(key=lambda e: _card_sort_key(e, sort_mode))

    if not entries:
        st.info("No central banks match the current filter.")
        return

    # --- Grid --------------------------------------------------------------
    # Phone-ish widths get 1 column; wider gets 3.
    # Streamlit doesn't tell us the viewport width; use 3-up desktop layout and
    # rely on the browser wrapping cards vertically on narrow screens.
    per_row = 3
    for row_start in range(0, len(entries), per_row):
        row = entries[row_start : row_start + per_row]
        cols = st.columns(per_row, gap="small")
        for col, entry in zip(cols, row):
            with col:
                cb = entry["cb"]
                snap = entry["snap"]
                if snap is None:
                    _render_empty_card(cb)
                else:
                    _render_live_card(cb, snap)
        # Fill trailing empty slots so the last row keeps consistent width
        for col in cols[len(row):]:
            with col:
                st.markdown("<div style='height:1px'></div>", unsafe_allow_html=True)

    # --- Footer ------------------------------------------------------------
    st.markdown(
        "<div style='color:#9ca3af;font-size:11px;margin-top:24px;'>"
        "Source: Newsquawk speaker headlines, LLM-classified via cb_monitor backend. "
        "Snapshots rebuilt nightly. Non-Fed CBs on the roadmap — Phase 2."
        "</div>",
        unsafe_allow_html=True,
    )
