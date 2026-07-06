#!/usr/bin/env python3
"""
US Nowcast — shared core utilities.

Provides:
  - FRED API key loading
  - SQLite cache (obs + meta) with configurable TTL for reruns (default 4h)
  - fetch_series() with graceful skip on 404/discontinued series
  - zscore_36m() with transforms level/diff/log-diff/mom/yoy
  - build_pillar() generic weighted composite over a series catalogue
  - HTML helpers (colour class from Z, formatted number, etc.)
"""
from __future__ import annotations
import os, json, sqlite3, datetime as dt, time
from pathlib import Path
from typing import Iterable
import pandas as pd
import numpy as np
import requests

ROOT = Path(__file__).parent
DB = ROOT / "fred_cache.sqlite"
CHARTS = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)

ENV_FILE = ROOT.parent.parent / ".env"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
# On Streamlit Cloud we want fresh data quickly after a release drops on FRED.
# FRED has no meaningful rate-limit, so keep this short. Local batch runs
# can override via NOWCAST_CACHE_TTL_SECS env var if needed.
CACHE_TTL_SECS = int(os.environ.get("NOWCAST_CACHE_TTL_SECS", 4 * 3600))  # 4h default

# ---------------------------------------------------------------------------
def load_fred_key() -> str:
    # 1. env var wins (Streamlit Cloud sets this via st.secrets bridge, or
    #    the OS env for local dev / CI)
    env_key = os.environ.get("FRED_API_KEY")
    if env_key:
        return env_key.strip()
    # 2. fall back to the workspace .env file
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("FRED_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        "FRED_API_KEY not found — set the env var or add it to .env"
    )

FRED_KEY = load_fred_key()

