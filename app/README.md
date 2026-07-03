# Macro Nowcast — Streamlit

A live macro nowcast dashboard. First cut ships the **US** page: three pillars
(Growth, Inflation, Liquidity), a Growth×Inflation regime grid, per-pillar
sub-Z drilldown, weekly movers, and the full component library with sparklines
and raw underlying series.

Data comes from FRED, cached in `../us/fred_cache.sqlite` with a 24-hour TTL
per series. Rendering is Plotly (hover tooltips, zoom, pan, range selection).

## Repo layout

```
macro-nowcast/
├── app/                       # streamlit entry point
│   ├── streamlit_app.py       # country tabs + auth gate
│   ├── countries/
│   │   ├── us.py              # ← live
│   │   └── coming_soon.py     # UK / EZ / JP / CA / AU stubs
│   ├── shared/
│   │   ├── engines/           # sys.path bridge into ../us
│   │   ├── charts.py          # plotly helpers
│   │   └── theme.py           # colours, CSS, stat cards
│   ├── .streamlit/config.toml
│   └── requirements.txt
└── us/                        # engines (compute logic)
    ├── nowcast_core.py
    ├── liquidity_pillar.py
    ├── growth_phase2.py
    ├── inflation_phase2.py
    └── regime_phase3.py
```

The `us/` folder is the **single source of truth** for compute. The app never
duplicates a Z-score calculation; it just imports.

Adding a country later means:
1. Drop a `uk/` sibling to `us/` with the same module layout.
2. Add `app/countries/uk.py` calling the engines.
3. Register it in the `COUNTRIES` list in `streamlit_app.py`.

## Local dev

```bash
cd app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
FRED_API_KEY=<your key> .venv/bin/streamlit run streamlit_app.py
```

Open http://localhost:8501.

## Secrets

Two values are read from Streamlit secrets (or env vars):

| Name | Purpose |
|---|---|
| `FRED_API_KEY` | Your St Louis Fed FRED key |
| `APP_PASSWORD` | Optional — enables the password gate; omit for no gate |

Locally either export them:

```bash
export FRED_API_KEY=...
export APP_PASSWORD=...
```

or put them in `app/.streamlit/secrets.toml` (git-ignored — see `.gitignore`):

```toml
FRED_API_KEY = "..."
APP_PASSWORD = "..."
```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (private is fine on the Community Cloud tier).
2. Go to https://share.streamlit.io/, connect your GitHub, click **New app**.
3. Point it at this repo:
   - **Main file path:** `app/streamlit_app.py`
   - **Python version:** 3.11
4. Under **Advanced settings → Secrets**, paste:
   ```toml
   FRED_API_KEY = "your fred key"
   APP_PASSWORD = "a password you'll share only with the humans allowed in"
   ```
5. Click **Deploy**. First build takes ~2 min while it installs `streamlit`,
   `plotly`, `pandas` from `app/requirements.txt`.
6. Share the URL. First visit warms the FRED cache (~15 s); every subsequent
   visit is instant.

## Data refresh

- The Streamlit `@st.cache_data(ttl=8*3600)` decorator on `_build_all()` means
  the compute reruns at most every 8 hours per container. Since FRED itself is
  cached with a 24 h per-series TTL, a full rebuild only re-hits FRED for
  series that are stale.
- Force a rebuild via the **🔄 Force rebuild from FRED** button in the sidebar.

## Rebuilding the static HTML dashboard

The original static-HTML build path in `us/build_all.py` still works:

```bash
cd us
python3 build_all.py   # writes dashboard.html + charts/*.png
```

Kept intentionally as a fallback / for offline snapshots.
