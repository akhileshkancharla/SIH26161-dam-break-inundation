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
import shutil
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


def _scan_root(root: Path, windows: bool) -> SPHTools:
    """Collect tools from one DualSPHysics tree (clone or full package)."""
    bindir = root / ("bin/windows" if windows else "bin/linux")
    tools = SPHTools(root=root)
    if not bindir.exists():
        return tools
    gencase = bindir / ("GenCase_win64.exe" if windows else "GenCase_linux64")
    partvtk = bindir / ("PartVTK_win64.exe" if windows else "PartVTK_linux64")
    tools.gencase = gencase if gencase.exists() else None
    tools.partvtk = partvtk if partvtk.exists() else None
    # Solver naming from the official run scripts, e.g.
    # DualSPHysics5.4CPU_win64.exe (CPU) / DualSPHysics5.4_win64.exe (GPU);
    # skip the 4.0 LiquidGas variants shipped in the full package.
    def pick(pattern: str, exclude: tuple[str, ...]) -> Path | None:
        hits = [p for p in sorted(bindir.glob(pattern))
                if not any(x in p.name for x in exclude)]
        return hits[0] if hits else None

    tools.solver = pick("DualSPHysics*CPU*", ("LiquidGas",))
    tools.solver_gpu = pick("DualSPHysics*_win64.exe" if windows else "DualSPHysics*_linux64",
                            ("CPU", "LiquidGas"))
    return tools


