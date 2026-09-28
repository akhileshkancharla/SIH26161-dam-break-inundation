"""D-Flow FM model construction from a scenario (milestone 2).

Builds a complete, self-consistent D-Flow FM case from the corridor DEM and
the breach parameters:

- rectangular 2D mesh over the corridor (meshkernel, spacing configurable)
- bed level from DEM samples (initial field, averaging interpolation)
- initial water level = full pool inside a reservoir polygon, dry elsewhere
- native ``dambreak`` structure on a polyline across the valley at the dam,
  with Verheij-van der Knaap breach growth timed by the Froehlich failure
  time (mapping documented below)
- downstream water-level boundary on the mesh edge where the flow path
  exits; upstream edge stays closed (the reservoir drives the wave)
- uniform Manning friction, observation points along the flow path,
  map + history output

Breach-parameter mapping (Froehlich -> Dambreak fields):
    crestLevelIni              = DEM bed at dam + dam height   (crest)
    crestLevelMin              = DEM bed at dam                (breach invert)
    water depth in reservoir   = Hw, via initial water level polygon
    timeToBreachToMaximumDepth = failure_time_s                (tf)
    algorithm                  = 2 (Verheij-van der Knaap 2002)

f1/f2/uCrit are starter values for erodible embankments; calibrate before
quoting results. Executing the model needs the ``dflowfm`` binary (see
adapter.run_delft3d).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ...breach.empirical import BreachParams
from ...ingestion.dem import DEMData

RESERVOIR_UPSTREAM_M = 1500.0   # reservoir polygon length upstream of the crest
FREEBOARD_M = 1.0               # pool level below crest


def _require_hydrolib():
    try:
        import meshkernel  # noqa: F401
        from hydrolib.core.dflowfm import (  # noqa: F401
            FMModel, NetworkModel, Mesh2d, IniFieldModel, InitialField, ExtModel,
            Boundary, ForcingModel, TimeSeries, QuantityUnitPair, PolyFile,
            ObservationPointModel, Dambreak, StructureModel,
        )
        from hydrolib.core.dflowfm.polyfile.models import Point, PolyObject, Metadata  # noqa: F401
        from hydrolib.core.dflowfm.common.models import (  # noqa: F401
            DataFileType, InterpolationMethod, AveragingType,
        )
        return True
    except ImportError as exc:
        raise ImportError(
            "D-Flow FM model building needs hydrolib-core and meshkernel: "
            "pip install .[delft3d]"
        ) from exc


@dataclass
class FMCase:
    run_dir: Path
    mdu_path: Path
    files: dict[str, Path] = field(default_factory=dict)
    info: dict = field(default_factory=dict)


def _save_portable(model, run_dir: Path, name: str):
    """Write a sidecar file, then keep only its bare name for serialization.

    D-Flow FM resolves relative names against the mdu directory (the runner
    executes with cwd=run_dir), which keeps the case folder portable.
    """
    model.save(run_dir / name)
    model.filepath = Path(name)
    return run_dir / name


def _make_poly(name: str, coords):
    from hydrolib.core.dflowfm.polyfile.models import Point, PolyObject, Metadata

    return PolyObject(
        metadata=Metadata(name=name, n_rows=len(coords), n_columns=2),
        points=[Point(x=float(x), y=float(y), data=[]) for x, y in coords],
    )


def _mesh_bounds(dem: DEMData) -> tuple[float, float, float, float]:
    ny, nx = dem.shape
    left = dem.transform.c
    right = dem.transform.c + dem.transform.a * nx
    top = dem.transform.f
    bottom = dem.transform.f + dem.transform.e * ny
    return left, bottom, right, top


def _dem_value(dem: DEMData, x: float, y: float) -> float:
    inv = ~dem.transform
    c, r = inv @ (x, y)
    r = int(np.clip(round(r), 0, dem.shape[0] - 1))
    c = int(np.clip(round(c), 0, dem.shape[1] - 1))
    z = dem.z[r, c]
    return float(z) if np.isfinite(z) else float(np.nanmin(dem.z))


def _dam_line_and_direction(path_xy: np.ndarray, dam_xy: tuple[float, float]):
    """Unit flow direction at the dam and a left/right pair across the valley."""
    d = path_xy - np.asarray(dam_xy)
    dist = np.hypot(d[:, 0], d[:, 1])
    i0 = int(np.argmin(dist))
    i1 = min(i0 + 1, len(path_xy) - 1) if i0 + 1 < len(path_xy) else max(i0 - 1, 0)
    direction = path_xy[i1] - path_xy[i0]
    norm = np.hypot(*direction)
    if norm < 1e-6:
        direction, norm = np.array([1.0, 0.0]), 1.0
    u = direction / norm                      # downstream unit vector
    n = np.array([-u[1], u[0]])               # left-normal unit vector
    return u, n


def _exit_side(path_xy: np.ndarray, bounds) -> str:
    """Which mesh edge the traced flow path leaves through."""
    left, bottom, right, top = bounds
    margin = 1e-6
    inside = (
        (path_xy[:, 0] > left + margin) & (path_xy[:, 0] < right - margin)
        & (path_xy[:, 1] > bottom + margin) & (path_xy[:, 1] < top - margin)
    )
    last = path_xy[np.max(np.where(inside)[0])] if inside.any() else path_xy[-1]
    distances = {
        "west": abs(last[0] - left), "east": abs(right - last[0]),
        "south": abs(last[1] - bottom), "north": abs(top - last[1]),
    }
    return min(distances, key=distances.get)


def _write_bed_xyz(dem: DEMData, path: Path, target_spacing_m: float) -> int:
    """Write DEM samples (x y z) decimated to roughly the mesh spacing."""
    cell = abs(dem.transform.a)
    step = max(1, int(round(target_spacing_m / cell)))
    z = dem.z[::step, ::step]
    rows, cols = np.indices(z.shape)
    xs = dem.transform.c + (cols * step + 0.5) * dem.transform.a
    ys = dem.transform.f + (rows * step + 0.5) * dem.transform.e
    pts = np.column_stack([xs.ravel(), ys.ravel(), z.ravel()])
    pts = pts[np.isfinite(pts[:, 2])]
    np.savetxt(path, pts, fmt="%.2f %.2f %.3f")
    return len(pts)


def build_dflowfm_case(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    dam_xy: tuple[float, float],
    path_xy: np.ndarray,
    breach: BreachParams,
    duration_s: float,
    out_dir: Path,
    mesh_resolution_m: float = 60.0,
    n_manning: float = 0.05,
    refdate: int = 20230101,
) -> FMCase:
    """Assemble and write a full D-Flow FM model; returns an FMCase."""
    _require_hydrolib()
    import meshkernel
    from hydrolib.core.dflowfm import (
        FMModel, NetworkModel, Mesh2d, IniFieldModel, InitialField, ExtModel,
        Boundary, ForcingModel, TimeSeries, QuantityUnitPair, PolyFile,
        ObservationPointModel, Dambreak, StructureModel,
    )
    from hydrolib.core.dflowfm.common.models import (
        DataFileType, InterpolationMethod, AveragingType,
    )

    run_dir = Path(out_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "output").mkdir(exist_ok=True)

    bounds = _mesh_bounds(dem)
    left, bottom, right, top = bounds

    # --- mesh ---------------------------------------------------------------
    # Mesh2d is a live view over the network's MeshKernel, so the grid is
    # built directly on the FMModel's own kernel and saved with the model.
    fm = FMModel()
    fm.filepath = run_dir / "flowfm.mdu"
    width, height = right - left, top - bottom
    nx_cells = max(8, int(round(width / mesh_resolution_m)))
    ny_cells = max(8, int(round(height / mesh_resolution_m)))
    dx, dy = width / nx_cells, height / ny_cells
    fm.geometry.netfile.network.meshkernel.mesh2d_make_rectangular_mesh(
        meshkernel.MakeGridParameters(
            num_columns=nx_cells, num_rows=ny_cells, angle=0.0,
            origin_x=left, origin_y=bottom,
            block_size_x=dx, block_size_y=dy,
            upper_right_x=left + nx_cells * dx,
            upper_right_y=bottom + ny_cells * dy,
        )
    )

    # --- bed level + reservoir initial condition ------------------------------
    n_bed = _write_bed_xyz(dem, run_dir / "bed.xyz", mesh_resolution_m)

    dam_x, dam_y = dam_xy
    u, nrm = _dam_line_and_direction(np.asarray(path_xy, dtype=float), (dam_x, dam_y))
    half = min((top - bottom), (right - left)) * 0.45
    left_pt = np.array([dam_x, dam_y]) - nrm * half
    right_pt = np.array([dam_x, dam_y]) + nrm * half
    up_left = left_pt - u * RESERVOIR_UPSTREAM_M - nrm * (half * 0.3)
    up_right = right_pt - u * RESERVOIR_UPSTREAM_M + nrm * (half * 0.3)

    bed_z = _dem_value(dem, dam_x, dam_y)
    crest_z = bed_z + breach.breach_height_m
    pool_z = crest_z - FREEBOARD_M

    _save_portable(PolyFile(objects=[_make_poly(
        "reservoir",
        [tuple(left_pt), tuple(up_left), tuple(up_right), tuple(right_pt)],
    )]), run_dir, "reservoir.poly")

    inifields = IniFieldModel(initial=[
        InitialField(
            quantity="bedlevel",
            dataFile="bed.xyz",
            dataFileType=DataFileType.sample,
            interpolationMethod=InterpolationMethod.averaging,
            averagingType=AveragingType.mean,
            averagingRelSize=1.21,
        ),
        InitialField(
            quantity="initialwaterlevel",
            dataFile="reservoir.poly",
            dataFileType=DataFileType.polygon,
            value=pool_z,
        ),
    ])
    _save_portable(inifields, run_dir, "flowfm.ini")

    # --- dambreak structure ----------------------------------------------------
    db = Dambreak(
        id="breach", type="dambreak",
        numCoordinates=2,
        xCoordinates=[float(left_pt[0]), float(right_pt[0])],
        yCoordinates=[float(left_pt[1]), float(right_pt[1])],
        startLocationX=float(dam_x), startLocationY=float(dam_y),
        algorithm=2,  # Verheij-van der Knaap (2002)
        crestLevelIni=crest_z,
        crestLevelMin=bed_z,
        breachWidthIni=1.0,
        t0=0.0,
        timeToBreachToMaximumDepth=float(breach.failure_time_s),
        f1=1.0, f2=1.0, uCrit=0.5,  # starter values; calibrate
        waterLevelUpstreamLocationX=float(dam_x - u[0] * 500),
        waterLevelUpstreamLocationY=float(dam_y - u[1] * 500),
        waterLevelDownstreamLocationX=float(dam_x + u[0] * 500),
        waterLevelDownstreamLocationY=float(dam_y + u[1] * 500),
    )
    structures = StructureModel(structure=[db])
    _save_portable(structures, run_dir, "structures.ini")

    # --- downstream boundary ----------------------------------------------------
    side = _exit_side(np.asarray(path_xy, dtype=float), bounds)
    if side == "east":
        bnd = [(right, bottom), (right, top)]
    elif side == "west":
        bnd = [(left, bottom), (left, top)]
    elif side == "north":
        bnd = [(left, top), (right, top)]
    else:
        bnd = [(left, bottom), (right, bottom)]
    outflow_pli = PolyFile(objects=[_make_poly("outflow", bnd)])
    _save_portable(outflow_pli, run_dir, "outflow.pli")

    wl_down = _dem_value(dem, *(bnd[0][0], bnd[0][1])) - 2.0
    duration_min = max(duration_s / 60.0, 1.0)
    forcing = ForcingModel(
        forcing=[
            TimeSeries(
                name="outflow",
                function="timeseries",
                timeinterpolation="linear",
                quantityunitpair=[
                    QuantityUnitPair(quantity="time", unit="minutes since refdate"),
                    QuantityUnitPair(quantity="waterlevelbnd", unit="m"),
                ],
                datablocks=[[0.0, wl_down], [duration_min + 60.0, wl_down]],
            ),
        ],
    )
    _save_portable(forcing, run_dir, "outflow.bc")
    ext = ExtModel(boundary=[
        Boundary(quantity="waterlevelbnd",
                 locationFile=Path("outflow.pli"), forcingFile=forcing),
    ])
    _save_portable(ext, run_dir, "dflowfm.ext")

    # --- observation points along the path ---------------------------------------
    path = np.asarray(path_xy, dtype=float)
    seg = np.hypot(np.diff(path[:, 0]), np.diff(path[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    step_m = 2000.0
    targets = np.arange(step_m, cum[-1], step_m)
    idx = np.searchsorted(cum, targets)
    idx = idx[idx < len(path)]
    from hydrolib.core.dflowfm import XYNModel
    from hydrolib.core.dflowfm.xyn.models import XYNPoint

    obsfile = None
    if len(idx):
        obsfile = XYNModel(points=[
            XYNPoint(x=float(path[i, 0]), y=float(path[i, 1]), n=f"km{i:03d}")
            for i in idx
        ])
        _save_portable(obsfile, run_dir, "obspoints.xyn")

    # --- assemble the FM model ----------------------------------------------------
    fm.geometry.inifieldfile = inifields
    fm.geometry.structurefile = [structures]
    fm.external_forcing.extforcefilenew = ext
    if obsfile is not None:
        fm.output.obsfile = [obsfile]
    fm.geometry.bedlevtype = 3

    fm.time.refdate = refdate
    fm.time.tstart = 0.0
    fm.time.tstop = duration_min  # tunit default: minutes since refdate
    fm.time.dtmax = 5.0
    fm.time.dtinit = 1.0

    fm.physics.uniffricttype = 1          # Manning
    fm.physics.uniffrictcoef = n_manning

    fm.output.mapfile = "flowfm_map.nc"   # written next to the mdu
    fm.output.mapinterval = [10.0]        # minutes
    fm.output.hisfile = "flowfm_his.nc"
    fm.output.hisinterval = [5.0]

    # netfile: write and keep the bare name in the mdu.
    fm.geometry.netfile.save(run_dir / "flowfm_net.nc")
    fm.geometry.netfile.filepath = Path("flowfm_net.nc")
    fm.save(fm.filepath)

    return FMCase(
        run_dir=run_dir,
        mdu_path=fm.filepath,
        files={
            "network": run_dir / "flowfm_net.nc",
            "bed_samples": run_dir / "bed.xyz",
            "initial_fields": run_dir / "flowfm.ini",
            "reservoir_polygon": run_dir / "reservoir.poly",
            "structures": run_dir / "structures.ini",
            "boundary_pli": run_dir / "outflow.pli",
            "boundary_bc": run_dir / "outflow.bc",
            "ext": run_dir / "dflowfm.ext",
            "obs": run_dir / "obspoints.xyn" if obsfile is not None else None,
        },
        info={
            "mesh_cells": nx_cells * ny_cells,
            "mesh_columns": nx_cells,
            "mesh_rows": ny_cells,
            "mesh_resolution_m": mesh_resolution_m,
            "bed_samples": n_bed,
            "crest_level_m": crest_z,
            "pool_level_m": pool_z,
            "breach_failure_time_s": breach.failure_time_s,
            "downstream_boundary": side,
            "observation_points": len(obsfile.points) if obsfile is not None else 0,
            "manning_n": n_manning,
        },
    )
