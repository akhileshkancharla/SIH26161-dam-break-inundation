"""Delft3D FM (D-Flow FM) adapter — regional hydrodynamic solver.

Status: model-file generation via HYDROLIB-core (when installed) plus runner
for the ``dflowfm`` executable. The framework treats Delft3D FM as the
regional solver; this machine must have dflowfm available (Linux binary from
the Deltares OSS distribution, or via Docker) — see README "Solvers".

If the binary or hydrolib-core is missing, ``run_delft3d`` raises a clear
RuntimeError instead of silently faking a result.
"""

from __future__ import annotations

import os
import shutil
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
        return True
    except ImportError:
        return False


def build_boundary_file(t: np.ndarray, q: np.ndarray, path: Path) -> Path:
    """Write the upstream discharge boundary as a D-Flow FM .bc time series."""
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
) -> SolverResult:
    run_dir = Path(run_dir) / "delft3d_fm"
    run_dir.mkdir(parents=True, exist_ok=True)
    build_boundary_file(t, q, run_dir / "boundary.bc")

    if not (dflowfm_binary() and hydrolib_available()):
        raise RuntimeError(
            "Delft3D FM run requested but the toolchain is missing: "
            "install hydrolib-core (pip install .[delft3d]) and make the "
            "'dflowfm' executable available (DFLOWFM_BIN env var or PATH). "
            f"Boundary time series was still written to {run_dir / 'boundary.bc'} "
            "so the case can be run elsewhere."
        )

    # Full model construction (mesh from MeshKernelPy, bed from DEM, friction
    # from n_map) is milestone 2 of the roadmap; hydrolib-core is verified
    # present here so the builder can be added incrementally.
    raise NotImplementedError(
        "D-Flow FM model construction is milestone 2: mesh + mdu generation "
        "via hydrolib-core; the boundary file is ready at "
        f"{run_dir / 'boundary.bc'}"
    )
