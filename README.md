# SIH26161 — Dam Break Inundation Modelling

A scenario-based framework for dam-break / river-blockage inundation analysis:
breach hydrograph generation, rapid screening inundation, adapters for
**Delft3D FM** (regional solver) and **DualSPHysics** (near-field SPH),
satellite (Sentinel-1/GEE) near-real-time flood mapping, exposure analysis,
and SHP/KML export — all driven by one scenario JSON.

## Quickstart

Local (Python 3.10+):

```bash
git clone https://github.com/akhileshkancharla/SIH26161-dam-break-inundation.git
cd SIH26161-dam-break-inundation
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -e .
python scripts/run_pipeline.py configs/scenarios/machhu2_1979.json
```

Colab (recommended for training/heavy runs):

```
https://colab.research.google.com/github/akhileshkancharla/SIH26161-dam-break-inundation/blob/main/notebooks/01_run_pipeline_colab.ipynb
```

The notebook clones the repo, installs the package, runs the pipeline on a
demo dam, exports SHP/KML, and has optional GEE flood-mapping and
DualSPHysics (GPU) sections.

Dashboard (Streamlit shell over the same pipeline):

```bash
streamlit run dashboard/app.py
```

## What a run does

```
scenario JSON ─► dam registry lookup ─► DEM ingest (AWS terrarium / GEE GLO30 / file)
        │                                        │
        ▼                                        ▼
  breach module                          terrain prep: UTM, depression fill,
  (Froehlich 1995/2008,                  flow-path trace, corridor clip
   weir for instantaneous)                       │
        │ hydrograph (volume-conserving)         ▼
        ├─────────────► screening solver (volume-fill along the river)
        ├─────────────► Delft3D FM adapter   [milestone 2 — needs dflowfm]
        └─────────────► DualSPHysics adapter [milestone 3 — needs GPU]
                         │
                         ▼
        rasters (COG) ─ polygons ─ SHP / GPKG / KML ─ exposure ─ summary.json
```

Outputs land in `outputs/<scenario_id>/<timestamp>/`:
`hydrograph.csv/png`, `depth_max.tif`, `arrival_min.tif`,
`velocity_max.tif`, `hazard(_class).tif`, inundation `.shp.zip` / `.gpkg` /
`.kml`, class/exposure CSVs, `summary.json`, preview PNGs.

## Scenario JSON

See `configs/scenarios/` for the two presets (Machhu-II 1979 replay;
South Lhonak / Teesta 2023 GLOF). Key fields:

| Field | Meaning |
| --- | --- |
| `dam` | registry name (+ optional `override`) or inline lat/lon/height/storage |
| `terrain.dem` | `aws_terrarium` (no auth) \| `gee_glo30` \| `file:<path>` |
| `terrain.corridor_length_km` / `corridor_width_km` | downstream reach to model |
| `breach.mode` | `overtopping` \| `piping` \| `instantaneous` |
| `breach.case` | `low` \| `expected` \| `high` uncertainty bracket |
| `breach.release_fraction` | share of reservoir storage released |
| `solvers` | any of `screening`, `delft3d_fm`, `dualsphysics` |
| `run.attenuation_km` | optional volume-loss length scale (screening) |

Overrides without editing files:

```bash
python scripts/run_pipeline.py configs/scenarios/machhu2_1979.json \
    --override breach.case=high --override breach.release_fraction=0.8
```

## Repository layout

```
configs/datasets/dams_india.csv   demo dam registry (NRLD/GeoDAR subset)
configs/scenarios/                scenario presets
src/dam_break/
  config.py        scenario schema + validation
  breach/          Froehlich 1995/2008, weir, volume-conserving hydrograph
  ingestion/       DEM (AWS terrarium / GEE GLO30 / file), WorldCover, dam registry
  preparation/     UTM reprojection, priority-flood fill, flow-path trace,
                   roughness mapping, DEM→STL for SPH
  solvers/         screening (volume-fill), delft3d adapter, sph adapter
  postprocess/     COG rasters, depth polygons, SHP/KML exports, CSI/F1 metrics
  exposure/        land-cover exposure overlay
  satellite/       Sentinel-1 GEE flood mapping (UN-SPIDER practice)
  pipeline.py      end-to-end orchestration
scripts/run_pipeline.py           CLI entry point
notebooks/01_run_pipeline_colab.ipynb   Colab training/run notebook
dashboard/app.py                  Streamlit GUI shell
tests/                            pytest suite (offline)
```

## Solvers — status and honesty

- **screening** — runs anywhere (pure numpy/scipy). A volume-conserving
  cross-section fill along the traced river; for triage and demos only.
  Outputs are always labelled "screening".
- **delft3d_fm** — full model builder works (hydrolib-core + meshkernel):
  rectangular mesh from the DEM window, bed level from samples, reservoir
  polygon with full-pool initial level, native `dambreak` structure with
  Verheij–van der Knaap growth timed by the Froehlich failure time,
  downstream water-level boundary on the mesh edge the river exits,
  observation points every 2 km, Manning friction. Executing needs the
  `dflowfm` binary (Linux/WSL/Colab via conda — see the notebook's Optional C;
  `DFLOWFM_BIN` env var). Mesh spacing via `terrain.mesh_resolution_m`
  (default 60 m; ~392k cells for the Machhu corridor).
- **dualsphysics** — real v5.4 XML case generation (validated by running
  GenCase on synthetic AND real Machhu terrain: 78k fluid / 33k boundary
  particles at dp=4 m for a 1.2 km near-field). Terrain enters as STL in
  local coordinates (UTM offsets break float32 precision); reservoir is a
  fillbox; the dam body is omitted (instantaneous full breach — progressive
  breaching is D-Flow FM's dambreak structure). The full driver runs
  GenCase -> solver -> PartVTK -> binned depth raster when binaries exist.
  The public clone ships GenCase + post tools; the **solver** comes from the
  full package (dual.sphysics.org, registration) or compiling `src/` on
  Linux. Env vars: `DUALSPHYSICS_ROOT`, `DUALSPHYSICS_GENCASE`,
  `DUALSPHYSICS_SOLVER`, `DUALSPHYSICS_PARTVTK`.

## Data sources & attribution

- DEM: Mapzen/AWS Open Data **Terrain Tiles** (terrarium); Copernicus **GLO-30**
  via GEE (project `COPERNICUS/DEM/GLO30`).
- Land cover: ESA **WorldCover v200** (CC-BY-4.0).
- Flood mapping: **Copernicus Sentinel-1** GRD via Google Earth Engine;
  JRC Global Surface Water for permanent-water masking.
- Dam attributes: National Register of Large Dams (CWC) and GeoDAR v1.1 —
  values in `configs/datasets/dams_india.csv` are **demo-grade until
  verified**; see `docs/verification-log.md`.

## Development

```bash
pip install -e .[dev]
pytest            # offline test suite
python scripts/make_colab_notebook.py   # regenerate the Colab notebook
```

## Roadmap

1. ✅ Data pipeline + DEM ingestion + dam registry + breach module + screening
2. ◐ Delft3D FM: model builder done; execution + validation run pending the binary
3. ◐ DualSPHysics: v5.4 case generation + GenCase validation done; solver execution + benchmark convergence pending the solver binary
4. ⏳ Solver comparison (arrival/peak/extent CSI) + depth-damage loss analysis
5. ⏳ GEE near-real-time watchlist (scheduled Sentinel-1 re-checks)
6. ⏳ Dashboard polish: results map with time slider, scenario library, PDF report
