"""Run history, background pipeline jobs and export bundles for the dashboard.

Everything here is plain Python (no Streamlit import) so it can be tested
offline. Runs are read back from ``outputs/<scenario_id>/<stamp>/summary.json``
so results survive a browser refresh or a server restart.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ----------------------------------------------------------------- history


@dataclass
class RunRecord:
    """One finished pipeline run on disk."""

    scenario_id: str
    stamp: str
    run_dir: Path
    dam_name: str
    solvers: list[str]
    peak_flow_m3s: float | None
    area_km2: float | None
    runtime_s: float | None
    summary: dict = field(repr=False, default_factory=dict)

    @property
    def label(self) -> str:
        return f"{format_stamp(self.stamp)} · {'+'.join(self.solvers) or 'no solver'}"


def format_stamp(stamp: str) -> str:
    """'20260930T132153Z' -> '30 Sep 2026 · 13:21 UTC' (unknown formats pass through)."""
    try:
        dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
    except (TypeError, ValueError):
        return str(stamp)
    return dt.strftime("%d %b %Y · %H:%M UTC").lstrip("0")


def _area(summary: dict) -> float | None:
    for res in (summary.get("solvers") or {}).values():
        a = (res.get("diagnostics") or {}).get("inundated_area_km2")
        if a is not None:
            return float(a)
    return None


def load_run(run_dir: str | Path) -> RunRecord | None:
    run_dir = Path(run_dir)
    try:
        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    breach = summary.get("breach") or {}
    return RunRecord(
        scenario_id=str(summary.get("scenario_id") or run_dir.parent.name),
        stamp=str(summary.get("generated_utc") or run_dir.name),
        run_dir=run_dir,
        dam_name=str((summary.get("dam") or {}).get("name", "")),
        solvers=list((summary.get("solvers") or {}).keys()),
        peak_flow_m3s=breach.get("peak_flow_m3s"),
        area_km2=_area(summary),
        runtime_s=summary.get("runtime_s"),
        summary=summary,
    )


def list_runs(outputs_dir: str | Path) -> list[RunRecord]:
    """Every run under ``outputs_dir``, newest first."""
    root = Path(outputs_dir)
    if not root.is_dir():
        return []
    runs = [r for p in root.glob("*/*/summary.json") if (r := load_run(p.parent))]
    return sorted(runs, key=lambda r: r.stamp, reverse=True)


def cfg_from_run(run_dir: str | Path) -> dict:
    """Editable scenario dict (the JSON schema load_scenario reads) from a
    run's saved scenario.json, so "tweak & re-run" starts from that run."""
    from ..ingestion.dams import lookup_dam

    saved = json.loads((Path(run_dir) / "scenario.json").read_text(encoding="utf-8"))
    d = dict(saved.get("dam") or {})
    size = {k: d[k] for k in ("height_m", "storage_mcm", "length_m") if d.get(k) is not None}
    hit = lookup_dam(d.get("name", "")) if d.get("name") else None
    if hit is not None and hit.get("name") == d.get("name"):
        dam = {"name": d["name"], "override": size}
    else:
        dam = {"name": d.get("name", "dam"), "lat": d.get("lat"), "lon": d.get("lon"),
               "type": d.get("dam_type", "earthfill"), **size}
    terrain = {k: v for k, v in (saved.get("terrain") or {}).items() if k != "dem_path"}
    return {
        "scenario_id": saved.get("scenario_id", Path(run_dir).parent.name),
        "description": saved.get("description", ""),
        "dam": dam,
        "terrain": terrain,
        "roughness": saved.get("roughness") or {},
        "breach": saved.get("breach") or {},
        "solvers": saved.get("solvers") or ["screening"],
        "run": saved.get("run") or {},
        "exports": saved.get("exports") or ["shp", "kml", "gpkg", "tif", "csv"],
    }


# ------------------------------------------------------------- live stages

