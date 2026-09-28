#!/usr/bin/env python
"""Generate notebooks/01_run_pipeline_colab.ipynb (run from repo root)."""

import json
from pathlib import Path

REPO_URL = "https://github.com/akhileshkancharla/SIH26161-dam-break-inundation"

cells = []


def md(src):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": src})


def code(src):
    cells.append({
        "cell_type": "code", "metadata": {},
        "source": src, "outputs": [], "execution_count": None,
    })


md(f"""# SIH 26161 — Dam Break Inundation Pipeline (Colab)

One notebook to clone the repo and run the full pipeline:

1. **Setup** — clone repo, install the `dam_break` package.
2. **Scenario** — pick a dam (Machhu-II 1979 replay or South Lhonak/Teesta 2023) and set breach parameters.
3. **Run** — fetch DEM, compute the breach hydrograph, run the screening solver, export SHP/KML.
4. **Explore** — view maps, download outputs.
5. **Optional A** — Sentinel-1 near-real-time flood mapping in Google Earth Engine (Teesta 2023 event).
6. **Optional B** — DualSPHysics on the T4 GPU (near-field SPH).

> CPU runtime is enough for stages 1-4. Choose a GPU runtime
> (Runtime -> Change runtime type -> T4 GPU) only for stage 6.""")

md("## 1. Setup — clone the repo and install")
code(f"""# Clone the repository (skipped if it already exists, e.g. after a reconnect)
![ -d SIH26161-dam-break-inundation ] || git clone {REPO_URL}.git
%cd SIH26161-dam-break-inundation
!git pull --quiet 2>/dev/null || true

# Install dependencies + the package.
# NOT editable (-e): editable installs register their path via a .pth file
# that the already-running Colab kernel ignores (it is only read at
# interpreter startup), so `import dam_break` would fail without a restart.
# A regular install puts the package in site-packages and imports at once.
%pip install -q .

import os, sys
if os.path.isdir('src'):
    sys.path.insert(0, 'src')   # prefer the repo checkout over the installed copy
import dam_break
print('dam_break version:', dam_break.__version__)""")

md("""## 2. Scenario — pick a dam and set parameters

The dam registry (`configs/datasets/dams_india.csv`) is a demo subset of
NRLD/GeoDAR. Attribute values marked `verified=False` are demo-grade —
check them against the National Register of Large Dams before quoting.""")
code("""import pandas as pd
from dam_break.ingestion.dams import load_registry

pd.set_option('display.width', 120)
registry = load_registry()
registry[['name', 'river', 'state', 'type', 'height_m', 'storage_mcm', 'verified']]""")

code("""# Choose the scenario: 'machhu2_1979' or 'teesta_south_lhonak_2023'
SCENARIO = 'machhu2_1979'

# Quick parameter overrides (see configs/scenarios/*.json for all knobs)
OVERRIDES = {
    'breach.case': 'expected',   # low | expected | high
    'breach.release_fraction': 0.6,
}""")

md("## 3. Run the pipeline end to end")
code("""import json
from pathlib import Path
from dam_break.config import load_scenario
from dam_break.pipeline import run_pipeline

cfg = json.loads(Path(f'configs/scenarios/{SCENARIO}.json').read_text())

def apply_override(cfg, dotted, value):
    keys = dotted.split('.')
    node = cfg
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value

for k, v in OVERRIDES.items():
    apply_override(cfg, k, v)

summary = run_pipeline(load_scenario(cfg), out_root='outputs')""")

md("## 4. Explore the results")
code("""# Breach summary
b = summary['breach']
print(f"Peak flow:        {b['peak_flow_m3s']:,.0f} m3/s")
print(f"Failure time:     {b['failure_time_min']:.0f} min")
print(f"Breach width:     {b['breach_width_m']:.0f} m")
print(f"Released volume:  {b['volume_m3']/1e6:.1f} Mm3")

d = summary['solvers']['screening']['diagnostics']
print(f"Inundated area:   {d['inundated_area_km2']:.1f} km2")
print(f"Path length:      {d['path_length_km']:.1f} km")
print(f"Front arrival at reach end: {d['arrival_last_min']:.0f} min")
for note in summary['solvers']['screening']['notes']:
    print('note:', note)""")

code("""# Preview maps
from IPython.display import Image, display
run_dir = Path(summary['run_dir'])
for png in sorted(run_dir.rglob('*.png')):
    print(png.relative_to(run_dir))
    display(Image(str(png), width=700))""")

