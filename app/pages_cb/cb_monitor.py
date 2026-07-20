"""Central Bank Stance Monitor — dedicated page.

Grid of one card per central bank. Phase 1 = Fed, Phase 2 = full G10,
Phase 3 (cb-monitor-em-15) = G10 + 15 EM CBs, grouped by region.

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
    commentary_band_label,
    commentary_color,
    truncate,
)


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Registry — one entry per CB card. Only entries with ``code`` mapped to a
# snapshot file render live; the rest render as placeholders.
# ---------------------------------------------------------------------------
# Groups (G10 first, then EM by region). Order within each group is
# adjusted by the sort selector at runtime.
CB_REGISTRY: list[dict] = [
    # ---- G10 ----
    {"code": "fed",     "label": "FED",       "flag": "🇺🇸", "snapshot": "fed_stance.json",      "status": "live", "group": "G10"},
    {"code": "ecb",     "label": "ECB",       "flag": "🇪🇺", "snapshot": "ecb_stance.json",      "status": "live", "group": "G10"},
    {"code": "boe",     "label": "BOE",       "flag": "🇬🇧", "snapshot": "boe_stance.json",      "status": "live", "group": "G10"},
    {"code": "boj",     "label": "BOJ",       "flag": "🇯🇵", "snapshot": "boj_stance.json",      "status": "live", "group": "G10"},
    {"code": "rba",     "label": "RBA",       "flag": "🇦🇺", "snapshot": "rba_stance.json",      "status": "live", "group": "G10"},
    {"code": "rbnz",    "label": "RBNZ",      "flag": "🇳🇿", "snapshot": "rbnz_stance.json",     "status": "live", "group": "G10"},
    {"code": "boc",     "label": "BOC",       "flag": "🇨🇦", "snapshot": "boc_stance.json",      "status": "live", "group": "G10"},
    {"code": "snb",     "label": "SNB",       "flag": "🇨🇭", "snapshot": "snb_stance.json",      "status": "live", "group": "G10"},
    {"code": "riksbank","label": "RIKSBANK",  "flag": "🇸🇪", "snapshot": "riksbank_stance.json", "status": "live", "group": "G10"},
    {"code": "norges",  "label": "NORGES",    "flag": "🇳🇴", "snapshot": "norges_stance.json",   "status": "live", "group": "G10"},
    # ---- EM Asia ----
    {"code": "cnh",     "label": "CNH · PBOC",   "flag": "🇨🇳", "snapshot": "cnh_stance.json",  "status": "live", "group": "EM Asia"},
    {"code": "krw",     "label": "KRW · BOK",    "flag": "🇰🇷", "snapshot": "krw_stance.json",  "status": "live", "group": "EM Asia"},
    {"code": "twd",     "label": "TWD · CBC",    "flag": "🇹🇼", "snapshot": "twd_stance.json",  "status": "live", "group": "EM Asia"},
    {"code": "thb",     "label": "THB · BOT",    "flag": "🇹🇭", "snapshot": "thb_stance.json",  "status": "live", "group": "EM Asia"},
    {"code": "inr",     "label": "INR · RBI",    "flag": "🇮🇳", "snapshot": "inr_stance.json",  "status": "live", "group": "EM Asia"},
    {"code": "sgd",     "label": "SGD · MAS",    "flag": "🇸🇬", "snapshot": "sgd_stance.json",  "status": "live", "group": "EM Asia"},
    # ---- EM CEEMEA ----
    {"code": "huf",     "label": "HUF · MNB",    "flag": "🇭🇺", "snapshot": "huf_stance.json",  "status": "live", "group": "EM CEEMEA"},
    {"code": "pln",     "label": "PLN · NBP",    "flag": "🇵🇱", "snapshot": "pln_stance.json",  "status": "live", "group": "EM CEEMEA"},
    {"code": "czk",     "label": "CZK · CNB",    "flag": "🇨🇿", "snapshot": "czk_stance.json",  "status": "live", "group": "EM CEEMEA"},
    {"code": "ils",     "label": "ILS · BOI",    "flag": "🇮🇱", "snapshot": "ils_stance.json",  "status": "live", "group": "EM CEEMEA"},
    {"code": "zar",     "label": "ZAR · SARB",   "flag": "🇿🇦", "snapshot": "zar_stance.json",  "status": "live", "group": "EM CEEMEA"},
    # ---- EM LatAm ----
    {"code": "mxn",     "label": "MXN · BANXICO","flag": "🇲🇽", "snapshot": "mxn_stance.json",  "status": "live", "group": "EM LatAm"},
    {"code": "brl",     "label": "BRL · BCB",    "flag": "🇧🇷", "snapshot": "brl_stance.json",  "status": "live", "group": "EM LatAm"},
    {"code": "clp",     "label": "CLP · BCCH",   "flag": "🇨🇱", "snapshot": "clp_stance.json",  "status": "live", "group": "EM LatAm"},
    {"code": "cop",     "label": "COP · BANREP", "flag": "🇨🇴", "snapshot": "cop_stance.json",  "status": "live", "group": "EM LatAm"},
]

# Group render order
GROUP_ORDER = ["G10", "EM Asia", "EM CEEMEA", "EM LatAm"]


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
            y=df["commentary_score"],
            mode="lines",
            line=dict(color=colour, width=2),
            hovertemplate="%{x|%b %d}<br>commentary=%{y:+.2f}<extra></extra>",
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
    commentary = float(snap.get("commentary_score", 0.0))
    window_days = int(snap.get("commentary_window_days", 14))
    n_win = int(snap.get("n_items_window", 0))
    history = snap.get("history_90d", [])

    colour = commentary_color(commentary)
    band_lbl = commentary_band_label(commentary)

    # Confidence badge — how much data is actually behind the headline.
    # Thresholds scale with the CB's window (14d default, 30d for low-cadence).
    if window_days >= 30:
        low_thr, med_thr = 6, 15
    else:
        low_thr, med_thr = 5, 10
    if n_win < low_thr:
        conf_label, conf_bg, conf_fg = f"low conviction · n={n_win}", "#fee2e2", "#991b1b"
    elif n_win < med_thr:
        conf_label, conf_bg, conf_fg = f"medium conviction · n={n_win}", "#fef3c7", "#92400e"
    else:
        conf_label, conf_bg, conf_fg = f"high conviction · n={n_win}", "#dcfce7", "#166534"

    # Header + big number
    st.markdown(
        f"""
