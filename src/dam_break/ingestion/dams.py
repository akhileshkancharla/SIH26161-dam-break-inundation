"""Local dam registry (demo subset of the NRLD / GeoDAR inventories).

The CSV at configs/datasets/dams_india.csv holds a small curated table of
Indian dams. Values are demo-grade: coordinates are close but attribute
numbers (height, storage) must be verified against the National Register of
Large Dams (CWC) and GeoDAR v1.1 before being quoted in results. See
docs/verification-log.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..paths import repo_root

_CACHE: pd.DataFrame | None = None


def registry_path() -> Path:
    return repo_root() / "configs" / "datasets" / "dams_india.csv"


def load_registry() -> pd.DataFrame:
    global _CACHE
    if _CACHE is None:
        path = registry_path()
        if not path.exists():
            raise FileNotFoundError(f"dam registry not found at {path}")
        _CACHE = pd.read_csv(path)
    return _CACHE


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def lookup_dam(name: str) -> dict | None:
    """Case/punctuation-insensitive lookup; returns the registry row as dict."""
    df = load_registry()
    target = _normalize(name)
    keys = df["name"].map(_normalize)
    hit = df.index[keys == target]
    if len(hit) == 0:
        # Substring fallback (e.g. "machhu" -> "Machhu-II").
        hit = df.index[keys.str.contains(target, regex=False)]
    if len(hit) == 0:
        return None
    row = df.loc[hit[0]].where(pd.notna(df.loc[hit[0]]), None).to_dict()
    return row
