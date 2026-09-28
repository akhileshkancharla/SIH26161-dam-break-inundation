"""Rapid screening solver: cross-section-wise volume fill along the river.

This is NOT a hydrodynamic solver. It is a deliberately simple, fast,
volume-conserving first-pass inundation estimate for scenario triage and
dashboard demos; Delft3D FM and SPH handle the defensible physics runs:

1. Trace the downstream flow path from the dam on a depression-filled DEM.
2. Assign every cell within a corridor to its nearest path cross-section.
3. Split the breach volume between cross-sections in proportion to their
   length along the path (optionally attenuated downstream).
4. Fill each cross-section from the bed up until its volume share fits,
   giving per-cell depth and a stage that follows the valley.
5. Arrival time from Manning kinematic celerity c = (5/3) v along the path,
   v = (1/n) h^(2/3) sqrt(S); velocity raster from local terrain slope.

Always label outputs from this solver as "screening".
"""

from __future__ import annotations

import numpy as np
from rasterio.transform import Affine
from scipy.spatial import cKDTree

from ..breach.empirical import BreachParams
from ..ingestion.dem import DEMData
from ..preparation.terrain import priority_flood_fill, trace_flow_path, coarsen, slope_magnitude
from .base import SolverResult, RasterLayer

MIN_WET_DEPTH = 0.05  # m; below this a cell counts as dry


def _fill_section_volumes(
    section_elevs: list[np.ndarray],
    targets: np.ndarray,
    cell_area: float,
) -> np.ndarray:
    """Stage per section from a target storage volume.

    For a section with cell elevations sorted ascending, the volume below
    stage z is V(z) = sum(max(z - e_i, 0)) * A; solve by scanning sorted
    elevations with a cumulative sum and closing linearly inside the bracket.
    """
    stages = np.zeros(len(section_elevs))
    for i, (elevs, target) in enumerate(zip(section_elevs, targets)):
        if elevs.size == 0 or target <= 0:
            continue
        srt = np.sort(elevs)
        csum = np.cumsum(srt)
        k = np.arange(1, srt.size + 1)
        vol_at = (k * srt - csum) * cell_area  # volume when stage = srt[k-1]
        j = int(np.searchsorted(vol_at, target))
        if j >= srt.size:
            # Valley saturated: continue the stage above the highest cell.
            stages[i] = srt[-1] + (target - vol_at[-1]) / (srt.size * cell_area)
        elif j == 0:
            stages[i] = srt[0] + target / (srt.size * cell_area)
        else:
            v0, v1 = vol_at[j - 1], vol_at[j]
            frac = 0.0 if v1 == v0 else (target - v0) / (v1 - v0)
            stages[i] = srt[j - 1] + frac * (srt[j] - srt[j - 1])
    return stages


