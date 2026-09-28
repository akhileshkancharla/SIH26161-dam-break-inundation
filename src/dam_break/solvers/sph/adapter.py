"""DualSPHysics adapter — near-field, high-fidelity particle solver.

DualSPHysics runs on CPU or NVIDIA CUDA GPUs; anything beyond toy domains
needs a GPU (laptop RTX 3050 for development, Colab T4 for larger cases).
Workflow here: clip the near-field DEM patch -> STL terrain (see
``preparation.geometry.dem_to_stl``) -> write a DualSPHysics v5-style XML
case definition -> run the solver binaries if present.

If the binaries are unavailable, the case folder is still produced so the
run can be executed on a GPU machine (e.g. the Colab notebook).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np

from ...breach.empirical import BreachParams
from ...ingestion.dem import DEMData
from ...preparation.geometry import dem_to_stl
from ..base import SolverResult


def dualsphysics_root() -> Path | None:
    env = os.environ.get("DUALSPHYSICS_ROOT")
    if env:
        return Path(env)
    # Common checkout location inside the repo workspace.
    for candidate in (Path.cwd() / "DualSPHysics", Path.home() / "DualSPHysics"):
        if candidate.exists():
            return candidate
    return None


def nearfield_patch(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    length_m: float = 2000.0,
    width_m: float = 1000.0,
):
    """Clip the DEM to a near-field box downstream of the dam."""
    cell = abs(dem.transform.a)
    r, c = dam_rowcol
    c0 = max(c - int(200.0 / cell), 0)
    c1 = min(c + int(width_m / cell), dem.shape[1])
    r0 = max(r - int(200.0 / cell), 0)
    r1 = min(r + int(length_m / cell), dem.shape[0])
    z = dem.z[r0:r1, c0:c1]
    from rasterio.transform import Affine
    transform = dem.transform @ Affine.translation(c0, r0)
    return z, transform


def write_case_xml(
    case_dir: Path,
    stl_name: str,
    bbox: tuple[float, float, float, float],
    z_min: float,
    z_max: float,
    breach: BreachParams,
    dp: float = 2.0,
) -> Path:
    """DualSPHysics v5-style XML case: reservoir + terrain + open boundary."""
    x0, y0, x1, y1 = bbox
    # Reservoir: block of water behind the dam crest level.
    water_z = z_min + breach.water_depth_m * 0.5
    xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<case>
  <casedef>
    <definition>
      <pointref x="{x0}" y="{y0}" z="0" />
      <dp value="{dp}" comment="Initial inter-particle spacing (m)" />
    </definition>
  </casedef>
  <geometry>
    <setdrawmode mode="full" />
    <definition dp="{dp}">
      <objlist>
        <object>
          <filestl file="{stl_name}" objname="terrain" />
        </object>
      </objlist>
    </definition>
  </geometry>
  <motion>
    <objlist />
  </motion>
  <floatings>
    <floatingsinfo />
  </floatings>
  <particles>
    <definition dp="{dp}">
      <objlist>
        <object>
          <boxfill objname="reservoir">
            <box x="{x0 + 50}" y="{y0 + 50}" z="{z_min}" x2="{x0 + (x1 - x0) * 0.35}" y2="{y1 - 50}" z2="{water_z}" />
          </boxfill>
        </object>
      </objlist>
    </definition>
  </particles>
  <tools>
    <tlbbasicshaping />
  </tools>
  <runtimes>
    <runtimesim seconds="{max(breach.failure_time_s * 6, 300)}" />
  </runtimes>
  < specials >
    <specialsdefine />
  </specials>
</case>
"""
    path = case_dir / "Case_def.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def run_sph(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    breach: BreachParams,
    run_dir: Path,
    dp: float = 2.0,
    nearfield_length_m: float = 2000.0,
) -> SolverResult:
    run_dir = Path(run_dir) / "dualsphysics"
    run_dir.mkdir(parents=True, exist_ok=True)

    z, transform = nearfield_patch(dem, dam_rowcol, nearfield_length_m)
    finite = np.isfinite(z)
    if not finite.any():
        raise RuntimeError("near-field DEM patch is empty")
    stl = dem_to_stl(z, transform, run_dir / "terrain.stl", coarsen=4)
    bbox = (
        transform.c, transform.f + transform.e * z.shape[0],
        transform.c + transform.a * z.shape[1], transform.f,
    )
    xml = write_case_xml(
        run_dir, stl.name, bbox,
        float(np.nanmin(z)), float(np.nanmax(z)), breach, dp=dp,
    )

    root = dualsphysics_root()
    notes = [
        "SPH is the near-field solver: results cover the clipped reach only",
        f"case ready: {xml} (terrain: {stl.name}, dp={dp} m)",
        "particle count scales as volume/dp^3 — size the domain before running",
    ]
    if root is None:
        notes.append(
            "DualSPHysics checkout not found; clone it and set DUALSPHYSICS_ROOT "
            "(the Colab notebook does this on a T4 runtime)"
        )
        return SolverResult(solver="dualsphysics", layers={}, diagnostics={
            "case_dir": str(run_dir), "executed": False,
        }, notes=notes)

    return SolverResult(solver="dualsphysics", layers={}, diagnostics={
        "case_dir": str(run_dir), "dualsphysics_root": str(root), "executed": False,
    }, notes=notes + [
        "solver execution driver is milestone 3; run GenXML/DualSPHysics from "
        f"{run_dir} meanwhile"
    ])
