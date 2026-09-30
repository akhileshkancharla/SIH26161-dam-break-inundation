"""Pure helpers for the Streamlit dashboard (testable without Streamlit)."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer

# Hydrographic depth classes from the dashboard design system: cyan shallow
# -> blue -> amber -> red -> magenta-crimson for extreme depths.
HYDRO_EDGES = [0.1, 0.5, 1.5, 3.0, 6.0, np.inf]
HYDRO_COLORS = ["#38BDF8", "#2563EB", "#D97706", "#DC2626", "#C026D3"]


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

    Dry/NaN cells become fully transparent; wet cells use the design
    system's hydro ramp (cyan shallow -> magenta-crimson extreme) as
    discrete depth classes.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.colors import BoundaryNorm, ListedColormap

    d = np.asarray(depth, dtype=float)
    wet = np.nan_to_num(d, nan=0.0) > 0
    vmax = float(np.nanmax(d)) if wet.any() else 1.0
    edges = [0.1, 0.5, 1.5, 3.0, 6.0]
    if vmax <= edges[-1]:
        edges = [e for e in edges if e < vmax] + [vmax]
    if len(edges) < 2:
        edges = [0.0, max(vmax, 0.1)]
    cmap = ListedColormap(HYDRO_COLORS[:len(edges) - 1])
    norm = BoundaryNorm(edges, cmap.N, clip=True)
    rgba = cmap(norm(np.nan_to_num(d, nan=0.0)))
    rgba[..., 3] = np.where(wet, 235, 0)

    h, w = d.shape
    scale = max(1, int(np.ceil(max(w, h) / max_px)))
    rgb = rgba[::scale, ::scale]
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray((rgb * 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue(), wgs84_bounds(d.shape, transform, crs)


def kpi_stats(run_dir: str | Path) -> dict:
    """Headline numbers from a pipeline run's screening rasters."""
    import rasterio

    run_dir = Path(run_dir)
    sdir = run_dir / "screening"
    out: dict = {}
    with rasterio.open(sdir / "depth_max.tif") as ds:
        depth = ds.read(1)
        cell = abs(ds.transform.a * ds.transform.e)
    wet = np.isfinite(depth) & (depth > 0)
    out["wet_area_km2"] = float(wet.sum() * cell / 1e6)
    out["wet_cells"] = int(wet.sum())
    out["peak_depth_m"] = float(np.nanmax(depth)) if wet.any() else 0.0
    vel_p = sdir / "velocity_max.tif"
    if vel_p.exists():
        with rasterio.open(vel_p) as ds:
            out["max_velocity_ms"] = float(np.nanmax(ds.read(1)))
    arr_p = sdir / "arrival_min.tif"
    if arr_p.exists():
        with rasterio.open(arr_p) as ds:
            arrival = ds.read(1)
        wet_arr = arrival[wet & np.isfinite(arrival)]
        if wet_arr.size:
            # wave-front time at the farthest downstream wet cell
            out["arrival_front_min"] = float(np.nanmax(wet_arr))
            out["arrival_dam_min"] = float(np.nanmin(wet_arr))
    return out


def hydrograph_figure(t_s: np.ndarray, q: np.ndarray,
                      failure_time_s: float | None = None,
                      peak_flow_m3s: float | None = None):
    """Dark-styled breach hydrograph Q(t) for st.pyplot."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=140)
    fig.patch.set_facecolor("#111827")
    ax.set_facecolor("#0B0F19")
    t_h = np.asarray(t_s) / 3600.0
    q = np.asarray(q)
    ax.fill_between(t_h, q, color="#0284C7", alpha=0.22, lw=0)
    ax.plot(t_h, q, color="#38BDF8", lw=2.0, solid_capstyle="round")
    if failure_time_s:
        ax.axvline(failure_time_s / 3600.0, color="#D97706", lw=1.2, ls="--")
        ax.annotate(f"tf = {failure_time_s/60:.0f} min",
                    xy=(failure_time_s / 3600.0, 0.96), xycoords=("data", "axes fraction"),
                    color="#FCD34D", fontsize=9,
                    family="monospace", ha="left", va="top",
                    xytext=(4, 0), textcoords="offset points")
    if peak_flow_m3s:
        ax.axhline(peak_flow_m3s, color="#DC2626", lw=1.0, ls=":")
        ax.annotate(f"Qp = {peak_flow_m3s:,.0f} m3/s",
                    xy=(0.985, peak_flow_m3s), xycoords=("axes fraction", "data"),
                    color="#FCA5A5", fontsize=9, family="monospace",
                    ha="right", va="bottom")
    ax.set_xlabel("time since breach (h)", color="#94A3B8", fontsize=9,
                  family="monospace")
    ax.set_ylabel("Q (m3/s)", color="#94A3B8", fontsize=9, family="monospace")
    ax.grid(color="#1F2937", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#374151")
    ax.tick_params(colors="#94A3B8", labelsize=8)
    fig.tight_layout()
    return fig


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
