#!/usr/bin/env python3
"""
US Nowcast — Phase 1: Liquidity pillar dashboard.

Pulls FRED series, computes Z-scores (36m rolling on diffs / appropriate basis
per series), composes Fed sub-Z + Market sub-Z + headline NET FED LIQUIDITY line,
renders a single static HTML page with embedded PNG charts.

Refreshable: run `python3 liquidity_phase1.py` to rebuild.
"""
from __future__ import annotations
import os, json, sqlite3, datetime as dt
from pathlib import Path
import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = Path(__file__).parent
DB = ROOT / "fred_cache.sqlite"
OUT_HTML = ROOT / "dashboard.html"
OUT_DIR = ROOT / "charts"
OUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# FRED key resolution — lazy, env-first.
#
# Historically this module ran `FRED_KEY = load_key()` at import time, reading
# the workspace .env. On Streamlit Cloud there is no workspace .env, so the
# import blew up with 'Failed to build pillars: name FRED_KEY is not defined'.
#
# Fix (mirrors the 10 Jul fix applied to nowcast_core.py): resolve the key
# ONLY when something reads `FRED_KEY`, prefer os.environ, fall back to .env
# if present. On Streamlit Cloud, streamlit_app.py copies
# st.secrets['FRED_API_KEY'] into os.environ at boot so this Just Works.
# ---------------------------------------------------------------------------
import os
ENV_FILE = ROOT.parent.parent / ".env"

def load_key():
    env_key = os.environ.get("FRED_API_KEY")
    if env_key:
        return env_key
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        "FRED_API_KEY not found — set the env var or add it to .env"
    )

_FRED_KEY_CACHE: 'str | None' = None

def _get_key():
    """Return the cached FRED key, loading it lazily on first call.

    Module-level __getattr__ only fires for external `module.FRED_KEY`
    lookups; intra-module code must call this helper instead.
    """
    global _FRED_KEY_CACHE
    if _FRED_KEY_CACHE is None:
        _FRED_KEY_CACHE = load_key()
    return _FRED_KEY_CACHE

def __getattr__(name):
    if name == "FRED_KEY":
        return _get_key()
    raise AttributeError(name)

# ============================================================================
# Series catalogue — Liquidity pillar per INDICATOR-WEIGHTS.md
# Each: series_id, tier weight, kind, transform (level/diff/log-diff), sign,
# and label for the dashboard.
# ============================================================================
SERIES = [
    # Fed liquidity sub-pillar
    {"id":"WALCL",      "weight":1.00, "kind":"fed",    "transform":"diff",     "sign":+1, "label":"Fed Balance Sheet (WALCL)", "freq":"W"},
    {"id":"WTREGEN",    "weight":1.00, "kind":"fed",    "transform":"diff",     "sign":-1, "label":"Treasury General Account (TGA)", "freq":"W"},
    {"id":"RRPONTSYD",  "weight":1.00, "kind":"fed",    "transform":"diff",     "sign":-1, "label":"Overnight Reverse Repo (RRP)", "freq":"D"},
    {"id":"TOTRESNS",   "weight":0.70, "kind":"fed",    "transform":"diff",     "sign":+1, "label":"Bank Reserves (TOTRESNS)", "freq":"M"},
    # Market liquidity sub-pillar
    {"id":"BAMLC0A0CM", "weight":1.00, "kind":"market", "transform":"level",    "sign":-1, "label":"IG OAS (BAMLC0A0CM)", "freq":"D"},
    {"id":"BAMLH0A0HYM2","weight":1.00,"kind":"market", "transform":"level",    "sign":-1, "label":"HY OAS (BAMLH0A0HYM2)", "freq":"D"},
    {"id":"DGS2",       "weight":0.70, "kind":"market", "transform":"level",    "sign":-1, "label":"2y UST yield", "freq":"D"},
    {"id":"DGS10",      "weight":0.70, "kind":"market", "transform":"level",    "sign":-1, "label":"10y UST yield", "freq":"D"},
    {"id":"T10Y2Y",     "weight":0.70, "kind":"market", "transform":"level",    "sign":+1, "label":"2s10s curve", "freq":"D"},
    {"id":"T5YIFR",     "weight":0.50, "kind":"market", "transform":"level",    "sign":+1, "label":"5y5y forward breakeven", "freq":"D"},
    {"id":"VIXCLS",     "weight":1.00, "kind":"market", "transform":"level",    "sign":-1, "label":"VIX", "freq":"D"},
    {"id":"DTWEXBGS",   "weight":1.00, "kind":"market", "transform":"level",    "sign":-1, "label":"Broad USD index", "freq":"D"},
]