def find_tools() -> SPHTools:
    """Locate DualSPHysics binaries.

    Roots considered: $DUALSPHYSICS_ROOT first, then any DualSPHysics*
    directory next to this project (the git clone ships GenCase/post tools;
    the full package from dual.sphysics.org also has the solver and is
    preferred when both are present).
    """
    candidates: list[Path] = []
    env_root = os.environ.get("DUALSPHYSICS_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    for p in (Path.cwd(), *Path.cwd().parents[:3]):
        candidates.extend(sorted(p.glob("DualSPHysics*"), reverse=True))
        candidates.extend([p / "DualSPHysics", p.parent / "DualSPHysics"])

    windows = platform.system() == "Windows"
    seen: set[Path] = set()
    fallback: SPHTools | None = None
    for root in candidates:
        root = root.resolve()
        if not root.is_dir() or root in seen:
            continue
        seen.add(root)
        tools = _scan_root(root, windows)
        if tools.gencase is None and tools.solver is None:
            continue
        if tools.complete:
            return tools          # full package wins
        if fallback is None and tools.gencase is not None:
            fallback = tools      # clone: GenCase only
    tools = fallback or SPHTools()
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
    stl = ET.SubElement(mainlist, "drawfilestl", file=stl_file, advanced="true")
    ET.SubElement(stl, "depth", depthmin=f"{3 * dp:g}")  # solid crust under the surface

    ET.SubElement(mainlist, "setmkbound", mk="1")
    floor = ET.SubElement(mainlist, "drawbox")
    ET.SubElement(floor, "boxfill").text = "solid"
    ET.SubElement(floor, "point",
                  x=f"{pointmin[0]:.2f}", y=f"{pointmin[1]:.2f}", z=f"{pointmin[2] - dp:.2f}")
    ET.SubElement(floor, "size",
                  x=f"{pointmax[0] - pointmin[0]:.2f}",
                  y=f"{pointmax[1] - pointmin[1]:.2f}", z=f"{3 * dp:g}")

    # Upstream containment wall at the reservoir's upstream face (the DEM
    # patch is clipped there; without the wall the pool leaks off the edge).
    ET.SubElement(mainlist, "setmkbound", mk="2")
    wall = ET.SubElement(mainlist, "drawbox")
    ET.SubElement(wall, "boxfill").text = "solid"
    ET.SubElement(wall, "point", x=f"{water_point[0] - 2 * dp:.2f}",
                  y=f"{pointmin[1]:.2f}", z=f"{pointmin[2]:.2f}")
    ET.SubElement(wall, "size", x=f"{2 * dp:g}",
                  y=f"{pointmax[1] - pointmin[1]:.2f}",
                  z=f"{water_point[2] + water_size[2] + 2 * dp - pointmin[2]:.2f}")

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


def _tool_env(tool: Path) -> dict:
    """Subprocess env: on Linux the DualSPHysics binaries need their bundled
    shared libraries (libdsphchrono.so, libChronoEngine.so) on
    LD_LIBRARY_PATH — they live in the same bin directory as the tool."""
    env = os.environ.copy()
    if platform.system() != "Windows":
        bindir = str(tool.parent)
        env["LD_LIBRARY_PATH"] = bindir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    return env


def run_gencase(case_dir: Path, name: str, gencase: Path, timeout: int = 600) -> tuple[bool, str]:
    """Run GenCase: XML -> .bi4 (+ sanity VTKs). Returns (ok, log tail)."""
    proc = subprocess.run(
        [str(gencase), f"{name}_Def", f"{name}_out/{name}", "-save:all"],
        cwd=str(case_dir), capture_output=True, text=True, timeout=timeout,
        env=_tool_env(gencase),
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log[-4000:]


def run_solver(case_dir: Path, name: str, solver: Path, gpu: int | None = None,
               timeout: int = 0) -> tuple[bool, str]:
    """Run the solver, streaming its per-part progress lines as they come.

    The solver prints one summary line per output part (default every
    horizon/20 s of simulated time); these are echoed live so a
    hours-long solve is not a black box in the notebook.
    """
    args = [str(solver), f"{name}_out/{name}", f"{name}_out"]
    if gpu is not None:
        args[1:1] = ["-gpu", str(gpu)]
    proc = subprocess.Popen(
        args, cwd=str(case_dir), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
        env=_tool_env(solver),
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        if any(k in line for k in ("Part ", "TOTAL", "ERROR", "Time ")):
            print(f"    {line.rstrip()[:110]}", flush=True)
    proc.wait()
    log = "".join(lines)
    return proc.returncode == 0, log[-4000:]


def run_partvtk(case_dir: Path, name: str, partvtk: Path, timeout: int = 600) -> tuple[bool, str]:
    """Extract fluid particles per frame.

    ``-saveascii`` writes headerless columns "x y z id vel.x vel.y vel.z
    rhop press type" per particle (format pinned against PartVTK v5.4);
    ``-savevtk`` (binary by default) is kept for visualisation only.
    """
    proc = subprocess.run(
        [str(partvtk), "-dirdata", f"{name}_out/data",
         "-saveascii", f"{name}_out/particles/PartFluid",
         "-savevtk", f"{name}_out/particles/PartFluid",
         "-onlytype:-all,+fluid"],
        cwd=str(case_dir), capture_output=True, text=True, timeout=timeout,
        env=_tool_env(partvtk),
    )
    log = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, log[-2000:]


def parse_vtk_points(path: Path) -> np.ndarray:
    """XYZ array from a legacy POLYDATA VTK POINTS block.

    Handles both the ASCII form and the BINARY form PartVTK writes by
    default (raw big-endian floats right after the "POINTS n float" line).
    """
    raw = Path(path).read_bytes()
    if b"\nBINARY" in raw[:200]:
        idx = raw.find(b"\nPOINTS")
        line_end = raw.find(b"\n", idx + 1)
        n = int(raw[idx + 1:line_end].split()[1])
        return np.frombuffer(raw, dtype=">f4", count=n * 3,
                             offset=line_end + 1).reshape(n, 3).astype(np.float64)
    lines = raw.decode(errors="replace").splitlines()
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

    # Bed at the local thalweg (the dam coordinate can land on a valley
    # side, which would float the reservoir above the channel).
    rc_local = (min(dam_rowcol[0], z.shape[0] - 1), min(dam_rowcol[1], z.shape[1] - 1))
    r0w = max(rc_local[0] - 5, 0); r1w = min(rc_local[0] + 6, z.shape[0])
    c0w = max(rc_local[1] - 5, 0); c1w = min(rc_local[1] + 6, z.shape[1])
    window = z[r0w:r1w, c0w:c1w]
    bed_at_dam = float(np.nanmin(window)) if np.isfinite(window).any() else zmin

    # Pool requested by the breach scenario; clamped by the natural rim of
    # the reservoir box (valley walls at its y-faces) so the pool is held by
    # terrain rather than spilling over the whole near-field patch.
    pool_requested = bed_at_dam + breach.water_depth_m
    ly_, lx_ = z.shape
    # Reservoir box side faces in array indices (row 0 == local y = ly).
    row_top, row_bot = int(0.05 * ly_), min(int(0.95 * ly_), ly_ - 1)
    c0b, c1b = int(0.05 * lx_), min(int(RESERVOIR_FRACTION * lx_) + 1, lx_)
    edges = np.concatenate([z[row_top, c0b:c1b], z[row_bot, c0b:c1b]])
    # Walls dominate the box edges; the channel is a minority, so a
    # percentile (not the minimum) estimates the containing rim.
    rim = float(np.nanpercentile(edges, 60))
    pool_z = min(pool_requested, rim - 1.0)
    if pool_z <= zmin + 0.5 * dp:
        raise RuntimeError(
            "reservoir cannot be held within this near-field window (pool "
            f"{pool_z:.1f} m vs terrain minimum {zmin:.1f} m); widen "
            "nearfield_length_m or lower the dam height")

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

    # Simulated horizon: the flood front crosses a 1-2 km near-field in
    # ~1-3 minutes of simulated time; hours-long horizons (e.g. 3x the
    # breach failure time) turn into millions of time steps and run for
    # days. Override with run.sph_timemax_s if a longer window is needed.
    horizon = timemax_s if timemax_s else max(min(breach.failure_time_s * 3, 300.0), 30.0)

    xml = write_case_xml(
        run_dir,
        dp=dp,
        pointmin=(-DOMAIN_PAD_M, -DOMAIN_PAD_M, zmin - 2.0 * dp),
        pointmax=(lx + DOMAIN_PAD_M, ly + DOMAIN_PAD_M,
                  pool_z + max(breach.water_depth_m, 10.0)),
        stl_file="terrain.stl",
        water_point=(water_x0, water_y0, zmin),
        water_size=(water_x1 - water_x0, water_y1 - water_y0, pool_z - zmin),
        timemax_s=horizon,
        timeout_s=max(horizon / 20.0, 1.0),
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
        "pool_requested_m": pool_requested,
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
        total = re.search(
            r"Total particles:[\d,\s]*\(bound=([\d,]+)[^)]*\)[\s\S]*?fluid=([\d,]+)",
            out_text)
        if total:
            n_bound = int(total.group(1).replace(",", ""))
            n_fluid = int(total.group(2).replace(",", ""))
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
        # GPU only when an NVIDIA driver is present (DUALSPHYSICS_DEVICE
        # can force "gpu" or "cpu"); the GPU exe fails hard without CUDA.
        device = os.environ.get("DUALSPHYSICS_DEVICE", "auto")
        use_gpu = tools.solver_gpu is not None and (
            device == "gpu"
            or (device == "auto" and shutil.which("nvidia-smi") is not None)
        )
        solver = tools.solver_gpu if use_gpu else tools.solver
        diagnostics["solver_device"] = "gpu" if use_gpu else "cpu"
        # Announce before the (possibly hours-long) solve so a silent CPU
        # fallback is visible in the notebook output immediately.
        print(f"[sph] solver: {solver.name} ({diagnostics['solver_device'].upper()}); "
              f"DUALSPHYSICS_DEVICE={device}; timemax={horizon:g} s simulated")
        if use_gpu and shutil.which("nvidia-smi") is None:
            print("[sph] WARNING: GPU forced but nvidia-smi not found; "
                  "solver will fail if no CUDA device is present")
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
                # -onlytype:+fluid applies to the VTK output; -saveascii files
                # always contain every particle and are kept only for debugging.
                frames = sorted(pdir.glob("PartFluid_*.vtk"))
                extent = (0.0, 0.0, lx, ly)
                depth = np.zeros((
                    max(1, int(round(ly / dp))),
                    max(1, int(round(lx / dp))),
                ))
                used = 0
                for frame in frames:
                    try:
                        pts = parse_vtk_points(frame)
                    except Exception:
                        continue
                    depth = np.maximum(depth, particles_to_depth(pts, extent, dp))
                    used += 1
                if not used:
                    notes.append("no parsable particle frames (PartFluid_*.vtk)")
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