# Log lines written by pipeline.run_pipeline; each marks the start of a stage.
_MARKERS = {
    "terrain": "fetching DEM",
    "landcover": "fetching ESA WorldCover",
    "breach": "computing breach parameters",
    "screening": "running screening solver",
    "delft3d_fm": "building D-Flow FM case",
    "dualsphysics": "running DualSPHysics",
    "outputs": "writing rasters, polygons and exports",
    "exposure": "computing exposure and loss",
}
_SOLVER_TITLES = {
    "screening": "Screening solver",
    "delft3d_fm": "Delft3D FM case",
    "dualsphysics": "DualSPHysics (SPH)",
}


@dataclass
class Stage:
    key: str
    title: str
    state: str = "queued"   # queued | running | done | skipped | failed
    detail: str = ""


def plan_stages(cfg: dict) -> list[Stage]:
    """The stages a scenario will go through, in pipeline order."""
    landcover = (cfg.get("roughness") or {}).get("landcover", "none")
    stages = [
        Stage("terrain", "Terrain download", detail=(cfg.get("terrain") or {}).get("dem", "aws_terrarium")),
        Stage("landcover", "Land cover",
              state="queued" if landcover != "none" else "skipped",
              detail="ESA WorldCover" if landcover != "none" else "Skipped: no land cover in this scenario"),
        Stage("breach", "Breach hydrograph",
              detail=(cfg.get("breach") or {}).get("method", "froehlich_2008")),
    ]
    for s in cfg.get("solvers") or ["screening"]:
        stages.append(Stage(s, _SOLVER_TITLES.get(s, s)))
    stages.append(Stage("outputs", "Maps & exports", detail="Rasters, depth polygons, SHP / GPKG / KML"))
    stages.append(Stage("exposure", "Exposure & loss",
                        state="queued" if landcover != "none" else "skipped",
                        detail="" if landcover != "none" else "Skipped: needs land cover"))
    return stages


def _detail_from_log(key: str, lines: list[str]) -> str | None:
    text = "\n".join(lines)
    if key == "terrain":
        m = re.search(r"DEM grid \((\d+), (\d+)\) @ (\d+) m \(([^)]*\)?)\)", text)
        if m:
            d = f"{m.group(1)} × {m.group(2)} cells at {m.group(3)} m · {m.group(4)}"
            s = re.search(r"dam snapped to thalweg: (\d+) m", text)
            return d + (f" · dam snapped {s.group(1)} m onto the channel" if s else "")
    if key == "breach":
        m = re.search(r"Qp=([\d,]+) m3/s, tf=(\d+) min, V=([\d.]+) Mm3", text)
        if m:
            return f"Qp {m.group(1)} m³/s · tf {m.group(2)} min · {m.group(3)} Mm³ released"
    if key == "landcover" and "WorldCover fetch failed" in text:
        return "Fetch failed; using uniform roughness"
    return None