# ============================================================================
# FRED fetch (with cache)
# ============================================================================
def init_cache():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS obs (
      series_id TEXT NOT NULL,
      date TEXT NOT NULL,
      value REAL,
      PRIMARY KEY (series_id, date)
    );
    CREATE TABLE IF NOT EXISTS meta (
      series_id TEXT PRIMARY KEY,
      last_fetched TEXT,
      last_obs_date TEXT
    );
    """)
    con.commit()
    return con

def fetch_series(series_id: str, con: sqlite3.Connection) -> pd.Series:
    """Fetch observations from FRED, cache, return as pandas Series."""
    # Pull last observed date from cache
    cur = con.execute("SELECT MAX(date) FROM obs WHERE series_id=?", (series_id,))
    last_obs = cur.fetchone()[0]
    params = {
        "series_id": series_id,
        "api_key": _get_key(),
        "file_type": "json",
        "sort_order": "asc",
    }
    if last_obs:
        # Re-pull from a few months back to capture revisions
        start = (dt.date.fromisoformat(last_obs) - dt.timedelta(days=90)).isoformat()
        params["observation_start"] = start
    else:
        # First fetch: go back to 2010 for sufficient z-score history
        params["observation_start"] = "2010-01-01"
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()["observations"]
    rows = [(series_id, o["date"], float(o["value"])) for o in data if o["value"] not in (".","")]
    if rows:
        con.executemany("INSERT OR REPLACE INTO obs VALUES (?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?,?)",
                    (series_id, dt.datetime.utcnow().isoformat(), rows[-1][1]))
        con.commit()
    # Read full series from cache
    df = pd.read_sql_query(
        "SELECT date, value FROM obs WHERE series_id=? ORDER BY date",
        con, params=(series_id,)
    )
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["value"].rename(series_id)

# ============================================================================
# Z-score computation
# ============================================================================
def zscore_36m(series: pd.Series, transform: str = "level") -> pd.Series:
    """36-month rolling z-score, computed on diff for stock series, level for spreads."""
    s = series.copy()
    if transform == "diff":
        # Use change vs trailing month average to detrend
        s = s.diff()
    elif transform == "log-diff":
        s = np.log(s).diff()
    # 36-month rolling (approx 750 trading days, or 36 months)
    # Use a rolling window expressed in days that works regardless of frequency
    s_d = s.asfreq("D").ffill(limit=10)  # forward-fill weekly/monthly to daily for joint compute
    mean = s_d.rolling("1095D").mean()
    std  = s_d.rolling("1095D").std()
    z = (s_d - mean) / std
    return z

# ============================================================================
# Build the dataset
# ============================================================================
def build():
    con = init_cache()
    raw = {}
    for spec in SERIES:
        print(f"  Fetching {spec['id']:12} ({spec['label']})")
        s = fetch_series(spec["id"], con)
        raw[spec["id"]] = s

    # Build the master daily DataFrame, forward-filled
    idx = pd.date_range(start="2010-01-01", end=pd.Timestamp.utcnow().tz_localize(None), freq="D")
    df = pd.DataFrame(index=idx)
    for sid, s in raw.items():
        df[sid] = s.reindex(idx).ffill(limit=10)
    df = df.dropna(how="all")

    # NET FED LIQUIDITY = WALCL − TGA − RRP (in $bn since FRED reports in $m for WALCL, varies for others)
    # WALCL: millions of dollars
    # WTREGEN: millions of dollars (weekly avg)
    # RRPONTSYD: billions of dollars (daily)
    df["NET_FED_LIQ"] = df["WALCL"]/1000 - df["WTREGEN"]/1000 - df["RRPONTSYD"]   # all in $bn

    # Compute Z-scores for each series, sign-adjusted
    z_cols = {}
    for spec in SERIES:
        sid = spec["id"]
        z = zscore_36m(df[sid], spec["transform"]) * spec["sign"]
        z_cols[f"Z_{sid}"] = z
    z_df = pd.DataFrame(z_cols)

    # Fed sub-Z (weighted mean)
    fed_z = pd.Series(0.0, index=z_df.index)
    fed_w = 0
    for spec in [s for s in SERIES if s["kind"] == "fed"]:
        col = f"Z_{spec['id']}"
        fed_z = fed_z.add(z_df[col].fillna(0) * spec["weight"], fill_value=0)
        fed_w += spec["weight"]
    fed_z = fed_z / fed_w
    # Mask periods where the underlying isn't fully populated
    fed_valid = z_df[[f"Z_{s['id']}" for s in SERIES if s["kind"] == "fed"]].notna().mean(axis=1) > 0.5
    fed_z = fed_z.where(fed_valid)

    # Market sub-Z (weighted mean)
    mkt_z = pd.Series(0.0, index=z_df.index)
    mkt_w = 0
    for spec in [s for s in SERIES if s["kind"] == "market"]:
        col = f"Z_{spec['id']}"
        mkt_z = mkt_z.add(z_df[col].fillna(0) * spec["weight"], fill_value=0)
        mkt_w += spec["weight"]
    mkt_z = mkt_z / mkt_w
    mkt_valid = z_df[[f"Z_{s['id']}" for s in SERIES if s["kind"] == "market"]].notna().mean(axis=1) > 0.5
    mkt_z = mkt_z.where(mkt_valid)

    # Composite Liquidity Z = 50/50 blend
    liq_z = (fed_z + mkt_z) / 2

    df["FED_Z"] = fed_z
    df["MKT_Z"] = mkt_z
    df["LIQ_Z"] = liq_z

    return df, z_df

# ============================================================================
# Charts
# ============================================================================
def chart_net_fed_liquidity(df: pd.DataFrame, out_path: Path):
    fig, ax = plt.subplots(figsize=(12, 5))
    s = df["NET_FED_LIQ"].dropna().tail(365*5)  # last 5 years
    ax.plot(s.index, s.values, color="#1a365d", linewidth=1.8)
    ax.fill_between(s.index, s.values, s.values.min(), color="#1a365d", alpha=0.08)
    ax.set_title(f"NET FED LIQUIDITY  (WALCL − TGA − RRP, $bn)\nLatest: {s.iloc[-1]:,.0f}bn  ({s.index[-1].date()})", fontweight="bold")
    ax.set_ylabel("$ billions")
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()

def chart_liquidity_z(df: pd.DataFrame, out_path: Path):
    fig, ax = plt.subplots(figsize=(12, 5))
    tail = df.tail(365*5)
    ax.plot(tail.index, tail["LIQ_Z"], color="#1a365d", linewidth=2.0, label="Composite Liquidity Z")
    ax.plot(tail.index, tail["FED_Z"], color="#2c7a7b", linewidth=1.2, alpha=0.6, label="Fed Liquidity Z")
    ax.plot(tail.index, tail["MKT_Z"], color="#c0392b", linewidth=1.2, alpha=0.6, label="Market Liquidity Z")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.fill_between(tail.index, tail["LIQ_Z"], 0, where=(tail["LIQ_Z"]>0), color="green", alpha=0.08)
    ax.fill_between(tail.index, tail["LIQ_Z"], 0, where=(tail["LIQ_Z"]<0), color="red", alpha=0.08)
    latest = tail["LIQ_Z"].dropna().iloc[-1]
    ax.set_title(f"LIQUIDITY Z-SCORE  (36m rolling, +ve = easier financial conditions)\nLatest composite: {latest:+.2f}  ({tail.index[-1].date()})", fontweight="bold")
    ax.set_ylabel("Z-score (σ)")
    ax.set_ylim(-3, 3)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()

def chart_components(df: pd.DataFrame, z_df: pd.DataFrame, out_path: Path):
    """Small-multiples sparklines of each underlying."""
    fig, axes = plt.subplots(4, 3, figsize=(15, 10), sharex=True)
    axes = axes.flatten()
    tail = df.tail(365*3)
    for i, spec in enumerate(SERIES):
        ax = axes[i]
        sid = spec["id"]
        s = tail[sid].dropna()
        ax.plot(s.index, s.values, color="#1a365d", linewidth=1.4)
        ax.set_title(f"{spec['label']}", fontsize=9)
        latest = s.iloc[-1] if len(s) else float("nan")
        ax.text(0.02, 0.95, f"{latest:.2f}", transform=ax.transAxes, fontsize=8,
                verticalalignment="top", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=8)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y"))
    plt.suptitle("Component series — 3-year history", fontweight="bold", y=1.00)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()

# ============================================================================
# Dashboard HTML
# ============================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>US Nowcast — Liquidity (Phase 1)</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 24px; background: #fafafa; color: #222; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .card {{ background: white; padding: 16px; margin: 16px 0; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 14px; color: #555; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 12px; }}
  .headline {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .stat {{ flex: 1; min-width: 200px; padding: 12px; border-left: 4px solid #1a365d; background: #f8f9fa; border-radius: 4px; }}
  .stat .label {{ font-size: 11px; color: #888; text-transform: uppercase; }}
  .stat .value {{ font-size: 24px; font-weight: bold; color: #1a365d; margin: 4px 0; }}
  .stat .meta {{ font-size: 12px; color: #666; }}
  .stat.pos {{ border-left-color: #2c7a7b; }}
  .stat.pos .value {{ color: #2c7a7b; }}
  .stat.neg {{ border-left-color: #c0392b; }}
  .stat.neg .value {{ color: #c0392b; }}
  img {{ max-width: 100%; height: auto; display: block; }}
  .footer {{ color: #888; font-size: 11px; margin-top: 32px; }}
</style>
</head>
<body>
<h1>US Nowcast — Liquidity Pillar (Phase 1)</h1>
<div class="sub">Last updated {ts} UTC · Daily series last as of {last_data} · Source: FRED</div>

<div class="card">
  <h2>Headline</h2>
  <div class="headline">
    <div class="stat">
      <div class="label">NET FED LIQUIDITY</div>
      <div class="value">${net_fed:,.0f}bn</div>
      <div class="meta">WALCL − TGA − RRP</div>
    </div>
    <div class="stat {liq_class}">
      <div class="label">Liquidity Z (composite)</div>
      <div class="value">{liq_z:+.2f}σ</div>
      <div class="meta">36m rolling · {regime}</div>
    </div>
    <div class="stat {fed_class}">
      <div class="label">Fed sub-Z</div>
      <div class="value">{fed_z:+.2f}σ</div>
      <div class="meta">balance sheet flow</div>
    </div>
    <div class="stat {mkt_class}">
      <div class="label">Market sub-Z</div>
      <div class="value">{mkt_z:+.2f}σ</div>
      <div class="meta">credit + vol + rates</div>
    </div>
  </div>
</div>

<div class="card">
  <h2>NET FED LIQUIDITY ($bn) — last 5y</h2>
  <img src="charts/net_fed_liquidity.png?ts={ts_short}">
</div>

<div class="card">
  <h2>Liquidity Z-score — last 5y</h2>
  <img src="charts/liquidity_z.png?ts={ts_short}">
</div>

<div class="card">
  <h2>Component series — 3-year</h2>
  <img src="charts/components.png?ts={ts_short}">
</div>

<div class="footer">
  Built per <code>memory/macro/nowcast/us/INDICATOR-WEIGHTS.md</code> Phase 1 spec.<br>
  Phase 2 (Growth + Inflation pillars) and Phase 3 (regime grid) pending.<br>
  Source code: <code>~/.openclaw/workspace/nowcast/us/liquidity_phase1.py</code>
</div>
</body>
</html>
"""