def run_screening(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    breach: BreachParams,
    volume_m3: float,
    n_map: np.ndarray | float,
    corridor_width_m: float,
    attenuation_km: float | None = None,
    trace_coarsen: int = 4,
) -> SolverResult:
    """Run the volume-fill screening model on a UTM-grid DEM.

    ``dam_rowcol`` is the dam's (row, col) on the DEM grid; ``volume_m3`` is
    the total volume released by the breach (hydrograph integral).
    """
    cell = abs(dem.transform.a)
    cell_area = cell * cell
    n_scalar = float(np.mean(n_map)) if isinstance(n_map, np.ndarray) else float(n_map)

    # --- 1. Flow path on a coarsened, depression-filled DEM -----------------
    z_small, factor = coarsen(dem.z, trace_coarsen)
    filled_small = priority_flood_fill(z_small)
    small_transform = dem.transform @ Affine.scale(factor, factor)
    max_path_m = max(dem.shape) * cell * 1.5
    xy = np.asarray(
        trace_flow_path(
            filled_small,
            int(dam_rowcol[0] // factor),
            int(dam_rowcol[1] // factor),
            small_transform,
            max_path_m,
        ),
        dtype=np.float64,
    )
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    n_sections = len(xy)
    notes = [f"flow path traced: {cum[-1] / 1000.0:.1f} km ({factor}x coarsened grid)"]

    # --- 2. Assign corridor cells to the nearest path section ----------------
    ny, nx = dem.shape
    rows, cols = np.indices((ny, nx))
    xs = dem.transform.c + (cols + 0.5) * dem.transform.a
    ys = dem.transform.f + (rows + 0.5) * dem.transform.e
    pts = np.column_stack([xs.ravel(), ys.ravel()])
    tree = cKDTree(xy)
    dist, idx = tree.query(pts, distance_upper_bound=corridor_width_m)
    valid = np.isfinite(dist)
    sec_of_cell = np.full(pts.shape[0], -1, dtype=np.int64)
    sec_of_cell[valid] = idx[valid]

    # --- 3. Volume routing: split the breach volume along the path -----------
    lengths = np.diff(np.concatenate([cum, [cum[-1] + cell * factor]]))
    frac = lengths / max(lengths.sum(), 1e-9)
    sec_volume = volume_m3 * frac
    if attenuation_km is not None:
        # Model water leaving the corridor (spill outside AOI / storage) as
        # an exponential loss with distance.
        sec_volume = sec_volume * np.exp(-cum / (attenuation_km * 1000.0))

    # --- 4. Fill each section ------------------------------------------------
    flat_z = dem.z.ravel()
    order = np.argsort(sec_of_cell, kind="stable")
    sorted_sec = sec_of_cell[order]
    starts = np.searchsorted(sorted_sec, np.arange(n_sections), side="left")
    ends = np.searchsorted(sorted_sec, np.arange(n_sections), side="right")
    section_elevs = []
    for s in range(n_sections):
        vals = flat_z[order[starts[s]:ends[s]]]
        section_elevs.append(vals[np.isfinite(vals)])
    stages = _fill_section_volumes(section_elevs, sec_volume, cell_area)

    depth = np.zeros(pts.shape[0], dtype=np.float64)
    sec_depth = stages[sec_of_cell] - flat_z
    wet = (sec_of_cell >= 0) & (sec_depth > MIN_WET_DEPTH)
    depth[wet] = sec_depth[wet]
    depth = depth.reshape(dem.shape)

    # --- 5. Arrival time and velocity ----------------------------------------
    bed = np.array([e.min() if e.size else np.nan for e in section_elevs])
    bed_ok = ~np.isnan(bed)
    if bed_ok.sum() > 1:
        d_ok = cum[bed_ok]
        dz = np.abs(np.diff(bed[bed_ok]))
        dx = np.maximum(np.diff(d_ok), 1.0)
        slope_sec = np.maximum(dz / dx, 1e-4)
    else:
        slope_sec = np.array([1e-3])
    h_sec = np.where(np.isfinite(stages - bed), np.maximum(stages - bed, 0.05), 0.05)
    # Velocity at each section uses the local longitudinal slope; sections
    # beyond the last slope sample reuse the final value.
    if slope_sec.size:
        slope_per_sec = np.resize(slope_sec, n_sections)
    else:
        slope_per_sec = np.full(n_sections, 1e-3)
    v_sec = (1.0 / n_scalar) * h_sec ** (2.0 / 3.0) * np.sqrt(slope_per_sec)
    celerity = np.maximum((5.0 / 3.0) * v_sec, 0.3)
    if n_sections > 1:
        dt_seg = np.diff(cum) / celerity[:-1]
    else:
        dt_seg = np.zeros(0)
    t_arr = np.concatenate([[0.0], np.cumsum(dt_seg)])

    arrival = np.full(pts.shape[0], np.nan)
    arrival[wet] = t_arr[sec_of_cell[wet]] / 60.0
    arrival = arrival.reshape(dem.shape)

    slope_grid = np.maximum(slope_magnitude(dem.z, cell), 1e-4)
    velocity = np.where(
        depth > MIN_WET_DEPTH,
        (1.0 / n_scalar) * depth ** (2.0 / 3.0) * np.sqrt(slope_grid),
        0.0,
    )
    hazard = depth * velocity

    layers = {
        "depth_max": RasterLayer(depth, dem.transform, dem.crs, "m",
                                 "maximum water depth (screening)"),
        "arrival_min": RasterLayer(arrival, dem.transform, dem.crs, "min",
                                   "flood front arrival time (screening)"),
        "velocity_max": RasterLayer(velocity, dem.transform, dem.crs, "m/s",
                                    "surface velocity proxy (screening)"),
        "hazard": RasterLayer(hazard, dem.transform, dem.crs, "m2/s",
                              "depth x velocity hazard (screening)"),
    }
    stored = float(depth.sum() * cell_area)
    diagnostics = {
        "inundated_area_km2": float((depth > 0.1).sum() * cell_area / 1e6),
        "stored_volume_m3": stored,
        "target_volume_m3": float(volume_m3),
        "path_length_km": float(cum[-1] / 1000.0),
        "arrival_last_min": float(t_arr[-1] / 60.0) if t_arr.size else None,
        "sections": int(n_sections),
        "manning_n_mean": n_scalar,
    }
    notes.append("screening solver: indicative inundation only, not hydrodynamics")
    if stored < 0.5 * volume_m3:
        notes.append(
            f"corridor retains {stored / max(volume_m3, 1e-9):.0%} of the breach volume; "
            "widen the corridor or shorten the reach"
        )
    return SolverResult(solver="screening", layers=layers, diagnostics=diagnostics, notes=notes)
