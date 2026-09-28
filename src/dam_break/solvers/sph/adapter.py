"""DualSPHysics adapter — near-field, high-fidelity particle solver (v5.x).

Case generation follows the real v5.4 XML schema (validated by running
GenCase_win64 on real and synthetic terrain — see tests):

- terrain: ``<drawfilestl>`` from a triangulated DEM patch, written in LOCAL
  coordinates (UTM offsets break float32 precision at dp of a few metres;
  the offset is reapplied when binning particles back to a georeferenced
  raster). The native ``drawbathymetry``/zpoints route segfaults GenCase
  5.4 and is avoided.
- water: reservoir ``<drawbox boxfill="solid">`` behind the dam, filled to
  the pool level; the dam body itself is omitted (instantaneous full-breach
  release — the canonical SPH dam-break setup; progressive breaching is the
  D-Flow FM dambreak structure's job)
- execution: standard Symplectic + Wendland + DDT parameters, TimeMax from
  the scenario

Toolchain: the GitHub clone ships GenCase and post-processing binaries
(PartVTK, ...) but NOT the solver, which comes from the full package
(dual.sphysics.org, registration) or by compiling ``src/`` on Linux. The
adapter therefore runs GenCase whenever available (this validates the case
end-to-end and produces the .bi4 inputs) and executes the solver only when
its binary is present (``DUALSPHYSICS_SOLVER`` or auto-detected). It never
fakes a result.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
from rasterio.transform import Affine

from ...breach.empirical import BreachParams
from ...ingestion.dem import DEMData
from ...preparation.geometry import dem_to_stl, dem_to_xyz
from ..base import SolverResult, RasterLayer

RESERVOIR_FRACTION = 0.35   # near-field box length used by the reservoir
DOMAIN_PAD_M = 30.0


@dataclass
class SPHTools:
    gencase: Path | None = None
    partvtk: Path | None = None
    solver: Path | None = None
    solver_gpu: Path | None = None
    root: Path | None = None

    @property
    def complete(self) -> bool:
        return self.solver is not None or self.solver_gpu is not None


def find_tools() -> SPHTools:
    """Locate DualSPHysics binaries (env overrides win, then known roots)."""
    env_root = os.environ.get("DUALSPHYSICS_ROOT")
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root))
    for p in (Path.cwd(), *Path.cwd().parents[:2]):
        candidates.extend([p / "DualSPHysics", p.parent / "DualSPHysics"])

    windows = platform.system() == "Windows"
    tools = SPHTools()
    for root in candidates:
        if not root.exists():
            continue
        bindir = root / ("bin/windows" if windows else "bin/linux")
        if not bindir.exists():
            continue
        tools.root = root
        gencase = bindir / ("GenCase_win64.exe" if windows else "GenCase_linux64")
        partvtk = bindir / ("PartVTK_win64.exe" if windows else "PartVTK_linux64")
        tools.gencase = gencase if gencase.exists() else None
        tools.partvtk = partvtk if partvtk.exists() else None
        # Solver naming from the official run scripts, e.g.
        # DualSPHysics5.4CPU_win64.exe (CPU) / DualSPHysics5.4_win64.exe (GPU).
        cpu = sorted(bindir.glob("DualSPHysics*CPU*"))
        gpu = [p for p in sorted(bindir.glob("DualSPHysics*")) if "CPU" not in p.name]
        tools.solver = cpu[0] if cpu else None
        tools.solver_gpu = gpu[0] if gpu else None
        break

    # Direct env overrides last (highest priority).
    if os.environ.get("DUALSPHYSICS_GENCASE"):
        tools.gencase = Path(os.environ["DUALSPHYSICS_GENCASE"])
    if os.environ.get("DUALSPHYSICS_SOLVER"):
        tools.solver = Path(os.environ["DUALSPHYSICS_SOLVER"])
    if os.environ.get("DUALSPHYSICS_PARTVTK"):
        tools.partvtk = Path(os.environ["DUALSPHYSICS_PARTVTK"])
    return tools


def nearfield_patch(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    length_m: float = 1500.0,
    width_m: float = 600.0,
    upstream_m: float = 300.0,
):
    """Clip the DEM to a near-field box around the dam (upstream+downstream)."""
    cell = abs(dem.transform.a)
    r, c = dam_rowcol
    c0 = max(c - int(upstream_m / cell), 0)
    c1 = min(c + int((length_m - upstream_m) / cell), dem.shape[1])
    r0 = max(r - int(width_m / 2 / cell), 0)
    r1 = min(r + int(width_m / 2 / cell) + 1, dem.shape[0])
    z = dem.z[r0:r1, c0:c1]
    transform = dem.transform @ Affine.translation(c0, r0)
    return z, transform


def write_case_xml(
    case_dir: Path,
    *,
    dp: float,
    pointmin: tuple[float, float, float],
    pointmax: tuple[float, float, float],
    stl_file: str,
    water_point: tuple[float, float, float],
    water_size: tuple[float, float, float],
    timemax_s: float,
    timeout_s: float,
) -> Path:
    """DualSPHysics v5.4 case: bathymetry terrain + reservoir box."""
    case = ET.Element("case")
    casedef = ET.SubElement(case, "casedef")

    const = ET.SubElement(casedef, "constantsdef")
    ET.SubElement(const, "gravity", x="0", y="0", z="-9.81")
    ET.SubElement(const, "rhop0", value="1000")
    ET.SubElement(const, "rhopgradient", value="2")
    ET.SubElement(const, "hswl", value="0", auto="true")
    ET.SubElement(const, "gamma", value="7")
    ET.SubElement(const, "speedsystem", value="0", auto="true")
    ET.SubElement(const, "coefsound", value="20")
    ET.SubElement(const, "speedsound", value="0", auto="true")
    ET.SubElement(const, "coefh", value="1.0")
    ET.SubElement(const, "cflnumber", value="0.2")

    ET.SubElement(casedef, "mkconfig", boundcount="240", fluidcount="9")

    geometry = ET.SubElement(casedef, "geometry")
    definition = ET.SubElement(geometry, "definition", dp=f"{dp:g}")
    ET.SubElement(definition, "pointmin",
                  x=f"{pointmin[0]:.2f}", y=f"{pointmin[1]:.2f}", z=f"{pointmin[2]:.2f}")
    ET.SubElement(definition, "pointmax",
                  x=f"{pointmax[0]:.2f}", y=f"{pointmax[1]:.2f}", z=f"{pointmax[2]:.2f}")

    commands = ET.SubElement(geometry, "commands")
    mainlist = ET.SubElement(commands, "mainlist")
    ET.SubElement(mainlist, "setdrawmode", mode="full")

    ET.SubElement(mainlist, "setmkbound", mk="0")
    ET.SubElement(mainlist, "drawfilestl", file=stl_file)

    ET.SubElement(mainlist, "setmkfluid", mk="0")
    drawbox = ET.SubElement(mainlist, "drawbox")
    ET.SubElement(drawbox, "boxfill").text = "solid"
    ET.SubElement(drawbox, "point",
                  x=f"{water_point[0]:.2f}", y=f"{water_point[1]:.2f}", z=f"{water_point[2]:.2f}")
    ET.SubElement(drawbox, "size",
                  x=f"{water_size[0]:.2f}", y=f"{water_size[1]:.2f}", z=f"{water_size[2]:.2f}")

    execution = ET.SubElement(case, "execution")
    params = ET.SubElement(execution, "parameters")
    values = {
        "StepAlgorithm": "2",       # Symplectic for violent free-surface flow
        "Kernel": "2",              # Wendland
        "ViscoTreatment": "1",
        "Visco": "0.1",
        "DensityDT": "2",           # Fourtakas
        "DensityDTvalue": "0.1",
        "TimeMax": f"{timemax_s:g}",
        "TimeOut": f"{timeout_s:g}",
        "PartsOutMax": "1",
    }
    for key, value in values.items():
        ET.SubElement(params, "parameter", key=key, value=value)

    ET.indent(case, space="  ")
    path = Path(case_dir) / "CaseSph_Def.xml"
    ET.ElementTree(case).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def run_gencase(case_dir: Path, name: str, gencase: Path, timeout: int = 600) -> tuple[bool, str]:
    """Run GenCase: XML -> .bi4 (+ sanity VTKs). Returns (ok, log tail)."""
    proc = subprocess.run(
        [str(gencase), f"{name}_Def", f"{name}_out/{name}", "-save:all"],
        cwd=str(case_dir), capture_output=True, text=True, timeout=timeout,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log[-4000:]


def run_solver(case_dir: Path, name: str, solver: Path, gpu: int | None = None,
               timeout: int = 0) -> tuple[bool, str]:
    args = [str(solver), f"{name}_out/{name}", f"{name}_out"]
    if gpu is not None:
        args[1:1] = ["-gpu", str(gpu)]
    proc = subprocess.run(
        args, cwd=str(case_dir), capture_output=True, text=True,
        timeout=timeout if timeout > 0 else None,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log[-4000:]


def run_partvtk(case_dir: Path, name: str, partvtk: Path, timeout: int = 600) -> tuple[bool, str]:
    """Extract fluid particles per frame as VTK (visual) and CSV (parsing).

    The CSV output carries a column header, which makes it the robust
    extraction route; the VTKs GenCase/PartVTK write are binary by default.
    """
    proc = subprocess.run(
        [str(partvtk), "-dirdata", f"{name}_out/data",
         "-savevtk", f"{name}_out/particles/PartFluid",
         "-savecsv", f"{name}_out/particles/PartFluid",
         "-onlytype:-all,+fluid"],
        cwd=str(case_dir), capture_output=True, text=True, timeout=timeout,
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log[-2000:]


def parse_csv_particles(path: Path) -> np.ndarray:
    """XYZ array from a PartVTK -savecsv frame (header row with Pos* columns)."""
    import csv

    with open(path, "r", errors="replace", newline="") as fh:
        header = next(csv.reader(fh))
    col = {name.strip().lower(): i for i, name in enumerate(header)}
    ix = col.get("posx") or col.get("x")
    iy = col.get("posy") or col.get("y")
    iz = col.get("posz") or col.get("z")
    if ix is None or iy is None or iz is None:
        raise ValueError(f"unrecognised particle CSV header in {path}")
    data = np.loadtxt(path, delimiter=";", skiprows=1, usecols=(ix, iy, iz),
                      ndmin=2)
    if data.size == 0 or data.shape[1] != 3:
        data = np.loadtxt(path, delimiter=",", skiprows=1, usecols=(ix, iy, iz),
                          ndmin=2)
    return data


def parse_vtk_points(path: Path) -> np.ndarray:
    """XYZ array from a legacy ASCII POLYDATA VTK POINTS block."""
    lines = Path(path).read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("POINTS"):
            n = int(line.split()[1])
            vals: list[float] = []
            j = i + 1
            while len(vals) < n * 3 and j < len(lines):
                parts = lines[j].split()
                if parts and _is_numeric(parts[0]):
                    vals.extend(float(v) for v in parts)
                j += 1
            return np.asarray(vals[: n * 3], dtype=np.float64).reshape(n, 3)
    return np.zeros((0, 3))


def _is_numeric(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def particles_to_depth(
    points: np.ndarray,
    extent: tuple[float, float, float, float],  # x0, y0, x1, y1
    cell: float,
) -> np.ndarray:
    """Bin fluid particles to a grid; depth ~ particle count x dp per column."""
    x0, y0, x1, y1 = extent
    nx = max(1, int(round((x1 - x0) / cell)))
    ny = max(1, int(round((y1 - y0) / cell)))
    counts = np.zeros((ny, nx))
    if len(points) == 0:
        return counts
    cols = ((points[:, 0] - x0) / cell).astype(int)
    rows = ((y1 - points[:, 1]) / cell).astype(int)
    inside = (cols >= 0) & (cols < nx) & (rows >= 0) & (rows < ny)
    np.add.at(counts, (rows[inside], cols[inside]), 1.0)
    return counts * cell


def run_sph(
    dem: DEMData,
    dam_rowcol: tuple[int, int],
    breach: BreachParams,
    run_dir: Path,
    dp: float = 4.0,
    nearfield_length_m: float = 1200.0,
    timemax_s: float | None = None,
    execute: bool = True,
) -> SolverResult:
    run_dir = Path(run_dir) / "dualsphysics"
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- near-field terrain ---------------------------------------------------
    width_m = nearfield_length_m / 2.0
    z, transform = nearfield_patch(dem, dam_rowcol, nearfield_length_m, width_m)
    finite = np.isfinite(z)
    if not finite.any():
        raise RuntimeError("near-field DEM patch is empty")
    zmin = float(np.nanmin(z))
    zmax = float(np.nanmax(z))
    x0 = transform.c
    x1 = transform.c + transform.a * z.shape[1]
    y1 = transform.f
    y0 = transform.f + transform.e * z.shape[0]

    # Pool level: bed at dam + breach water depth, capped inside the patch.
    rc_local = (min(dam_rowcol[0], z.shape[0] - 1), min(dam_rowcol[1], z.shape[1] - 1))
    bed_at_dam = float(z[rc_local]) if np.isfinite(z[rc_local]) else zmin
    pool_z = min(bed_at_dam + breach.water_depth_m, zmax + 5.0)
    if pool_z <= zmin:
        raise RuntimeError("computed pool level is below the terrain minimum")

    # SPH works in local coordinates: large UTM values exhaust float32
    # precision at a few-metre dp, so the patch is shifted to (0, 0) and the
    # offset reapplied when binning particles back to the map.
    cell = abs(transform.a)
    coarsen = max(1, int(round(2.0 * dp / cell))) if cell > 0 else 1
    local_transform = Affine(cell, 0, 0, 0, -cell, z.shape[0] * cell)
    dem_to_stl(z, local_transform, run_dir / "terrain.stl", coarsen=coarsen)
    lx = z.shape[1] * cell   # local extent x
    ly = z.shape[0] * cell   # local extent y

    water_x0 = 0.05 * lx
    water_x1 = RESERVOIR_FRACTION * lx
    water_y0 = 0.05 * ly
    water_y1 = 0.95 * ly

    xml = write_case_xml(
        run_dir,
        dp=dp,
        pointmin=(-DOMAIN_PAD_M, -DOMAIN_PAD_M, zmin - 2.0 * dp),
        pointmax=(lx + DOMAIN_PAD_M, ly + DOMAIN_PAD_M,
                  pool_z + max(breach.water_depth_m, 10.0)),
        stl_file="terrain.stl",
        water_point=(water_x0, water_y0, zmin),
        water_size=(water_x1 - water_x0, water_y1 - water_y0, pool_z - zmin),
        timemax_s=timemax_s if timemax_s else max(breach.failure_time_s * 3, 30.0),
        timeout_s=max((timemax_s if timemax_s else 30.0) / 20.0, 1.0),
    )

    notes = [
        "SPH is the near-field solver: results cover the clipped reach only",
        f"case: {xml.name} (dp={dp:g} m, terrain STL local coords, pool {pool_z:.1f} m)",
        "dam body omitted: instantaneous full-breach release (canonical SPH setup); "
        "progressive breach is the D-Flow FM dambreak structure's job",
        "particle count scales as volume/dp^3 — size the domain before running",
    ]
    diagnostics: dict = {
        "case_dir": str(run_dir), "executed": False, "gencase_ok": None,
        "dp_m": dp, "bed_samples": int(finite.sum()),
        "nearfield_extent_m": [round(x1 - x0), round(y1 - y0)],
        "pool_level_m": pool_z,
    }

    tools = find_tools()
    if tools.gencase is None:
        notes.append(
            "DualSPHysics tools not found; clone the repo next to this project or set "
            "DUALSPHYSICS_ROOT / DUALSPHYSICS_GENCASE"
        )
        return SolverResult(solver="dualsphysics", layers={}, diagnostics=diagnostics, notes=notes)

    if execute:
        (run_dir / "CaseSph_out").mkdir(exist_ok=True)
        ok, log = run_gencase(run_dir, "CaseSph", tools.gencase)
        diagnostics["gencase_ok"] = ok
        if not ok:
            notes.append("GenCase rejected the case — see gencase_log_tail")
            diagnostics["gencase_log_tail"] = log[-500:]
            return SolverResult(solver="dualsphysics", layers={}, diagnostics=diagnostics, notes=notes)
        out = run_dir / "CaseSph_out"
        # GenCase writes the solver input (.bi4) and initial-state VTKs;
        # data/Part_*.bi4 frames appear once the solver runs.
        diagnostics["case_bi4"] = bool((out / "CaseSph.bi4").exists())
        n_fluid = n_bound = 0
        # GenCase reports counts in plain text in the .out file (its VTKs
        # are binary): "Total particles: 792,216 (bound=142788 ... fluid=649428)".
        out_text = ((out / "CaseSph.out").read_text(errors="replace")
                    if (out / "CaseSph.out").exists() else "")
        match = re.search(r"bound=([\d,]+)", out_text)
        if match:
            n_bound = int(match.group(1).replace(",", ""))
        match = re.search(r"fluid=([\d,]+)", out_text)
        if match:
            n_fluid = int(match.group(1).replace(",", ""))
        diagnostics["initial_fluid_particles"] = n_fluid
        diagnostics["initial_boundary_particles"] = n_bound
        notes.append(
            f"GenCase validated the case: fluid {n_fluid:,} / boundary {n_bound:,} "
            f"particles at dp={dp:g} m (solver input: CaseSph.bi4)"
        )

    if not tools.complete:
        notes.append(
            "solver binary absent (the GitHub clone ships GenCase/post tools only): "
            "get the full package from dual.sphysics.org or compile src/ on Linux, "
            "then set DUALSPHYSICS_SOLVER"
        )
        return SolverResult(solver="dualsphysics", layers={}, diagnostics=diagnostics, notes=notes)

    if execute:
        solver = tools.solver_gpu if tools.solver_gpu else tools.solver
        ok, log = run_solver(run_dir, "CaseSph", solver)
        diagnostics["executed"] = ok
        if not ok:
            notes.append("solver failed — see solver_log_tail")
            diagnostics["solver_log_tail"] = log[-500:]
            return SolverResult(solver="dualsphysics", layers={}, diagnostics=diagnostics, notes=notes)

        if tools.partvtk is not None:
            (run_dir / "CaseSph_out" / "particles").mkdir(exist_ok=True)
            ok_v, _ = run_partvtk(run_dir, "CaseSph", tools.partvtk)
            if ok_v:
                pdir = run_dir / "CaseSph_out" / "particles"
                csv_frames = sorted(pdir.glob("PartFluid_*.csv"))
                vtk_frames = sorted(pdir.glob("PartFluid_*.vtk"))
                extent = (0.0, 0.0, lx, ly)
                depth = np.zeros((
                    max(1, int(round(ly / dp))),
                    max(1, int(round(lx / dp))),
                ))
                used = 0
                for frame in csv_frames:
                    try:
                        pts = parse_csv_particles(frame)
                    except Exception:
                        continue
                    depth = np.maximum(depth, particles_to_depth(pts, extent, dp))
                    used += 1
                if not used:
                    for frame in vtk_frames:
                        try:
                            pts = parse_vtk_points(frame)
                        except Exception:
                            continue
                        depth = np.maximum(depth, particles_to_depth(pts, extent, dp))
                        used += 1
                if not used:
                    notes.append(
                        "particle frames could not be parsed (binary VTK and/or "
                        "unknown CSV layout) — pin the format on the first solver run"
                    )
                geo_transform = Affine(dp, 0, x0, 0, -dp, y1)  # back to UTM
                layers = {
                    "depth_max": RasterLayer(
                        depth, geo_transform, dem.crs, "m",
                        "max particle-column depth (SPH, count x dp)"),
                }
                diagnostics["frames_parsed"] = used
                notes.append("particle output binned to a depth grid")
                return SolverResult(solver="dualsphysics", layers=layers,
                                    diagnostics=diagnostics, notes=notes)
        notes.append("solver ran; PartVTK unavailable for raster extraction")

    return SolverResult(solver="dualsphysics", layers={}, diagnostics=diagnostics, notes=notes)
