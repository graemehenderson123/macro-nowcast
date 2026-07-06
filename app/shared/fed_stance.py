"""Fed Policy Stance renderer.

Reads a static JSON snapshot (`app/data/fed_stance.json`) produced nightly by
``~/.openclaw/workspace/cb_monitor/build_stance.py`` and rendered as a row on
the US country page.

If the snapshot is missing (e.g. fresh checkout on Streamlit Cloud before the
first build), degrade gracefully with a "Stance data not available" caption.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "fed_stance.json"


def _colour_for(score: float) -> str:
    # Red for hawkish (positive = tighter policy => risk-off / USD+),
    # green for dovish (negative = looser).
    if score >= 1.5:
        return "#c0392b"
    if score >= 0.5:
        return "#e67e22"
    if score > -0.5:
        return "#7f8c8d"
    if score > -1.5:
        return "#27ae60"
    return "#16a085"


def _sparkline(history: list[dict]) -> go.Figure:
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    # last 30 days
    tail = df.tail(30)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=tail["date"], y=tail["surprise_score"],
        mode="lines", line=dict(color="#2c3e50", width=2),
        name="Surprise",
        hovertemplate="%{x|%b %d}<br>surprise=%{y:+.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#bbb", width=1, dash="dot"))
    fig.update_layout(
        height=140,
        margin=dict(l=10, r=10, t=6, b=6),
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(size=10)),
        yaxis=dict(showgrid=True, gridcolor="#eee", tickfont=dict(size=10), zeroline=False),
        plot_bgcolor="white",
    )
    return fig


def render() -> None:
    if not SNAPSHOT_PATH.exists():
        st.info("🦅🕊️ Fed Policy Stance — snapshot not available (waiting for first build).")
        return

    try:
        snap = json.loads(SNAPSHOT_PATH.read_text())
    except Exception as e:  # noqa: BLE001
        st.warning(f"Could not read Fed stance snapshot: {e}")
        return

    surprise = float(snap.get("surprise_score", 0.0))
    commentary = float(snap.get("commentary_score", 0.0))
    label = snap.get("label", "neutral")
    n14 = int(snap.get("n_items_14d", 0))
    as_of = snap.get("as_of", "")
    colour = _colour_for(surprise)

    st.markdown(
        "<div style='display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;'>"
        "<h2 style='margin:0;'>🦅🕊️ Fed Policy Stance</h2>"
        f"<div style='font-size:26px;font-weight:800;color:{colour};'>{surprise:+.2f}</div>"
        f"<div style='color:#666;font-size:12px;'>surprise-adjusted · label <strong>{label}</strong></div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Positive = hawkish surprise vs speaker priors · negative = dovish · scale −5…+5 · "
        f"{n14} scored items in last 14d · commentary raw {commentary:+.2f} · "
        f"as of {as_of[:16].replace('T', ' ')} UTC"
    )

    col_left, col_right = st.columns([1, 1.4])

    with col_left:
        st.plotly_chart(_sparkline(snap.get("history_90d", [])), use_container_width=True)

    with col_right:
        movers = snap.get("top_movers", [])
        if not movers:
            st.caption("No recent movers.")
        else:
            rows = []
            for m in movers:
                rows.append({
                    "Date": m["published_at"][:10],
                    "Speaker": m["speaker"],
                    "Stance": m["stance"],
                    "Prior": m["prior"],
                    "Surprise": m["surprise"],
                    "Contribution": m["contribution"],
                    "Phrase": (m.get("phrase") or "")[:110],
                })
            df = pd.DataFrame(rows)
            st.dataframe(
                df.style
                  .format({"Stance": "{:+.2f}", "Prior": "{:+.2f}", "Surprise": "{:+.2f}", "Contribution": "{:+.3f}"})
                  .map(
                      lambda v: "color:#c0392b;font-weight:600" if isinstance(v, (int, float)) and v > 0.25
                                else ("color:#27ae60;font-weight:600" if isinstance(v, (int, float)) and v < -0.25 else ""),
                      subset=["Stance", "Surprise", "Contribution"],
                  ),
                use_container_width=True,
                hide_index=True,
                height=min(38 * (len(df) + 1) + 10, 260),
            )

    with st.expander("Methodology"):
        meth = snap.get("methodology", {})
        st.markdown(
            f"""
- **Scale:** {meth.get('scale', '')}
- **Primary signal:** {meth.get('primary_signal', '')}
- **Commentary window:** last {meth.get('commentary_window_days', '?')} days
- **Speaker prior:** rolling mean of same-speaker stance over last {meth.get('surprise_lookback_days', '?')} days
- **Recency half-life:** {meth.get('recency_halflife_days', '?')} days
- **Speaker weights:** {meth.get('speaker_weight_scale', '')}
- **Event weights:** {meth.get('event_weights', '')}
- **Source:** Newsquawk speaker headlines, LLM-classified (gpt-4o-mini), \
cached in `~/.openclaw/workspace/cb_monitor/stance_cache.sqlite`. Snapshot rebuilt nightly.
"""
        )
