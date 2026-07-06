"""Central-bank Stance Monitor — theme + helpers.

Colour palette and small helpers used by the dedicated CB monitor page.
Kept in ``shared/`` so future country pages can reuse the same buckets.
"""
from __future__ import annotations

import math
from typing import Iterable

# ---------------------------------------------------------------------------
# 5-band gradient for `surprise_score` (in σ, roughly ±3σ range).
#
#   z < -1.5       deep green  (very dovish surprise)
#   -1.5 ≤ z < -0.5 green       (dovish surprise)
#   -0.5 ≤ z ≤ 0.5 grey        (neutral)
#    0.5 < z ≤ 1.5 red         (hawkish surprise)
#    z > 1.5       deep red    (very hawkish surprise)
# ---------------------------------------------------------------------------
BAND_DEEP_DOVE = "#166534"
BAND_DOVE = "#16a34a"
BAND_NEUTRAL = "#6b7280"
BAND_HAWK = "#dc2626"
BAND_DEEP_HAWK = "#7f1d1d"

AMBER_BANNER_BG = "#fef3c7"
AMBER_BANNER_BORDER = "#f59e0b"
AMBER_BANNER_TEXT = "#78350f"

CARD_BG_EMPTY = "#f3f4f6"
CARD_BORDER = "#e5e7eb"


def band_color(z: float | None) -> str:
    """Return hex colour for a `surprise_score` in σ."""
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return BAND_NEUTRAL
    if z < -1.5:
        return BAND_DEEP_DOVE
    if z < -0.5:
        return BAND_DOVE
    if z <= 0.5:
        return BAND_NEUTRAL
    if z <= 1.5:
        return BAND_HAWK
    return BAND_DEEP_HAWK


def band_label(z: float | None) -> str:
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "no data"
    if z < -1.5:
        return "very dovish surprise"
    if z < -0.5:
        return "dovish surprise"
    if z <= 0.5:
        return "neutral"
    if z <= 1.5:
        return "hawkish surprise"
    return "very hawkish surprise"


def commentary_label(score: float | None) -> str:
    """Human-friendly label for the absolute commentary score (−5…+5)."""
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return "no data"
    if score >= 2.0:
        return "hawkish"
    if score >= 0.5:
        return "lean hawkish"
    if score > -0.5:
        return "neutral"
    if score > -2.0:
        return "lean dovish"
    return "dovish"


def direction_arrow(delta: float | None) -> tuple[str, str, int]:
    """Return (arrow_char, colour, font_pt) for a 14-day surprise delta.

    Font size scales with magnitude (16-40pt) so bigger moves are visually louder.
    """
    if delta is None or (isinstance(delta, float) and math.isnan(delta)):
        return "→", BAND_NEUTRAL, 24
    mag = abs(delta)
    # 16pt at |Δ|=0.1, up to 40pt at |Δ|=1.5+
    size = int(min(40, 16 + mag * 16))
    if delta > 0.15:
        return "↑", BAND_HAWK, size
    if delta < -0.15:
        return "↓", BAND_DOVE, size
    return "→", BAND_NEUTRAL, 20


def delta_phrase(delta: float | None) -> str:
    if delta is None or (isinstance(delta, float) and math.isnan(delta)):
        return "no data"
    if delta > 0.15:
        return "more hawkish"
    if delta < -0.15:
        return "more dovish"
    return "flat"


# ---------------------------------------------------------------------------
# Global CSS for the CB monitor page
# ---------------------------------------------------------------------------
CB_CSS = """
<style>
  .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1280px; }

  .cb-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 18px 18px 14px 18px;
    margin: 8px 0 12px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    position: relative;
    min-height: 340px;
  }
  .cb-card.empty {
    background: #f9fafb;
    color: #9ca3af;
    border-style: dashed;
    min-height: 340px;
  }
  .cb-card .cb-header {
    display: flex; align-items: baseline; justify-content: space-between;
    margin-bottom: 6px;
  }
  .cb-card .cb-name {
    font-size: 24px; font-weight: 800; letter-spacing: 0.5px;
    color: #111827;
  }
  .cb-card .cb-arrow { font-weight: 800; line-height: 1; }
  .cb-card .cb-big {
    font-size: 48px; font-weight: 800; line-height: 1.05;
    font-variant-numeric: tabular-nums; margin-top: 2px;
  }
  .cb-card .cb-band-label {
    font-size: 13px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
    margin-top: 2px;
  }
  .cb-card .cb-meta {
    color: #6b7280; font-size: 12px; margin-top: 6px;
  }
  .cb-card .cb-delta {
    font-size: 13px; margin-top: 8px; color: #374151;
  }
  .cb-card .cb-absolute {
    font-size: 12px; color: #6b7280; margin-top: 2px;
  }
  .cb-card .cb-mover {
    font-size: 12px; color: #374151; margin-top: 4px;
    line-height: 1.35;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .cb-card .cb-mover .sp { font-weight: 600; color: #111827; }

  .cb-banner {
    background: #fef3c7;
    border-left: 4px solid #f59e0b;
    color: #78350f;
    font-weight: 700; font-size: 12px;
    padding: 6px 10px;
    border-radius: 6px;
    margin: 8px 0 4px 0;
    text-transform: uppercase; letter-spacing: 0.5px;
  }

  .cb-empty-body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    height: 260px; text-align: center;
  }
  .cb-empty-body .flag { font-size: 56px; margin-bottom: 8px; }
  .cb-empty-body .name { font-size: 22px; font-weight: 700; color: #6b7280; }
  .cb-empty-body .soon { font-size: 12px; color: #9ca3af; margin-top: 6px;
    text-transform: uppercase; letter-spacing: 1px; }

  /* mobile */
  @media (max-width: 640px) {
    .cb-card .cb-big { font-size: 38px; }
    .cb-card .cb-name { font-size: 20px; }
    .block-container { padding-left: 0.6rem; padding-right: 0.6rem; }
  }
</style>
"""


def truncate(s: str, n: int = 60) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
