"""End-to-end pipeline: scenario JSON -> outputs directory.

Stages: resolve dam -> fetch DEM (AOI auto-derived around the downstream
corridor) -> optional land cover -> breach parameters and hydrograph ->
solvers -> rasters, polygons, exports, exposure, quick-look maps, summary.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio.warp
from pyproj import CRS

from .breach import breach_parameters, hydrograph_from_breach, hydrograph_volume
from .config import Scenario
from .paths import repo_root
from .ingestion.dem import fetch_dem
from .ingestion.landcover import fetch_worldcover_gee
from .postprocess.polygons import depth_polygons, export_vectors
from .postprocess.rasters import write_layer, classify_hazard
from .preparation.roughness import roughness_from_landcover
from .solvers.base import SolverResult
from .visualize import plot_hydrograph, plot_raster


def _bbox_around(lat: float, lon: float, half_deg: float) -> tuple[float, float, float, float]:
    return (lon - half_deg, lat - half_deg, lon + half_deg, lat + half_deg)


def _dam_rowcol(dem, lat: float, lon: float) -> tuple[int, int]:
    xs, ys = rasterio.warp.transform("EPSG:4326", dem.crs, [lon], [lat])
    x, y = xs[0], ys[0]
    inv = ~dem.transform
    col, row = inv * (x, y)
    r = int(np.clip(row, 0, dem.shape[0] - 1))
    c = int(np.clip(col, 0, dem.shape[1] - 1))
    return r, c


def _clip_to_corridor(dem, dam_rc, length_km: float, width_km: float):
    """Return a DEM clipped to a window spanning the downstream corridor."""
    from .preparation.terrain import priority_flood_fill, trace_flow_path, coarsen
    from rasterio.windows import Window

    cell = abs(dem.transform.a)
    # Window centred on the dam, sized to hold `length_km` in any direction
    # (the river direction is unknown before tracing).
    half = int((length_km * 1000.0 * 1.25) / cell)
    r0 = max(dam_rc[0] - half // 2, 0)
    c0 = max(dam_rc[1] - half // 2, 0)
    r1 = min(dam_rc[0] + half // 2 + 1, dem.shape[0])
    c1 = min(dam_rc[1] + half // 2 + 1, dem.shape[1])
    window = Window(c0, r0, c1 - c0, r1 - r0)
    from rasterio.transform import Affine
    transform = dem.transform @ Affine.translation(c0, r0)
    z = dem.z[r0:r1, c0:c1]
    from .ingestion.dem import DEMData
    clipped = DEMData(z=z, transform=transform, crs=dem.crs,
                      source=dem.source, bbox_wgs84=dem.bbox_wgs84)
    return clipped, (dam_rc[0] - r0, dam_rc[1] - c0)


def run_pipeline(scenario: Scenario | str | Path | dict, out_root: str | Path | None = None,
                 quiet: bool = False) -> dict[str, Any]:
    """Run a scenario end to end; returns the summary dict."""
    from .config import load_scenario

    if not isinstance(scenario, Scenario):
        scenario = load_scenario(scenario)

    t0 = time.time()
    log = lambda msg: None if quiet else print(f"[{scenario.scenario_id}] {msg}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(out_root) if out_root else repo_root() / "outputs"
    run_dir = out_dir / scenario.scenario_id / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"run directory: {run_dir}")

    # --- terrain -------------------------------------------------------------
    dam = scenario.dam
    length_km = scenario.terrain.corridor_length_km
    fetch_deg = length_km * 1.6 / 111.0
    bbox = _bbox_around(dam.lat, dam.lon, fetch_deg)
    log(f"fetching DEM ({scenario.terrain.dem}) over bbox {bbox}")
    dem = fetch_dem(scenario.terrain, bbox)
    dem_rc = _dam_rowcol(dem, dam.lat, dam.lon)
    dem, dam_rc = _clip_to_corridor(dem, dem_rc, length_km, scenario.terrain.corridor_width_km)
    log(f"DEM grid {dem.shape} @ {abs(dem.transform.a):.0f} m ({dem.source})")
    if np.isnan(dem.z).all():
        raise RuntimeError("DEM came back empty; check dam coordinates")

    # --- land cover / roughness -----------------------------------------------
    landcover = None
    n_map: np.ndarray | float = scenario.roughness.default_n
    if scenario.roughness.landcover == "worldcover_gee":
        log("fetching ESA WorldCover (GEE)")
        try:
            landcover = fetch_worldcover_gee(dem)
            n_map = roughness_from_landcover(landcover, scenario.roughness.default_n)
        except Exception as exc:  # GEE auth/network failures must not kill the run
            log(f"WorldCover fetch failed ({exc}); using uniform n")
    from .solvers.base import RasterLayer
    if "tif" in scenario.exports:
        write_layer(run_dir / "dem_utm.tif",
                    RasterLayer(dem.z, dem.transform, dem.crs, "m", "elevation"))
        if landcover is not None:
            write_layer(run_dir / "landcover.tif",
                        RasterLayer(landcover, dem.transform, dem.crs, "class", "WorldCover"))

    # --- breach ---------------------------------------------------------------
    log("computing breach parameters")
    breach = breach_parameters(
        mode=scenario.breach.mode,
        case=scenario.breach.case,
        storage_m3=dam.storage_m3,
        release_fraction=scenario.breach.release_fraction,
        dam_height_m=dam.height_m,
        dam_length_m=dam.length_m,
        failure_fraction=scenario.breach.failure_fraction,
        method=scenario.breach.method,
    )
    t, q = hydrograph_from_breach(breach, dt_s=scenario.run.dt_s,
                                  duration_h=scenario.run.duration_h)
    volume = hydrograph_volume(t, q)
    import pandas as pd
    pd.DataFrame({"t_s": t, "q_m3s": q}).to_csv(run_dir / "hydrograph.csv", index=False)
    plot_hydrograph(t, q, run_dir / "hydrograph.png",
                    f"Breach hydrograph — {dam.name} ({scenario.breach.case})")
    log(f"Qp={breach.peak_flow_m3s:,.0f} m3/s, tf={breach.failure_time_min:.0f} min, "
        f"V={volume/1e6:.1f} Mm3")

    # --- solvers ---------------------------------------------------------------
    from .solvers.screening import run_screening
    results: dict[str, SolverResult] = {}
    for solver in scenario.solvers:
        if solver == "screening":
            log("running screening solver (volume-fill)")
            results[solver] = run_screening(
                dem=dem,
                dam_rowcol=dam_rc,
                breach=breach,
                volume_m3=volume,
                n_map=n_map,
                corridor_width_m=scenario.terrain.corridor_width_km * 1000.0 / 2.0,
                attenuation_km=scenario.run.attenuation_km,
            )
        elif solver == "delft3d_fm":
            from .solvers.delft3d.adapter import run_delft3d
            results[solver] = run_delft3d(dem, dam_rc, breach, t, q, n_map, run_dir)
        elif solver == "dualsphysics":
            from .solvers.sph.adapter import run_sph
            results[solver] = run_sph(dem, dam_rc, breach, run_dir)
        for note in results[solver].notes:
            log(f"  note: {note}")

    # --- outputs ---------------------------------------------------------------
    exports_written: dict[str, dict[str, str]] = {}
    summaries: dict[str, Any] = {}
    for name, res in results.items():
        sdir = run_dir / name
        sdir.mkdir(exist_ok=True)
        for lname, layer in res.layers.items():
            if "tif" in scenario.exports or lname == "depth_max":
                write_layer(sdir / f"{lname}.tif", layer)
        plots = {}
        if "depth_max" in res.layers:
            plot_raster(res.layers["depth_max"].array, dem.transform,
                        sdir / "depth_max.png",
                        f"Max depth — {dam.name} ({name})", "m",
                        hillshade_under=dem.z)
            plots["depth_max.png"] = str(sdir / "depth_max.png")
            if "arrival_min" in res.layers:
                plot_raster(res.layers["arrival_min"].array, dem.transform,
                            sdir / "arrival_min.png",
                            f"Arrival time — {dam.name} ({name})", "min",
                            cmap="viridis", hillshade_under=dem.z)
                plots["arrival_min.png"] = str(sdir / "arrival_min.png")
            if "tif" in scenario.exports and "velocity_max" in res.layers:
                write_layer(sdir / "hazard_class.tif",
                            RasterLayer(classify_hazard(
                                res.layers["depth_max"].array,
                                res.layers["velocity_max"].array),
                                dem.transform, dem.crs, "class",
                                "hazard class (0 dry, 1 low, 2 medium, 3 high)",
                                nodata=0))
            gdf = depth_polygons(res.layers["depth_max"].array, dem.transform, dem.crs)
            if not gdf.empty:
                vectors = export_vectors(gdf, sdir, f"{scenario.scenario_id}_{name}",
                                         [f for f in scenario.exports
                                          if f in ("shp", "kml", "gpkg", "geojson")],
                                         name=f"{dam.name} {name}")
                exports_written[name] = {k: str(v) for k, v in vectors.items()}
                if "csv" in scenario.exports:
                    import pandas as pd
                    gdf.drop(columns="geometry").to_csv(
                        sdir / f"{scenario.scenario_id}_{name}_classes.csv", index=False)
            summaries[name] = {"diagnostics": res.diagnostics, "notes": res.notes,
                               "plots": plots}
        else:
            summaries[name] = {"diagnostics": res.diagnostics, "notes": res.notes}

    # --- exposure ---------------------------------------------------------------
    exposure = None
    if landcover is not None and "screening" in results:
        from .exposure import exposure_from_landcover, zonal_depth_by_class
        depth = results["screening"].layers["depth_max"].array
        exposure = {
            "landcover_area": exposure_from_landcover(
                depth > 0.1, landcover, dem.transform, abs(dem.transform.a) ** 2),
            "mean_depth_by_class_m": zonal_depth_by_class(depth, landcover, dem.transform),
        }
        if "csv" in scenario.exports:
            import pandas as pd
            pd.DataFrame(
                [{"class": k, "area_ha": v["area_ha"]}
                 for k, v in exposure["landcover_area"].items() if isinstance(v, dict)]
            ).to_csv(run_dir / "screening" / "exposure.csv", index=False)

    # --- summary -----------------------------------------------------------------
    summary = {
        "scenario_id": scenario.scenario_id,
        "description": scenario.description,
        "generated_utc": stamp,
        "dam": scenario.dam.__dict__,
        "terrain": {"source": dem.source, "shape": list(dem.shape),
                    "resolution_m": abs(dem.transform.a)},
        "breach": {"mode": breach.mode, "case": breach.case,
                   "peak_flow_m3s": breach.peak_flow_m3s,
                   "failure_time_min": breach.failure_time_min,
                   "breach_width_m": breach.breach_width_m,
                   "volume_m3": volume},
        "solvers": summaries,
        "exposure": exposure,
        "exports": exports_written,
        "runtime_s": round(time.time() - t0, 1),
        "caveats": [
            "screening solver outputs are indicative, not hydrodynamic results",
            "dam registry attributes are demo-grade until verified against NRLD/GeoDAR",
        ],
    }
    with open(run_dir / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    with open(run_dir / "scenario.json", "w", encoding="utf-8") as fh:
        json.dump(scenario.to_dict(), fh, indent=2, default=str)
    log(f"done in {summary['runtime_s']} s -> {run_dir}")
    summary["run_dir"] = str(run_dir)
    return summary