<div class='cb-card'>
  <div class='cb-header'>
    <span class='cb-name'>{cb['flag']} {cb['label']}</span>
  </div>
  <div class='cb-big' style='color:{colour};'>{commentary:+.2f}</div>
  <div class='cb-band-label' style='color:{colour};'>{band_lbl}</div>
  <div style='display:inline-block; margin-top:4px; padding:2px 8px; border-radius:10px;
              background:{conf_bg}; color:{conf_fg}; font-size:10.5px; font-weight:600;
              text-transform:uppercase; letter-spacing:0.4px;'>{conf_label}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Sparkline of commentary_score over trailing 30d.
    if history:
        st.plotly_chart(
            _sparkline(history, colour),
            use_container_width=True,
            config={"displayModeBar": False},
            key=f"spark_{cb['code']}",
        )

    st.markdown(
        f"<div class='cb-absolute'>{n_win} items in last {window_days} days</div>",
        unsafe_allow_html=True,
    )

    # Per-speaker current stance table (Option 1 per Graeme's spec 20 Jul 2026).
    # Simple: each speaker's average stance in the current commentary window.
    speakers = snap.get("speakers") or []
    if speakers:
        st.markdown(
            "<div style='margin-top:14px; font-size:12px; font-weight:700; "
            "color:#374151; text-transform:uppercase; letter-spacing:0.4px;'>"
            f"Speakers ({len(speakers)} in last {window_days} days)</div>",
            unsafe_allow_html=True,
        )
        rows = []
        for sp in speakers:
            role = (sp.get("role") or "").replace("_", " ")
            voting = sp.get("voting_2026")
            if voting is True and role != "chair":
                role += " · voter"
            elif voting is False:
                role += " · non-voter"
            rows.append({
                "Speaker": sp.get("name", ""),
                "Role": role.strip() or "—",
                "Stance": sp.get("mean_stance"),
                "N": sp.get("n_items", 0),
            })
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.format({"Stance": "{:+.2f}"}, na_rep="—"),
            use_container_width=True,
            hide_index=True,
            height=min(35 * (len(df) + 1) + 4, 320),
        )

    # Top 5 comments (per-CB, importance-ranked, chronological display order).
    _render_key_comments_for_cb(snap, k=5)


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
        return (1, entry["_idx"])

    commentary = float(snap.get("commentary_score", 0.0))

    if mode == "Most hawkish first":
        return (0, -commentary)
    if mode == "Most dovish first":
        return (0, commentary)
    # Alphabetical
    return (0, entry["cb"]["label"])