def render_html(df: pd.DataFrame):
    chart_net_fed_liquidity(df, OUT_DIR / "net_fed_liquidity.png")
    chart_liquidity_z(df, OUT_DIR / "liquidity_z.png")
    chart_components(df, None, OUT_DIR / "components.png")

    latest = df.iloc[-1]
    liq_z = latest["LIQ_Z"]
    fed_z = latest["FED_Z"]
    mkt_z = latest["MKT_Z"]
    net_fed = latest["NET_FED_LIQ"]
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    ts_short = dt.datetime.utcnow().strftime("%Y%m%d%H%M")

    def cls(z):
        if pd.isna(z): return ""
        return "pos" if z > 0.3 else ("neg" if z < -0.3 else "")
    def regime(z):
        if pd.isna(z): return "n/a"
        if z > 1.0: return "easy"
        if z > 0.3: return "modestly easy"
        if z > -0.3: return "neutral"
        if z > -1.0: return "modestly tight"
        return "tight"

    html = HTML_TEMPLATE.format(
        ts=ts, ts_short=ts_short,
        last_data=df.dropna(subset=["LIQ_Z"]).index[-1].date(),
        net_fed=net_fed, liq_z=liq_z, fed_z=fed_z, mkt_z=mkt_z,
        liq_class=cls(liq_z), fed_class=cls(fed_z), mkt_class=cls(mkt_z),
        regime=regime(liq_z),
    )
    OUT_HTML.write_text(html)
    print(f"Wrote {OUT_HTML}")
    return liq_z, fed_z, mkt_z, net_fed

if __name__ == "__main__":
    print("Building US Nowcast Liquidity dashboard...")
    df, z_df = build()
    liq_z, fed_z, mkt_z, net_fed = render_html(df)
    print(f"\nLatest readings:")
    print(f"  NET FED LIQUIDITY: ${net_fed:,.0f}bn")
    print(f"  Liquidity Z:       {liq_z:+.2f}")
    print(f"  Fed sub-Z:         {fed_z:+.2f}")
    print(f"  Market sub-Z:      {mkt_z:+.2f}")
