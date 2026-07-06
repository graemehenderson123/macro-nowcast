"""Macro Nowcast — entry point (multipage via st.navigation).

Two top-level pages:
  1. 📈 Macro Nowcast — the existing country-selector nowcast.
  2. 🦅🕊️ CB Stance Monitor — dedicated central-bank hawk/dove dashboard.

Auth (password gate) and FRED key wiring run once for both pages.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import streamlit as st

# Make ``shared`` importable when running via ``streamlit run streamlit_app.py``
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Macro Nowcast",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# FRED key: pull from Streamlit secrets if available, else env / .env fallback.
# ---------------------------------------------------------------------------
try:
    if "FRED_API_KEY" in st.secrets:
        os.environ["FRED_API_KEY"] = st.secrets["FRED_API_KEY"]
except Exception:
    pass

# ---------------------------------------------------------------------------
# Password gate (Streamlit's built-in secrets pattern).
# Enabled only when APP_PASSWORD is present in st.secrets (or env).
# ---------------------------------------------------------------------------
def _password_ok() -> bool:
    password = None
    try:
        password = st.secrets.get("APP_PASSWORD")
    except Exception:
        pass
    if not password:
        password = os.environ.get("APP_PASSWORD")
    if not password:
        return True  # no gate configured

    if st.session_state.get("_auth_ok"):
        return True

    st.markdown("### 🔒 Macro Nowcast")
    st.caption("Enter the password to view the dashboard.")
    with st.form("login", clear_on_submit=False):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if pw == password:
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


if not _password_ok():
    st.stop()

# ---------------------------------------------------------------------------
# Country registry (Nowcast page only)
# ---------------------------------------------------------------------------
COUNTRIES = [
    {"code": "US", "label": "🇺🇸 United States", "status": "live"},
    {"code": "UK", "label": "🇬🇧 United Kingdom", "status": "soon", "source": "ONS + BoE"},
    {"code": "EZ", "label": "🇪🇺 Eurozone",       "status": "soon", "source": "Eurostat + ECB"},
    {"code": "JP", "label": "🇯🇵 Japan",           "status": "soon", "source": "e-Stat + BoJ"},
    {"code": "CA", "label": "🇨🇦 Canada",          "status": "soon", "source": "StatCan + BoC"},
    {"code": "AU", "label": "🇦🇺 Australia",       "status": "soon", "source": "ABS + RBA"},
]


# ---------------------------------------------------------------------------
# Page callables
# ---------------------------------------------------------------------------
def _nowcast_page() -> None:
    """Existing macro-nowcast surface with country picker in the sidebar."""
    with st.sidebar:
        st.markdown("## 📈 Macro Nowcast")
        st.caption("G10 macro nowcast — pillars, regime, drill-down.")
        labels = [c["label"] + ("" if c["status"] == "live" else "  · soon") for c in COUNTRIES]
        codes  = [c["code"] for c in COUNTRIES]
        picked_label = st.radio("Country", labels, index=0, key="_nowcast_country")
        picked = codes[labels.index(picked_label)]

    country = next(c for c in COUNTRIES if c["code"] == picked)
    st.title(f"{country['label']} — Macro Nowcast")

    if country["status"] == "live":
        if picked == "US":
            from countries import us
            us.render()
    else:
        from countries import coming_soon
        coming_soon.render(country["code"], country.get("source", "TBD"))


def _cb_monitor_page() -> None:
    """Dedicated Central Bank Stance Monitor."""
    with st.sidebar:
        st.markdown("## 🦅🕊️ CB Monitor")
        st.caption("Speaker-relative hawk/dove tracking. Phase 1: Fed live.")
    from pages_cb import cb_monitor
    cb_monitor.render()


# ---------------------------------------------------------------------------
# Nav — prefer new st.navigation (>= 1.36). Fall back to top-level tabs.
# ---------------------------------------------------------------------------
def _run_with_navigation() -> bool:
    try:
        nav = st.navigation(
            [
                st.Page(_nowcast_page,    title="Macro Nowcast",       icon="📈", default=True),
                st.Page(_cb_monitor_page, title="CB Stance Monitor",   icon="🦅"),
            ]
        )
    except Exception:
        return False
    nav.run()
    return True


if not _run_with_navigation():
    tab1, tab2 = st.tabs(["📈 Macro Nowcast", "🦅🕊️ CB Stance Monitor"])
    with tab1:
        _nowcast_page()
    with tab2:
        _cb_monitor_page()