# ---------------------------------------------------------------------------
def init_cache() -> sqlite3.Connection:
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
      last_obs_date TEXT,
      status TEXT
    );
    """)
    # Ensure status column exists on old caches
    cols = [r[1] for r in con.execute("PRAGMA table_info(meta)").fetchall()]
    if "status" not in cols:
        con.execute("ALTER TABLE meta ADD COLUMN status TEXT")
    con.commit()
    return con

SKIPPED: list[tuple[str, str]] = []  # (series_id, reason)

def _cache_fresh(con: sqlite3.Connection, series_id: str) -> bool:
    row = con.execute("SELECT last_fetched FROM meta WHERE series_id=?", (series_id,)).fetchone()
    if not row or not row[0]:
        return False
    try:
        ts = dt.datetime.fromisoformat(row[0])
    except ValueError:
        return False
    age = (dt.datetime.utcnow() - ts).total_seconds()
    return age < CACHE_TTL_SECS


def fetch_series(series_id: str, con: sqlite3.Connection, start: str = "2005-01-01",
                 required: bool = True) -> pd.Series | None:
    """Fetch observations from FRED with 24h cache TTL. Returns None on 404/skip.

    If required=False and the series doesn't exist on FRED (400/404), we log
    to SKIPPED and return None instead of raising.
    """
    # Load from cache first
    def load_from_cache() -> pd.Series:
        df = pd.read_sql_query(
            "SELECT date, value FROM obs WHERE series_id=? ORDER BY date",
            con, params=(series_id,)
        )
        if df.empty:
            return pd.Series(dtype=float, name=series_id)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")["value"].astype(float).rename(series_id)

    # If cached and fresh, skip refetch
    if _cache_fresh(con, series_id):
        s = load_from_cache()
        if not s.empty:
            return s

    # Determine start date
    last_obs_row = con.execute("SELECT MAX(date) FROM obs WHERE series_id=?", (series_id,)).fetchone()
    last_obs = last_obs_row[0] if last_obs_row else None
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "sort_order": "asc",
    }
    if last_obs:
        params["observation_start"] = (dt.date.fromisoformat(last_obs) - dt.timedelta(days=90)).isoformat()
    else:
        params["observation_start"] = start

    try:
        r = requests.get(FRED_URL, params=params, timeout=30)
        if r.status_code in (400, 404):
            SKIPPED.append((series_id, f"FRED {r.status_code}: {r.text[:120]}"))
            print(f"    [skip] {series_id}: HTTP {r.status_code}")
            return None
        r.raise_for_status()
        data = r.json().get("observations", [])
    except requests.RequestException as e:
        # Fall back to cache if we have anything
        s = load_from_cache()
        if not s.empty:
            print(f"    [warn] {series_id}: {e} — using cached data")
            return s
        SKIPPED.append((series_id, f"network: {e}"))
        return None

    rows = [(series_id, o["date"], float(o["value"])) for o in data if o["value"] not in (".", "")]
    if rows:
        con.executemany("INSERT OR REPLACE INTO obs VALUES (?,?,?)", rows)
    con.execute(
        "INSERT OR REPLACE INTO meta VALUES (?,?,?,?)",
        (series_id, dt.datetime.utcnow().isoformat(),
         rows[-1][1] if rows else last_obs, "ok"),
    )
    con.commit()
    # small delay to be polite (~120/min limit)
    time.sleep(0.05)
    return load_from_cache()

# ---------------------------------------------------------------------------
def _apply_transform(s: pd.Series, transform: str) -> pd.Series:
    """Convert raw series to the analytical basis specified by transform.

    Supported transforms:
      level       — as-is (spreads, levels)
      diff        — first difference (change vs prior obs, flow measure)
      log-diff    — log first difference
      mom         — month-over-month % change (for monthly series)
      yoy         — 12-month % change  (for monthly series)
      dyoy        — YoY difference in level (for indices already in %/index units)
    """
    s = s.dropna()
    if transform == "level":
        return s
    if transform == "diff":
        return s.diff()
    if transform == "log-diff":
        return np.log(s.where(s > 0)).diff()
    if transform in ("mom",):
        return s.pct_change() * 100.0
    if transform in ("yoy",):
        return s.pct_change(12) * 100.0
    if transform == "dyoy":
        return s.diff(12)
    raise ValueError(f"Unknown transform {transform!r}")


def zscore_36m(series: pd.Series, transform: str = "level",
               daily_ffill_limit: int = 45) -> pd.Series:
    """36-month rolling z-score on chosen transform, resampled to daily.

    We (a) apply the transform on the series in its native frequency, (b)
    resample to daily and forward-fill for a bounded window so pillar Zs can
    be blended on a common index, and (c) compute a rolling window of ~36
    months (1095 calendar days).
    """
    s = _apply_transform(series, transform)
    if s.empty:
        return pd.Series(dtype=float)
    s_d = s.asfreq("D").ffill(limit=daily_ffill_limit)
    mean = s_d.rolling("1095D", min_periods=60).mean()
    std = s_d.rolling("1095D", min_periods=60).std()
    z = (s_d - mean) / std
    return z


# ---------------------------------------------------------------------------
def build_composite(zs: dict[str, pd.Series], weights: dict[str, float]) -> pd.Series:
    """Weighted composite of Z series, with weights normalised to sum=1.

    Missing values in any component are treated as 0 contribution and the
    denominator for that timestamp drops that component's weight. This means
    a partial set still produces a reasonable composite.
    """
    if not zs:
        return pd.Series(dtype=float)
    # Common index
    idx = None
    for s in zs.values():
        idx = s.index if idx is None else idx.union(s.index)
    if idx is None or len(idx) == 0:
        return pd.Series(dtype=float)
    numer = pd.Series(0.0, index=idx)
    denom = pd.Series(0.0, index=idx)
    for sid, s in zs.items():
        w = weights.get(sid, 0.0)
        if w == 0:
            continue
        s_al = s.reindex(idx)
        mask = s_al.notna()
        numer = numer.add(s_al.where(mask, 0.0) * w, fill_value=0.0)
        denom = denom.add(mask.astype(float) * w, fill_value=0.0)
    out = numer / denom.where(denom > 0)
    return out


def breadth(zs: dict[str, pd.Series]) -> pd.Series:
    """% of component Zs currently > 0, on daily index."""
    if not zs:
        return pd.Series(dtype=float)
    idx = None
    for s in zs.values():
        idx = s.index if idx is None else idx.union(s.index)
    pos = pd.Series(0.0, index=idx)
    tot = pd.Series(0.0, index=idx)
    for s in zs.values():
        a = s.reindex(idx)
        m = a.notna()
        pos = pos.add((a > 0).where(m, 0).astype(float), fill_value=0)
        tot = tot.add(m.astype(float), fill_value=0)
    return (pos / tot.where(tot > 0)) * 100.0


# ---------------------------------------------------------------------------
def z_color_class(z: float | None) -> str:
    if z is None or (isinstance(z, float) and (pd.isna(z))):
        return ""
    if z > 0.25:
        return "pos"
    if z < -0.25:
        return "neg"
    return "neu"


def fmt_z(z: float | None) -> str:
    if z is None or (isinstance(z, float) and pd.isna(z)):
        return "—"
    return f"{z:+.2f}σ"


def top_movers(z_now: dict[str, float], z_4w: dict[str, float],
               labels: dict[str, str], n: int = 5) -> list[dict]:
    """Return top N absolute-change movers over 4 weeks."""
    rows = []
    for k, now in z_now.items():
        if pd.isna(now):
            continue
        prev = z_4w.get(k, np.nan)
        chg = now - prev if not pd.isna(prev) else np.nan
        rows.append({"id": k, "label": labels.get(k, k), "z_now": now,
                     "z_prev": prev, "chg": chg})
    rows = [r for r in rows if not pd.isna(r["chg"])]
    rows.sort(key=lambda r: abs(r["chg"]), reverse=True)
    return rows[:n]


# ---------------------------------------------------------------------------
def normalise_weights(specs: list[dict]) -> None:
    """In-place: rewrite spec[i]['weight'] so weights within a pillar sum to 1.

    Uses tier if present as a fallback, else weight already given.
    """
    tier_w = {"A": 1.0, "B": 0.7, "C": 0.5, "D": 0.3, "E": 0.15}
    for spec in specs:
        if "weight" not in spec and "tier" in spec:
            spec["weight"] = tier_w[spec["tier"]]
    total = sum(s["weight"] for s in specs)
    if total <= 0:
        return
    for s in specs:
        s["weight_norm"] = s["weight"] / total


# ---------------------------------------------------------------------------
# HTML style block reused across dashboards
# ---------------------------------------------------------------------------
CSS = """
  body { font-family: -apple-system, system-ui, Segoe UI, Roboto, sans-serif;
         margin: 0; padding: 24px; background: #fafafa; color: #222; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 14px; color: #555; text-transform: uppercase; letter-spacing: 0.5px; margin: 0 0 12px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .card { background: white; padding: 16px; margin: 12px 0; border-radius: 8px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  .stat { padding: 12px; border-left: 4px solid #1a365d; background: #f8f9fa;
          border-radius: 4px; }
  .stat .label { font-size: 11px; color: #888; text-transform: uppercase; }
  .stat .value { font-size: 24px; font-weight: bold; color: #1a365d; margin: 4px 0; }
  .stat .meta { font-size: 12px; color: #666; }
  .stat.pos { border-left-color: #2c7a7b; }
  .stat.pos .value { color: #2c7a7b; }
  .stat.neg { border-left-color: #c0392b; }
  .stat.neg .value { color: #c0392b; }
  .stat.neu { border-left-color: #999; }
  .stat.neu .value { color: #555; }
  .regime-card { padding: 24px; border-radius: 12px; }
  .regime-label { font-size: 32px; font-weight: 800; letter-spacing: 0.5px; }
  .regime-sub { font-size: 14px; opacity: 0.9; }
  .regime-strip { display: flex; gap: 2px; margin-top: 16px; }
  .regime-strip .cell { flex: 1; height: 24px; border-radius: 3px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }
  th { color: #666; font-weight: 600; font-size: 11px; text-transform: uppercase; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td.pos { color: #2c7a7b; font-weight: 600; }
  td.neg { color: #c0392b; font-weight: 600; }
  td.neu { color: #666; }
  img { max-width: 100%; height: auto; display: block; }
  .footer { color: #888; font-size: 11px; margin-top: 32px; }
  .pillar-h { display: flex; gap: 12px; flex-wrap: wrap; align-items: baseline; }
  .pillar-h h1 { margin: 0; }
  .pillar-h .z { font-size: 28px; font-weight: 800; }
  .z.pos { color: #2c7a7b; }
  .z.neg { color: #c0392b; }
  .z.neu { color: #555; }
  .stale { color: #b7791f; font-size: 10px; }
"""