def parse_progress(log_text: str, cfg: dict, returncode: int | None) -> dict:
    """Turn the pipeline's log into per-stage status.

    A stage is running once its marker line appears and done once a later
    stage starts (or the process exits cleanly). ``returncode`` is None
    while the process is still alive.
    """
    stages = plan_stages(cfg)
    lines = [ln.split("] ", 1)[-1] for ln in log_text.splitlines()]
    started: dict[str, int] = {}
    for i, ln in enumerate(lines):
        for key, marker in _MARKERS.items():
            if ln.startswith(marker) and key not in started:
                started[key] = i

    active = [s for s in stages if s.state != "skipped"]
    last_started = None
    for idx, st in enumerate(active):
        if st.key in started:
            last_started = idx
    for idx, st in enumerate(active):
        if last_started is not None and idx < last_started:
            st.state = "done"
        elif idx == last_started:
            st.state = "running"
        # Stages with no marker yet stay queued.

    run_dir = None
    m = re.search(r"done in ([\d.]+) s -> (.+)$", log_text, re.MULTILINE)
    finished_ok = returncode == 0 or (returncode is None and m is not None)
    if m:
        run_dir = m.group(2).strip()
    if finished_ok:
        for st in active:
            if st.state in ("queued", "running"):
                # A stage that never logged (e.g. exposure without land cover
                # data) did not run; mark it skipped rather than done.
                st.state = "done" if st.key in started or st.key in ("terrain", "breach") else "skipped"
    elif returncode not in (None, 0):
        running = [s for s in active if s.state == "running"]
        (running[0] if running else active[0]).state = "failed"

    for st in stages:
        if st.key in started:
            seg_start = started[st.key]
            later = [v for v in started.values() if v > seg_start]
            seg = lines[seg_start:(min(later) if later else len(lines))]
            d = _detail_from_log(st.key, seg)
            if d:
                st.detail = d
            notes = [ln.strip()[6:] for ln in seg if ln.strip().startswith("note: ")]
            if notes and st.key in _SOLVER_TITLES:
                st.detail = notes[0]

    counted = [s for s in stages if s.state != "skipped"]
    done = sum(s.state == "done" for s in counted)
    return {
        "stages": stages,
        "fraction": 1.0 if finished_ok else done / max(len(counted), 1),
        "finished": finished_ok,
        "failed": returncode not in (None, 0),
        "run_dir": run_dir,
    }


# -------------------------------------------------------------- jobs


@dataclass
class Job:
    """A pipeline run in a child process, logging to a file."""

    job_id: str
    cfg: dict
    log_path: Path
    started: float
    proc: subprocess.Popen | None = field(default=None, repr=False)
    ended: float | None = None
    cancelled: bool = False

    @property
    def returncode(self) -> int | None:
        if self.proc is None:
            return None
        rc = self.proc.poll()
        if rc is not None and self.ended is None:
            self.ended = time.time()
        return rc

    @property
    def elapsed_s(self) -> float:
        return (self.ended or time.time()) - self.started

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def cancel(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.cancelled = True


def start_job(cfg: dict, repo: str | Path, jobs_dir: str | Path) -> Job:
    """Launch scripts/run_pipeline.py on ``cfg`` in the background."""
    repo = Path(repo)
    jobs_dir = Path(jobs_dir)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    job_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    cfg_path = jobs_dir / f"{job_id}.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log_path = jobs_dir / f"{job_id}.log"
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(repo / "scripts" / "run_pipeline.py"), str(cfg_path)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(repo), env=env,
        )
    return Job(job_id=job_id, cfg=cfg, log_path=log_path, started=time.time(), proc=proc)


# ------------------------------------------------------------- exports


@dataclass
class ExportFile:
    path: Path
    label: str
    group: str
    tags: frozenset[str]

    @property
    def size(self) -> int:
        return self.path.stat().st_size


EXPORT_GROUPS = ("Flood extent (vector)", "Rasters (GeoTIFF)", "Tables & figures",
                 "Reproduce this run", "Solver case files")
EXPORT_PRESETS = {
    "Recommended": "recommended",
    "Field teams (KML)": "field",
    "GIS analyst (SHP + rasters)": "gis",
    "Reproduce the run": "reproduce",
}
_RASTER_LABELS = {
    "depth_max": "Maximum depth", "arrival_min": "Arrival time",
    "velocity_max": "Maximum velocity", "hazard_class": "Hazard class",
    "hazard": "Hazard index", "dem_utm": "Terrain (DEM)", "landcover": "Land cover",
}
_SHAPEFILE_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
MAX_EXPORT_BYTES = 200 * 1024 * 1024


