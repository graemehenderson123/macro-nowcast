"""Shared visual constants for the streamlit nowcast app."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Colour palette (matches the original static dashboard)
# ---------------------------------------------------------------------------
NAVY    = "#1a365d"
TEAL    = "#2c7a7b"
BRICK   = "#c0392b"
ORANGE  = "#c05621"
GREEN   = "#38a169"
AMBER   = "#d69e2e"
GREY    = "#a0aec0"
LIGHT_BG = "#fafafa"
CARD_BG  = "#ffffff"

REGIME_COLORS = {
    "Overheating":         "#c05621",
    "Goldilocks":          "#38a169",
    "Stagflation":         "#c53030",
    "Deflation/Recession": "#2b6cb0",
    "Reflation":           "#805ad5",
    "Disinflation":        "#4fd1c5",
    "Slowdown":            "#d69e2e",
    "Neutral":             "#a0aec0",
    "Unknown":             "#cccccc",
}

REGIME_DESCRIPTIONS = {
    "Overheating":         "Growth strong + inflation rising — late-cycle reflation.",
    "Goldilocks":          "Growth strong + inflation cooling — disinflationary expansion.",
    "Stagflation":         "Growth weak + inflation rising — worst mix for risk assets.",
    "Deflation/Recession": "Growth weak + inflation falling — classic recession.",
    "Reflation":           "Growth accelerating with inflation neutral — early expansion.",
    "Slowdown":            "Growth decelerating with inflation neutral — late cycle cooling.",
    "Disinflation":        "Growth neutral with inflation falling — soft landing tone.",
    "Neutral":             "Both Growth and Inflation near trend — no strong regime signal.",
    "Unknown":             "Insufficient data.",
}

TIME_RANGES = {
    "6m": 30 * 6,
    "1y": 365,
    "3y": 365 * 3,
    "5y": 365 * 5,
    "All": None,
}

# Global CSS injected once per page
GLOBAL_CSS = """
<style>
  /* tighten default streamlit padding */
  .block-container { padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1200px; }

  /* card */
  .nc-card {
    background: white;
    padding: 18px 20px;
    margin: 10px 0 14px 0;
    border-radius: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    border: 1px solid #eef;
  }
  .nc-card h3 { margin: 0 0 8px 0; font-size: 15px; color: #333; }

  /* regime headline */
  .nc-regime-card {
    padding: 22px 24px;
    border-radius: 14px;
    margin-bottom: 18px;
  }
  .nc-regime-eyebrow {
    font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px;
  }
  .nc-regime-label { font-size: 34px; font-weight: 800; letter-spacing: 0.5px; margin: 2px 0 6px 0; }
  .nc-regime-sub { font-size: 14px; color: #333; opacity: 0.95; }

  /* stat pill */
  .nc-stat {
    padding: 10px 14px;
    border-left: 4px solid #1a365d;
    background: #f8f9fa;
    border-radius: 6px;
    height: 100%;
  }
  .nc-stat .lbl { font-size: 10px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
  .nc-stat .val { font-size: 22px; font-weight: 700; color: #1a365d; margin: 3px 0; font-variant-numeric: tabular-nums; }
  .nc-stat .meta { font-size: 11px; color: #666; }
  .nc-stat.pos { border-left-color: #2c7a7b; }
  .nc-stat.pos .val { color: #2c7a7b; }
  .nc-stat.neg { border-left-color: #c0392b; }
  .nc-stat.neg .val { color: #c0392b; }
  .nc-stat.neu { border-left-color: #999; }
  .nc-stat.neu .val { color: #555; }

  /* table tweaks */
  .nc-table { font-size: 13px; }
  .stDataFrame { border-radius: 6px; }

  /* footer */
  .nc-footer { color: #888; font-size: 11px; margin-top: 24px; }

  /* mobile: shrink regime label + stat values a touch */
  @media (max-width: 500px) {
    .nc-regime-label { font-size: 26px; }
    .nc-stat .val { font-size: 18px; }
    .block-container { padding-left: 0.5rem; padding-right: 0.5rem; }
  }
</style>
"""


def z_class(z: float | None) -> str:
    """Return a CSS class name for a Z-score bucket."""
    import math
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "neu"
    if z > 0.25:
        return "pos"
    if z < -0.25:
        return "neg"
    return "neu"


def fmt_z(z) -> str:
    import math
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "—"
    return f"{z:+.2f}σ"


def stat_card(label: str, value: str, meta: str = "", z: float | None = None) -> str:
    cls = z_class(z) if z is not None else "neu"
    return (
        f"<div class='nc-stat {cls}'>"
        f"<div class='lbl'>{label}</div>"
        f"<div class='val'>{value}</div>"
        f"<div class='meta'>{meta}</div>"
        f"</div>"
    )
