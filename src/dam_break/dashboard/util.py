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
    png, bounds, _ = layer_png_bytes(depth, transform, crs, "depth", max_px=max_px)
    return png, bounds


# Map layers the results page can show: discrete classes or a continuous ramp.
DEPTH_LABELS = ["0.1–0.5 m", "0.5–1.5 m", "1.5–3 m", "3–6 m", "over 6 m"]
ARRIVAL_COLORS = ["#F43F5E", "#FB923C", "#FACC15", "#A3E635", "#38BDF8"]
VELOCITY_COLORS = ["#7DD3FC", "#FACC15", "#F97316", "#DC2626"]
HAZARD_COLORS = ["#FACC15", "#F97316", "#DC2626"]
HAZARD_LABELS = ["low", "medium", "high"]
LAYER_TITLES = {"depth": "Maximum depth (m)", "arrival": "Arrival time (min after breach)",
                "velocity": "Maximum velocity (m/s)", "hazard": "Hazard class"}


def _ramp(values: np.ndarray, colors: list[str], vmin: float, vmax: float) -> np.ndarray:
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("ramp", colors)
    span = max(vmax - vmin, 1e-9)
    return cmap(np.clip((values - vmin) / span, 0.0, 1.0))


def layer_rgba(arr: np.ndarray, kind: str,
               mask: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """RGBA (floats 0-1) for a result layer, plus a legend description.

    kind: depth | arrival | velocity | hazard. Cells that are NaN, dry
    (<= 0; hazard class 0) or outside ``mask`` are transparent.
    """
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.colors import to_rgba

    a = np.asarray(arr, dtype=float)
    finite = np.isfinite(a)
    vals = np.where(finite, a, 0.0)
    if kind == "depth":
        show = vals > HYDRO_EDGES[0]   # same wet threshold as the solvers' area figures
        idx = np.clip(np.digitize(vals, HYDRO_EDGES[1:-1]), 0, len(HYDRO_COLORS) - 1)
        rgba = np.array([to_rgba(c) for c in HYDRO_COLORS])[idx]
        legend = {"type": "classes", "colors": HYDRO_COLORS, "labels": DEPTH_LABELS}
    elif kind == "hazard":
        show = vals >= 1
        idx = np.clip(vals.astype(int) - 1, 0, 2)
        rgba = np.array([to_rgba(c) for c in HAZARD_COLORS])[idx]
        legend = {"type": "classes", "colors": HAZARD_COLORS, "labels": HAZARD_LABELS}
    else:
        show = finite & ((vals > 0) if kind == "velocity" else np.ones_like(finite))
        colors = ARRIVAL_COLORS if kind == "arrival" else VELOCITY_COLORS
        data = vals[show]
        vmin = float(data.min()) if data.size else 0.0
        vmax = float(np.percentile(data, 99)) if data.size else 1.0
        if kind == "arrival" and data.size:
            vmax = float(data.max())
        rgba = _ramp(vals, colors, vmin, vmax)
        legend = {"type": "ramp", "colors": colors, "vmin": vmin, "vmax": vmax}
    show = show & finite
    if mask is not None:
        show = show & mask
    rgba[..., 3] = np.where(show, 0.92, 0.0)
    legend["title"] = LAYER_TITLES.get(kind, kind)
    return rgba, legend


def layer_png_bytes(arr: np.ndarray, transform, crs, kind: str,
                    mask: np.ndarray | None = None, max_px: int = 1400
                    ) -> tuple[bytes, tuple[float, float, float, float], dict]:
    """PNG overlay (transparent where dry), WGS84 bounds and legend for a layer."""
    from PIL import Image

    rgba, legend = layer_rgba(arr, kind, mask)
    h, w = rgba.shape[:2]
    scale = max(1, int(np.ceil(max(w, h) / max_px)))
    img = (rgba[::scale, ::scale] * 255).round().astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue(), wgs84_bounds(np.shape(arr), transform, crs), legend


def depth_class_areas(depth: np.ndarray, cell_area_m2: float,
                      mask: np.ndarray | None = None) -> list[dict]:
    """Flooded area (ha) per map depth class (cells deeper than 0.1 m, as in the
    solver diagnostics), matching the map colours."""
    d = np.nan_to_num(np.asarray(depth, dtype=float), nan=0.0)
    wet = d > HYDRO_EDGES[0]
    if mask is not None:
        wet &= mask
    idx = np.clip(np.digitize(d[wet], HYDRO_EDGES[1:-1]), 0, len(HYDRO_COLORS) - 1)
    counts = np.bincount(idx, minlength=len(HYDRO_COLORS))
    return [{"label": lab, "color": col, "area_ha": float(n * cell_area_m2 / 1e4)}
            for lab, col, n in zip(DEPTH_LABELS, HYDRO_COLORS, counts)]


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