code("""# Interactive map of the inundation polygons (depth classes)
import geopandas as gpd

gpkg = next((run_dir / 'screening').glob('*.gpkg'))
gdf = gpd.read_file(gpkg)
print(gdf.drop(columns='geometry').to_string(index=False))
gdf.explore(column='dclass', cmap='Blues', tooltip=['dclass', 'area_ha', 'maxdepth'])""")

code("""# Download the SHP (zip) and KML exports
from google.colab import files

for pattern in ('*.shp.zip', '*.kml'):
    for f in (run_dir / 'screening').glob(pattern):
        files.download(str(f))""")

md("""## Optional A — Sentinel-1 flood mapping in GEE (near-real-time module)

Maps the actual 4 Oct 2023 South Lhonak GLOF extent around the lower Teesta
using the UN-SPIDER change-detection practice. Requires a Google account
authorized for Earth Engine (research/non-commercial use).""")

code("""# One-time authentication (follow the link), then initialize
import ee
from dam_break.satellite import init_ee, flood_mask, flood_area_km2

try:
    ee.Initialize(project='your-ee-project-id')   # <- set your Cloud project id
except Exception:
    ee.Authenticate()
    ee.Initialize(project='your-ee-project-id')

aoi = ee.Geometry.Rectangle([88.10, 27.25, 88.80, 27.95])  # Teesta below the lake
mask = flood_mask(
    aoi,
    before=('2023-09-15', '2023-09-30'),   # pre-event window
    after=('2023-10-05', '2023-10-12'),    # post-event window
)
print(f'flooded area: {flood_area_km2(mask, aoi):.1f} km2')""")

code("""# Visual check: S1 before/after and the flood mask
import geemap  # %pip install -q geemap if missing

before = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(aoi) \\
    .filterDate('2023-09-15', '2023-09-30').select('VV').median()
after = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(aoi) \\
    .filterDate('2023-10-05', '2023-10-12').select('VV').median()

Map = geemap.Map(center=[27.6, 88.45], zoom=9)
Map.addLayer(before, {'min': -25, 'max': 5}, 'S1 VV before')
Map.addLayer(after, {'min': -25, 'max': 5}, 'S1 VV after')
Map.addLayer(mask.selfMask(), {'palette': ['red']}, 'flood')
Map""")

md("""## Optional B — DualSPHysics near-field case on the T4 GPU

The SPH solver covers the near-field reach only (dam + first km). This cell
clones the DualSPHysics repository (a prebuilt Linux tree; compiling from
source on Colab is fragile) and runs a small standard dam-break benchmark to
verify the toolchain. Our adapter (`dam_break.solvers.sph`) writes the case
files for real-terrain runs — see the repo README, milestone 3.""")

code("""# Clone DualSPHysics and locate the Linux binaries (T4 GPU runtime)
![ -d DualSPHysics ] || git clone --depth 1 https://github.com/DualSPHysics/DualSPHysics.git
import os, shutil
from pathlib import Path

dsp = Path('DualSPHysics')
bins = [p for p in dsp.rglob('*') if p.is_file() and 'linux' in str(p.parent).lower()]
print(f'{len(bins)} linux binaries found')
print('set DAM_BREAK env:' , os.environ.get('DUALSPHYSICS_ROOT', '(not set)'))
if dsp.exists():
    os.environ['DUALSPHYSICS_ROOT'] = str(dsp.resolve())
    print('DUALSPHYSICS_ROOT =', os.environ['DUALSPHYSICS_ROOT'])
!nvidia-smi -L 2>/dev/null || echo 'no GPU runtime'""")

code("""# Generate our near-field case files for the selected dam and inspect them
from dam_break.pipeline import run_pipeline  # noqa: F401 (already run above)
from dam_break.solvers.sph import run_sph
from dam_break.ingestion.dem import fetch_dem, DEMData
from dam_break.config import load_scenario
from dam_break.breach import breach_parameters
import rasterio.warp, numpy as np

sc = load_scenario(cfg)
bbox = (sc.dam.lon - 0.2, sc.dam.lat - 0.2, sc.dam.lon + 0.2, sc.dam.lat + 0.2)
dem = fetch_dem(sc.terrain, bbox)
xs, ys = rasterio.warp.transform('EPSG:4326', dem.crs, [sc.dam.lon], [sc.dam.lat])
inv = ~dem.transform
col, row = inv * (xs[0], ys[0])
rc = (int(np.clip(row, 0, dem.shape[0]-1)), int(np.clip(col, 0, dem.shape[1]-1)))

breach = breach_parameters(
    mode=sc.breach.mode, case=sc.breach.case, storage_m3=sc.dam.storage_m3,
    release_fraction=sc.breach.release_fraction, dam_height_m=sc.dam.height_m)
res = run_sph(dem, rc, breach, Path('outputs/sph_case'))
print('\\n'.join(res.notes))""")

