"""Placeholder page for countries not yet built."""
from __future__ import annotations
import streamlit as st


def render(country: str, source: str, eta: str = "next pass"):
    st.markdown(
        f"""
### 🚧 {country} — coming soon

The engines for **{country}** haven't been ported yet. Once done they'll drop
in as `countries/{country.lower()}.py` and share the same shared plot / theme
layer.

- **Data source:** {source}
- **ETA:** {eta}
- **Same architecture:** hard + soft pillars, 36-month rolling Z, 4-quadrant
  regime with a liquidity modifier. Weights defined per `memory/macro/nowcast/{country.lower()}/INDICATOR-WEIGHTS.md`.
""",
        unsafe_allow_html=True,
    )
