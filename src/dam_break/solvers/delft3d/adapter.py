"""Delft3D FM (D-Flow FM) adapter — regional hydrodynamic solver.

``run_delft3d`` builds the complete model (see model_builder) and, when the
``dflowfm`` executable is available (``DFLOWFM_BIN`` env var or PATH),
executes it and reports status. Without the binary the case folder is still
fully written so it can be executed on Linux/WSL/Colab — the model is the
deliverable either way, and the framework never fakes a result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from ...breach.empirical import BreachParams
from ...ingestion.dem import DEMData
from ..base import SolverResult


def dflowfm_binary() -> str | None:
    return os.environ.get("DFLOWFM_BIN") or shutil.which("dflowfm")


def hydrolib_available() -> bool:
    try:
        import hydrolib.core  # noqa: F401
        import meshkernel  # noqa: F401
        return True
    except ImportError:
        return False


def build_boundary_file(t: np.ndarray, q: np.ndarray, path: Path) -> Path:
    """Upstream discharge time series as a plain .bc (kept for reuse/tests)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[General]",
        "fileVersion = 2.00",
        "fileType = 1D/2D boundary condition file",
        "",
        "[boundary]",
        "name = breach_inflow",
        "function = timeseries",
        "timeInterpolation = linear",
        "quantity = time",
        "unit = s",
        "quantity = discharge",
        "unit = m3/s",
    ]
    for ti, qi in zip(t, q):
        lines.append(f"  {ti:.0f}  {qi:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_delft3d(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    breach: BreachParams,
    t: np.ndarray,
    q: np.ndarray,
    n_map: np.ndarray | float,
    run_dir: Path,
    path_xy: np.ndarray | None = None,
    duration_s: float | None = None,
    mesh_resolution_m: float = 60.0,
) -> SolverResult:
    from ...preparation.terrain import priority_flood_fill, trace_flow_path, coarsen
    from rasterio.transform import Affine

    run_dir = Path(run_dir) / "delft3d_fm"
    run_dir.mkdir(parents=True, exist_ok=True)
    build_boundary_file(t, q, run_dir / "breach_inflow.bc")

    if not hydrolib_available():
        raise RuntimeError(
            "Delft3D FM model building needs hydrolib-core + meshkernel: "
            "pip install .[delft3d]. The breach boundary series was written to "
            f"{run_dir / 'breach_inflow.bc'}."
        )

    # Flow path for the dam line, boundary side and observation points.
    if path_xy is None:
        cell = abs(dem.transform.a)
        z_small, factor = coarsen(dem.z, 4)
        filled = priority_flood_fill(z_small)
        small_transform = dem.transform @ Affine.scale(factor, factor)
        path_xy = np.asarray(
            trace_flow_path(filled, dam_rowcol[0] // factor, dam_rowcol[1] // factor,
                            small_transform, max(dem.shape) * cell * 1.5),
            dtype=float,
        )
    if duration_s is None:
        duration_s = float(t[-1]) if len(t) else 3600.0
    n_scalar = float(np.mean(n_map)) if isinstance(n_map, np.ndarray) else float(n_map)

    from .model_builder import build_dflowfm_case
    inv = ~dem.transform
    dam_x, dam_y = inv @ (dam_rowcol[1], dam_rowcol[0])
    case = build_dflowfm_case(
        dem=dem, dam_rowcol=dam_rowcol, dam_xy=(dam_x, dam_y),
        path_xy=path_xy, breach=breach, duration_s=duration_s,
        out_dir=run_dir, mesh_resolution_m=mesh_resolution_m, n_manning=n_scalar,
    )

    notes = [
        "regional solver: mesh covers reservoir + downstream corridor",
        f"dambreak structure: tf={breach.failure_time_s:.0f} s, "
        f"crest {case.info['crest_level_m']:.1f} m, pool {case.info['pool_level_m']:.1f} m",
        "f1/f2/uCrit breach-growth parameters are starter values; calibrate",
    ]
    diagnostics = {"case_dir": str(case.run_dir), "mdu": str(case.mdu_path),
                   "executed": False, **case.info}

    binary = dflowfm_binary()
    if binary is None:
        notes.append(
            "dflowfm binary not found (set DFLOWFM_BIN); the complete case is at "
            f"{case.mdu_path} — run it on Linux/WSL/Colab"
        )
        return SolverResult(solver="delft3d_fm", layers={}, diagnostics=diagnostics,
                            notes=notes)

    log_path = case.run_dir / "dflowfm.log"
    with open(log_path, "w", encoding="utf-8") as log_fh:
        proc = subprocess.run(
            [binary, str(case.mdu_path.name)], cwd=str(case.run_dir),
            stdout=log_fh, stderr=subprocess.STDOUT, timeout=None,
        )
    diagnostics["executed"] = True
    diagnostics["returncode"] = proc.returncode
    map_nc = case.run_dir / "output" / "flowfm_map.nc"
    diagnostics["map_file"] = str(map_nc) if map_nc.exists() else None
    notes.append(f"solver finished rc={proc.returncode}; log: {log_path.name}")
    if proc.returncode != 0:
        notes.append("non-zero return code — inspect dflowfm.log")
    return SolverResult(solver="delft3d_fm", layers={}, diagnostics=diagnostics,
                        notes=notes)