md("""## Optional C — Delft3D FM regional model (CPU, experimental)

The framework builds a complete D-Flow FM case (mesh + bed level +
reservoir initial level + native dambreak structure + boundary + obs
points). Executing it needs the Linux `dflowfm` binary; on Colab the
route is condacolab + the Deltares conda channel. This recipe is
experimental — verify channel/package names (tracked in
docs/verification-log.md) before relying on it.""")

code("""# 1) Build the case with our pipeline (no binary needed; self-contained)
from pathlib import Path
import rasterio.warp, numpy as np
from dam_break.config import load_scenario
from dam_break.ingestion.dem import fetch_dem
from dam_break.breach import breach_parameters, hydrograph_from_breach
from dam_break.pipeline import _bbox_around, _dam_rowcol, _clip_to_corridor
from dam_break.solvers.delft3d.adapter import run_delft3d

sc = load_scenario(cfg)
bbox = _bbox_around(sc.dam.lat, sc.dam.lon, sc.terrain.corridor_length_km * 1.6 / 111.0)
dem = fetch_dem(sc.terrain, bbox)
rc = _dam_rowcol(dem, sc.dam.lat, sc.dam.lon)
dem, rc = _clip_to_corridor(dem, rc, sc.terrain.corridor_length_km, sc.terrain.corridor_width_km)

breach = breach_parameters(
    mode=sc.breach.mode, case=sc.breach.case, storage_m3=sc.dam.storage_m3,
    release_fraction=sc.breach.release_fraction, dam_height_m=sc.dam.height_m)
t, q = hydrograph_from_breach(breach, dt_s=60.0, duration_h=sc.run.duration_h)

# 120 m mesh keeps Colab runtimes manageable; use 60 m for the final run
res = run_delft3d(dem, rc, breach, t, q, 0.05, Path('outputs/delft3d_manual'),
                  path_xy=None, duration_s=sc.run.duration_h * 3600,
                  mesh_resolution_m=120.0)
print(json.dumps(res.diagnostics, indent=1, default=str))
print('case ready at:', res.diagnostics['mdu'])""")

code("""# 2) (Experimental) install dflowfm via conda and run the case.
# NOTE: condacolab restarts the runtime once; re-run this cell afterwards.
%pip install -q condacolab
import condacolab
condacolab.install()""")

code("""# After the condacolab restart, run this cell (same notebook):
!mamba install -y -c deltares delft3dfm
import os
os.environ['DFLOWFM_BIN'] = 'dflowfm'   # once installed on PATH

case_dir = 'outputs/delft3d_manual'     # from the build cell above
%cd {case_dir}
!dflowfm flowfm.mdu
# Map output: output/flowfm_map.nc -> post-process with the same
# dam_break.postprocess tools used for the screening solver.""")

md("""## Next steps

- **Delft3D FM:** the case builder is done; execution needs `dflowfm`
  (Linux/WSL/Colab via conda, Optional C). Then compare arrival/peak/extent
  against the screening solver with `dam_break.postprocess.metrics`.
- **Full SPH runs (milestone 3):** run the generated case with the
  DualSPHysics binaries on the T4; keep `dp` >= 2 m and the domain <= 2 km.
- **Save outputs to Drive** so long runs survive session timeouts:
  `from google.colab import drive; drive.mount('/content/drive')` and pass
  `out_root='/content/drive/MyDrive/SIH26161'`.
- Everything run here is reproducible locally:
  `python scripts/run_pipeline.py configs/scenarios/machhu2_1979.json`.""")


notebook = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        " colab": {"provenance": [], "gpuType": "T4"},
        "kernelspec": {"name": "python3", "display_name": "Python 3"},
        "language_info": {"name": "python"},
        "accelerator": "GPU",
    },
    "cells": cells,
}

# Source fields must be lists of lines in ipynb JSON.
for c in notebook["cells"]:
    src = c["source"]
    c["source"] = src.splitlines(keepends=True)

out = Path("notebooks/01_run_pipeline_colab.ipynb")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
print(f"wrote {out} with {len(cells)} cells")
