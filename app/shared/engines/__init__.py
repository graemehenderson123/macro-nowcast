"""Bridge into the country engine packages.

The compute logic lives in the country folders next to the app (e.g.
``nowcast/us/*.py``). This package adds those folders to ``sys.path`` on
import so the app can call ``from shared.engines.us import growth_phase2``.

Deployment note: on Streamlit Cloud the ``nowcast/us`` folder is copied
into the repo root alongside ``nowcast/app``, so the same relative path
works locally and in the cloud.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Directory that contains all country engine folders (../../ from here).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_COUNTRIES = {
    "us": _REPO_ROOT / "us",
    # future: "uk": _REPO_ROOT / "uk", etc.
}

for _name, _path in _COUNTRIES.items():
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