def export_files(run_dir: str | Path) -> list[ExportFile]:
    """Classify a run directory's files for the Export page."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return []
    top_solvers = {p.name for p in run_dir.iterdir() if p.is_dir()}
    solver_dirs = {"screening", "delft3d_fm", "dualsphysics"} & top_solvers
    multi = len(solver_dirs) > 1
    out: list[ExportFile] = []
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file() or p.stat().st_size > MAX_EXPORT_BYTES:
            continue
        rel = p.relative_to(run_dir)
        solver = rel.parts[0] if len(rel.parts) > 1 else None
        suffix = f" · {solver}" if multi and solver else ""
        name = p.name.lower()
        if solver in ("delft3d_fm", "dualsphysics"):
            out.append(ExportFile(p, str(rel.as_posix()), "Solver case files", frozenset()))
        elif name.endswith(".shp.zip"):
            out.append(ExportFile(p, "Shapefile" + suffix, EXPORT_GROUPS[0],
                                  frozenset({"recommended", "gis"})))
        elif p.suffix.lower() in _SHAPEFILE_PARTS:
            continue  # shipped inside the .shp.zip
        elif p.suffix.lower() == ".gpkg":
            out.append(ExportFile(p, "GeoPackage" + suffix, EXPORT_GROUPS[0],
                                  frozenset({"recommended", "gis"})))
        elif p.suffix.lower() == ".kml":
            out.append(ExportFile(p, "KML for Google Earth" + suffix, EXPORT_GROUPS[0],
                                  frozenset({"recommended", "field"})))
        elif p.suffix.lower() == ".tif":
            label = _RASTER_LABELS.get(p.stem, p.stem) + suffix
            tags = {"gis"}
            if p.stem in ("depth_max", "arrival_min"):
                tags.add("recommended")
            out.append(ExportFile(p, label, EXPORT_GROUPS[1], frozenset(tags)))
        elif p.name in ("scenario.json", "summary.json", "comparison.json"):
            label = {"scenario.json": "Scenario (JSON)", "summary.json": "Run summary (JSON)",
                     "comparison.json": "Solver comparison (JSON)"}[p.name]
            tags = {"reproduce"} | ({"recommended"} if p.name != "comparison.json" else set())
            out.append(ExportFile(p, label, EXPORT_GROUPS[3], frozenset(tags)))
        elif p.suffix.lower() in (".csv", ".png", ".json"):
            if p.name == "hydrograph.csv":
                label, tags = "Breach hydrograph (CSV)", {"recommended"}
            elif name.endswith("_classes.csv"):
                label, tags = "Area by depth class (CSV)" + suffix, set()
            else:
                label, tags = str(rel.as_posix()), set()
            out.append(ExportFile(p, label, EXPORT_GROUPS[2], frozenset(tags)))
    return out


def caveats_text(summary: dict) -> str:
    lines = [
        "HydroInundate (SIH 26161) - read before using these results",
        "",
        f"Scenario: {summary.get('scenario_id', '')}",
        f"Run: {format_stamp(str(summary.get('generated_utc', '')))}",
        f"Solvers: {', '.join((summary.get('solvers') or {}).keys())}",
        "",
    ]
    lines += [f"- {c}" for c in relevant_caveats(summary)]
    return "\n".join(lines) + "\n"


def relevant_caveats(summary: dict) -> list[str]:
    """The run's caveats, minus ones that don't apply (e.g. loss without exposure)."""
    out = []
    for c in summary.get("caveats") or []:
        if "loss" in c and not summary.get("exposure"):
            continue
        if "screening" in c and "screening" not in (summary.get("solvers") or {}):
            continue
        if "registry" in c and (summary.get("dam") or {}).get("registry_verified"):
            continue
        out.append(c)
    return out


def bundle_zip(run_dir: str | Path, files: list[Path], caveats: str | None) -> bytes:
    """Zip the chosen files (paths kept relative to the run) plus CAVEATS.txt."""
    run_dir = Path(run_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.relative_to(run_dir).as_posix())
        if caveats:
            zf.writestr("CAVEATS.txt", caveats)
    return buf.getvalue()


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"