# ---------------------------------------------------------------------------
# Top 3 key comments (cross-CB)
# ---------------------------------------------------------------------------
def _fmt_role(role: str | None, voting: bool | None) -> str:
    if not role:
        return "speaker"
    if role == "institutional":
        return "official statement"
    m = {
        "chair": "Chair",
        "vice_chair": "Vice Chair",
        "vice_chair_supervision": "Vice Chair for Supervision",
        "governor": "Governor",
        "nyfed_president": "NY Fed President",
        "regional_president": "Regional Fed President",
        "deputy_governor": "Deputy Governor",
        "mpc_external": "External MPC Member",
    }
    label = m.get(role, role.replace("_", " ").title())
    if voting is True:
        label += " · voter"
    elif voting is False and role != "chair":
        label += " · non-voter"
    return label


def _fmt_relative_time(iso_ts: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return ""
    delta = datetime.now(timezone.utc) - dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() / 60)} min ago"
    if hours < 24:
        return f"{int(hours)} h ago"
    days = int(hours / 24)
    return f"{days} day{'s' if days != 1 else ''} ago"


def _render_key_comments_for_cb(snap: dict, k: int = 5) -> None:
    """Render the top-k key_comments for a single CB inside its card.
    Same visual language as before (coloured left bar, italic quote, why-line)
    just scoped to one CB."""
    kc = snap.get("key_comments") or []
    st.markdown("<div style='margin-top:14px; font-size:12px; font-weight:700; "
                "color:#374151; text-transform:uppercase; letter-spacing:0.4px;'>"
                f"Top {k} comments</div>", unsafe_allow_html=True)
    if not kc:
        st.markdown(
            "<div style='color:#9ca3af; font-size:12px; margin-top:6px;'>"
            "No stand-out comments in the trailing 30 days."
            "</div>",
            unsafe_allow_html=True,
        )
        return
    for c in kc[:k]:
        stance = float(c.get("stance", 0.0))
        colour = band_color(stance)
        speaker = c.get("speaker", "—")
        role_tag = _fmt_role(c.get("role"), c.get("voting_2026"))
        phrase = c.get("phrase") or ""
        reasons = c.get("reasons") or []
        why = " · ".join(reasons) if reasons else "—"
        when = _fmt_relative_time(c.get("published_at", ""))
        st.markdown(
            f"""
<div style="border-left:4px solid {colour}; background:#fafafa; padding:8px 10px;
            border-radius:4px; margin:6px 0;">
  <div style="font-size:12px; color:#111827;">
    <strong>{speaker}</strong>
    <span style="color:#6b7280; font-weight:500;"> · {role_tag}</span>
    <span style="color:#9ca3af; float:right; font-size:11px;">{when}</span>
  </div>
  <div style="font-style:italic; color:#374151; margin-top:4px; font-size:12.5px; line-height:1.35;">
    “{phrase}”
  </div>
  <div style="color:#6b7280; font-size:10.5px; margin-top:4px; line-height:1.3;">
    <strong>Why:</strong> {why}
    &nbsp;·&nbsp; stance {stance:+.2f}
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )


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
        f"Speaker-relative hawk/dove tracking across G10 + 15 EM central banks. "
        f"Last updated: **{as_of_str}**"
    )

    with st.expander("How to read this dashboard"):
        st.markdown(
            """
**What it shows.** For each central bank, we score every speaker headline
(prepared speech, minutes, off-the-cuff, statement) on a −5 (ultra-dovish)
to +5 (ultra-hawkish) scale using a small LLM, then aggregate with these
weights:

- **Speaker weight:** Chair 1.0 → Vice/Deputy 0.7 → Voting member 0.6 → Non-voter 0.4.
- **Event weight:** Prepared speech 1.0 → Off-the-cuff 0.75 → Minutes 0.5.
- **Recency:** 7-day exponential half-life over the trailing 14 days for
  high-cadence CBs (Fed, ECB, BoE), or 30 days for low-cadence CBs
  (BoJ, RBA, RBNZ, BoC, SNB, Riksbank, Norges, all EM) where a 14d window
  would be dominated by n=1-2 items.

**The big number (commentary score, −5 to +5)** is the *how hawkish/dovish
is this CB right now* reading based on what its speakers actually said in
the recent window. It doesn't move when nothing new is said.

**Card colour bands.**
`< −2.0` deep green (very dovish) · `−2.0…−0.75` green (dovish) ·
`−0.75…+0.75` grey (neutral) · `+0.75…+2.0` red (hawkish) ·
`> +2.0` deep red (very hawkish).

**Sparkline** plots the commentary score over the trailing 30 days.

**Speakers table** — each speaker's confidence-weighted average stance
in the current commentary window. Sorted most hawkish first. Only speakers
with at least one policy-relevant comment in the window are shown.

**Top 5 comments** — the most policy-relevant headlines in the last 30
days (Chair/Vice-Chair speeches, off-lean moves, cross-market extremes),
displayed in chronological order (most recent first).

**Conviction badge.** Small tag under the headline number, showing `n` —
the number of policy-relevant items scored in the CB's recent window.
Treat low-conviction (`n < 5-6`) headline numbers with caution — the
signal is directionally real but sample-size limited.
            """
        )

    # --- Controls ----------------------------------------------------------
    c1, c2 = st.columns([3, 1])
    with c1:
        sort_mode = st.selectbox(
            "Sort by",
            [
                "Most hawkish first",
                "Most dovish first",
                "Alphabetical",
            ],
            index=0,
        )
    with c2:
        if st.button("↻ Refresh", use_container_width=True):
            st.session_state["_cb_cache_bust"] = datetime.now(timezone.utc).isoformat()
            st.rerun()

    # --- Build card list ---------------------------------------------------
    entries: list[dict] = []
    for idx, cb in enumerate(CB_REGISTRY):
        snap = None
        if cb.get("snapshot"):
            snap = _load_snapshot(cb["snapshot"], cache_bust)
        # If snapshot says sparse (zero items ever scored), treat as "coming soon"
        # to avoid a misleading 0.00σ neutral reading.
        if snap is not None and snap.get("sparse") and int(snap.get("n_items_total", 0)) == 0:
            snap = None
        entries.append({"cb": cb, "snap": snap, "_idx": idx})

    if not entries:
        st.info("No central banks match the current filter.")
        return

    # --- Grid — grouped by G10 / EM Asia / EM CEEMEA / EM LatAm -----------
    # Phone-ish widths get 1 column; wider gets 3.
    # Streamlit doesn't tell us the viewport width; use 3-up desktop layout and
    # rely on the browser wrapping cards vertically on narrow screens.
    per_row = 3

    # Group entries and preserve group order.
    grouped: dict[str, list[dict]] = {g: [] for g in GROUP_ORDER}
    for e in entries:
        g = e["cb"].get("group", "Other")
        grouped.setdefault(g, []).append(e)

    for group_name in list(grouped.keys()):
        group_entries = grouped[group_name]
        if not group_entries:
            continue
        # Sort within group by the selected mode
        group_entries.sort(key=lambda e: _card_sort_key(e, sort_mode))

        # Section header (small, styled)
        st.markdown(
            f"<div style='margin:20px 0 8px; padding-bottom:4px;"
            f" border-bottom:1px solid #e5e7eb; color:#374151;"
            f" font-size:12.5px; font-weight:700;"
            f" text-transform:uppercase; letter-spacing:0.6px;'>"
            f"{group_name}"
            f"<span style='color:#9ca3af; font-weight:500; margin-left:8px;'>"
            f"· {len(group_entries)} banks</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        for row_start in range(0, len(group_entries), per_row):
            row = group_entries[row_start : row_start + per_row]
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
        "Snapshots rebuilt nightly. G10 + 15 EM central banks tracked."
        "</div>",
        unsafe_allow_html=True,
    )
