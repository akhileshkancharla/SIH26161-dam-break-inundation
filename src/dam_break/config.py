"""Scenario configuration: one JSON drives the whole pipeline.

Schema (see configs/scenarios/*.json for examples):

{
  "scenario_id": "demo_overtopping_expected",
  "description": "optional text",
  "dam": {
    "name": "Machhu-II",            # looked up in the local dam registry
    "override": {"storage_mcm": 60}  # optional per-run overrides
    # -- or inline: {"name": "...", "lat": 22.81, "lon": 70.90,
    #                "height_m": 25.6, "storage_mcm": 99.2, "type": "earthfill"}
  },
  "terrain": {
    "dem": "aws_terrarium",          # aws_terrarium | gee_glo30 | file:<path>
    "zoom": 12,                      # terrarium zoom (12 ~ 38 m, 13 ~ 19 m)
    "corridor_length_km": 30,        # downstream reach to model
    "corridor_width_km": 6,          # lateral corridor half-extent around river
    "resolution_m": 30               # resample to this UTM grid spacing
  },
  "roughness": {"landcover": "none", "default_n": 0.05},  # worldcover_gee | none
  "breach": {
    "mode": "overtopping",           # overtopping | piping | instantaneous
    "method": "froehlich_2008",
    "case": "expected",              # low | expected | high
    "release_fraction": 0.6,         # fraction of reservoir volume released
    "failure_fraction": 1.0          # fraction of dam length breached (instantaneous)
  },
  "solvers": ["screening"],          # screening | delft3d_fm | dualsphysics
  "run": {"duration_h": 24, "dt_s": 60},
  "exports": ["shp", "kml", "gpkg", "tif", "csv"]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .paths import repo_root  # noqa: F401  (re-exported for convenience)
from .ingestion.dams import lookup_dam

DEM_SOURCES = ("aws_terrarium", "gee_glo30")
SOLVERS = ("screening", "delft3d_fm", "dualsphysics")
BREACH_MODES = ("overtopping", "piping", "instantaneous")
BREACH_CASES = ("low", "expected", "high")
EXPORT_FORMATS = ("shp", "kml", "gpkg", "tif", "csv")


@dataclass
class DamSpec:
    name: str
    lat: float
    lon: float
    dam_type: str = "earthfill"
    height_m: float | None = None
    length_m: float | None = None
    storage_mcm: float | None = None  # gross storage, million m^3
    river: str | None = None
    state: str | None = None
    registry_verified: bool = False

    @property
    def storage_m3(self) -> float | None:
        return None if self.storage_mcm is None else self.storage_mcm * 1e6


@dataclass
class TerrainSpec:
    dem: str = "aws_terrarium"
    zoom: int = 12
    corridor_length_km: float = 30.0
    corridor_width_km: float = 6.0
    resolution_m: float = 30.0
    mesh_resolution_m: float = 60.0  # D-Flow FM mesh spacing (delft3d solver)
    dem_path: str | None = None  # when dem == "file:<path>"


@dataclass
class RoughnessSpec:
    landcover: str = "none"  # none | worldcover_gee
    default_n: float = 0.05


@dataclass
class BreachSpec:
    mode: str = "overtopping"
    method: str = "froehlich_2008"
    case: str = "expected"
    release_fraction: float = 0.6
    failure_fraction: float = 1.0


@dataclass
class RunSpec:
    duration_h: float = 24.0
    dt_s: float = 60.0
    attenuation_km: float | None = None  # exponential volume loss length scale
    sph_timemax_s: float | None = None   # SPH simulated horizon (default: capped 300 s)


@dataclass
class Scenario:
    scenario_id: str
    dam: DamSpec
    terrain: TerrainSpec = field(default_factory=TerrainSpec)
    roughness: RoughnessSpec = field(default_factory=RoughnessSpec)
    breach: BreachSpec = field(default_factory=BreachSpec)
    solvers: list[str] = field(default_factory=lambda: ["screening"])
    run: RunSpec = field(default_factory=RunSpec)
    exports: list[str] = field(default_factory=lambda: ["shp", "kml", "gpkg", "tif", "csv"])
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_dam(cfg: dict[str, Any]) -> DamSpec:
    d = dict(cfg.get("dam") or {})
    if not d:
        raise ValueError("scenario requires a 'dam' block (registry name or inline attributes)")
    override = d.pop("override", {}) or {}
    if "lat" in d and "lon" in d:
        base = d
    else:
        name = d.get("name") or ""
        if not name:
            raise ValueError("'dam' needs either lat/lon or a registry 'name'")
        found = lookup_dam(name)
        if found is None:
            raise ValueError(
                f"dam '{name}' not found in registry; "
                "check spelling or give inline lat/lon/height/storage"
            )
        keep = (
            "name", "lat", "lon", "type", "height_m", "length_m",
            "storage_mcm", "river", "state", "verified",
        )
        base = {k: v for k, v in found.items() if k in keep and v not in (None, "")}
    base.update(override)
    known = set(DamSpec.__dataclass_fields__)
    base.setdefault("name", "unnamed-dam")
    # Registry attribute name -> DamSpec field name.
    field_map = {"type": "dam_type", "verified": "registry_verified"}
    kwargs = {}
    for key, value in base.items():
        target = field_map.get(key, key)
        if target in known:
            kwargs[target] = value
    missing = [f for f in ("lat", "lon") if f not in kwargs]
    if missing:
        raise ValueError(f"dam spec missing required fields: {missing}")
    return DamSpec(**kwargs)


def _check_enum(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"{what} '{value}' not supported; choose from {allowed}")
    return value


def load_scenario(source: str | Path | dict[str, Any]) -> Scenario:
    """Load and validate a scenario from a JSON path, JSON string, or dict."""
    if isinstance(source, (str, Path)):
        text = str(source)
        if text.strip().startswith("{"):
            cfg = json.loads(text)
        else:
            with open(source, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
    else:
        cfg = dict(source)

    if not cfg.get("scenario_id"):
        raise ValueError("scenario requires 'scenario_id'")

    dam = _resolve_dam(cfg)

    t = dict(cfg.get("terrain") or {})
    dem = t.get("dem", "aws_terrarium")
    dem_path = None
    if dem.startswith("file:"):
        dem_path = dem[5:]
        if not Path(dem_path).exists():
            raise FileNotFoundError(f"DEM file not found: {dem_path}")
    elif dem not in DEM_SOURCES:
        raise ValueError(f"terrain.dem '{dem}' not supported; use {DEM_SOURCES} or 'file:<path>'")
    terrain = TerrainSpec(
        dem=dem,
        zoom=int(t.get("zoom", 12)),
        corridor_length_km=float(t.get("corridor_length_km", 30.0)),
        corridor_width_km=float(t.get("corridor_width_km", 6.0)),
        resolution_m=float(t.get("resolution_m", 30.0)),
        mesh_resolution_m=float(t.get("mesh_resolution_m", 60.0)),
        dem_path=dem_path,
    )

    r = dict(cfg.get("roughness") or {})
    roughness = RoughnessSpec(
        landcover=_check_enum(r.get("landcover", "none"), ("none", "worldcover_gee"), "roughness.landcover"),
        default_n=float(r.get("default_n", 0.05)),
    )

    b = dict(cfg.get("breach") or {})
    breach = BreachSpec(
        mode=_check_enum(b.get("mode", "overtopping"), BREACH_MODES, "breach.mode"),
        method=str(b.get("method", "froehlich_2008")),
        case=_check_enum(b.get("case", "expected"), BREACH_CASES, "breach.case"),
        release_fraction=float(b.get("release_fraction", 0.6)),
        failure_fraction=float(b.get("failure_fraction", 1.0)),
    )

    run_cfg = dict(cfg.get("run") or {})
    run = RunSpec(
        duration_h=float(run_cfg.get("duration_h", 24.0)),
        dt_s=float(run_cfg.get("dt_s", 60.0)),
        attenuation_km=(
            float(run_cfg["attenuation_km"]) if run_cfg.get("attenuation_km") is not None else None
        ),
        sph_timemax_s=(
            float(run_cfg["sph_timemax_s"]) if run_cfg.get("sph_timemax_s") is not None else None
        ),
    )

    solvers = list(cfg.get("solvers") or ["screening"])
    for s in solvers:
        _check_enum(s, SOLVERS, "solvers entry")

    exports = list(cfg.get("exports") or ["shp", "kml", "gpkg", "tif", "csv"])
    for e in exports:
        _check_enum(e, EXPORT_FORMATS, "exports entry")

    return Scenario(
        scenario_id=str(cfg["scenario_id"]),
        description=str(cfg.get("description", "")),
        dam=dam,
        terrain=terrain,
        roughness=roughness,
        breach=breach,
        solvers=solvers,
        run=run,
        exports=exports,
    )
