"""Pure helpers for the Streamlit dashboard (testable without Streamlit)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer


def wgs84_bounds(shape: tuple[int, int], transform, crs) -> tuple[float, float, float, float]:
    """(west, south, east, north) of a north-up raster in EPSG:4326."""
    rows, cols = shape
    x0 = transform.c
    x1 = transform.c + transform.a * cols
    y1 = transform.f
    y0 = transform.f + transform.e * rows
    src = CRS.from_user_input(crs)
    if src.to_epsg() == 4326:
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    fwd = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    lons, lats = [], []
    for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1)):
        lon, lat = fwd.transform(x, y)
        lons.append(lon)
        lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def depth_png_bytes(depth: np.ndarray, transform, crs,
                    max_px: int = 1400) -> tuple[bytes, tuple[float, float, float, float]]:
    """Transparent-background PNG of the depth raster + its WGS84 bounds.

    Dry/NaN cells become fully transparent so the PNG overlays cleanly on
    a web map; wet cells use a YlGnBu ramp clipped to the raster maximum.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors

    d = np.asarray(depth, dtype=float)
    vmax = float(np.nanmax(d)) if np.isfinite(d).any() else 1.0
    vmax = vmax if vmax > 0 else 1.0
    norm = mcolors.Normalize(vmin=0.0, vmax=vmax, clip=True)
    rgba = cm.YlGnBu(norm(np.nan_to_num(d, nan=0.0)))
    rgba[..., 3] = np.where(np.nan_to_num(d, nan=0.0) > 0, 235, 0)

    h, w = d.shape
    scale = max(1, int(np.ceil(max(w, h) / max_px)))
    rgb = rgba[::scale, ::scale]
    from PIL import Image  # Pillow ships with matplotlib's stack
    buf = io.BytesIO()
    Image.fromarray((rgb * 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue(), wgs84_bounds(d.shape, transform, crs)


def scenario_from_registry(dam_name: str, scenario_id: str | None = None,
                           **overrides) -> dict:
    """Dashboard-facing scenario dict for a registry dam (guide Section 10.5:
    one JSON drives everything - this is the same schema load_scenario reads)."""
    from ..ingestion.dams import lookup_dam

    hit = lookup_dam(dam_name)
    if hit is None:
        raise ValueError(f"dam '{dam_name}' not in the registry")
    dam: dict = {"name": hit["name"]}
    for k in ("height_m", "storage_mcm"):
        v = hit.get(k)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            dam.setdefault("override", {})[k] = float(v)
    for k, v in overrides.items():
        dam.setdefault("override", {})[k] = v
    return {
        "scenario_id": scenario_id or _slug(dam_name),
        "description": f"dashboard scenario for {hit['name']} "
                       f"({hit.get('river', '')}, {hit.get('state', '')})",
        "dam": dam,
        "solvers": ["screening"],
        "exports": ["shp", "kml", "gpkg", "tif", "csv"],
    }


def _slug(name: str) -> str:
    return (name.lower().replace(" ", "_").replace("-", "_")
            .replace("ii", "2").replace("iii", "3"))


def list_run_artifacts(run_dir: str | Path) -> dict[str, list[Path]]:
    """Group a pipeline run directory's downloadable files by kind."""
    run_dir = Path(run_dir)
    groups: dict[str, list[Path]] = {
        "GeoTIFF": [], "Shapefile (zip)": [], "KML": [], "GeoPackage": [],
        "Tables (CSV/JSON)": [], "Maps (PNG)": [],
    }
    if not run_dir.is_dir():
        return {}
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.stat().st_size > 200 * 1024 * 1024:
            continue
        s = p.suffix.lower()
        if s == ".tif":
            groups["GeoTIFF"].append(p)
        elif s == ".zip":
            groups["Shapefile (zip)"].append(p)
        elif s == ".kml":
            groups["KML"].append(p)
        elif s == ".gpkg":
            groups["GeoPackage"].append(p)
        elif s in (".csv", ".json"):
            groups["Tables (CSV/JSON)"].append(p)
        elif s == ".png":
            groups["Maps (PNG)"].append(p)
    return {k: v for k, v in groups.items() if v}
