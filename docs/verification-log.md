# Verification log

Track every external fact this repo relies on. Anything not yet checked
against a primary source is marked **TODO** and must be verified before it
appears in final deliverables or the demo.

## Dam registry (`configs/datasets/dams_india.csv`)

Registry attributes are demo-grade (compiled from background knowledge) until
checked against the **National Register of Large Dams (CWC)** and **GeoDAR
v1.1** (doi:10.5281/zenodo.6163413). Coordinates were placed from public
descriptions and must be snapped to the actual structure where marked.

| Entry | Status | Notes |
| --- | --- | --- |
| South Lhonak Lake | coords ✅ 27.9144 N, 88.1836 E (Wikipedia, 27°54′51.95″N 88°11′00.91″E) | lake volume estimate ~58–65 Mm³ (Sattar et al. 2021 / ISRO) — **TODO** pin one source and cite it consistently |
| Teesta III dam | coords ~ ✅ 27.585 N, 88.772 E (27°35′N 88°46′E, Mongabay/ADB reports) | height/storage **TODO** vs NRLD (run-of-river, small storage) |
| Machhu-II | coords 22.810 N, 70.902 E measured **~550-570 m off the thalweg** (sits on the valley side); the pipeline now auto-snaps to the local thalweg (see preparation.terrain.snap_to_thalweg) — still **TODO**: snap to the actual dam structure | height 25.6 m / length 3,571 m / storage 99.2 Mm³ quoted from memory — **TODO** vs NRLD; breach-history numbers (peak outflow, warning time) **TODO** vs CWC/account papers |
| Tehri, Bhakra, Sardar Sarovar, Hirakud, Nagarjuna Sagar, Idukki, Mettur, Ukai, Rihand, Maithon, Panchet | **TODO** all attributes | heights/storages from memory; coordinates ±1 km |

## Breach relations (`src/dam_break/breach/empirical.py`)

Formulas as given in the team technical guide; dimensional sanity checks pass
(Teton-scale case gives ~3 h failure time). Constants **TODO** against the
original papers before publication:

- Froehlich (1995) `Qp = 0.607 Vw^0.295 Hw^1.24`
- Froehlich (2008) `B_avg = 0.27 Ko Vw^0.32 Hb^0.04`, Ko = 1.4 / 1.0
- Froehlich (2008) `tf = 63.2 sqrt(Vw/(g Hb^2))` — units (seconds) inferred
  from sanity check; the paper states minutes with a different constant —
  **TODO** recheck Wahl/Froehlich 2008 directly
- Low/high case factors (0.6/1.4 on Qp, 1.5/0.7 on tf) are our own indicative
  brackets, not published prediction intervals

## GEE dataset IDs

- `COPERNICUS/DEM/GLO30`, `COPERNICUS/S1_GRD`, `COPERNICUS/S2_SR_HARMONIZED`,
  `JRC/GSW1_4/GlobalSurfaceWater`, `ESA/WorldCover/v200` — **TODO** confirm
  each in the current Earth Engine catalog (IDs occasionally change).

## External tools

- DualSPHysics v5.4 (clone verified 2026-09-28): the repo ships GenCase +
  post tools for Windows AND Linux, but NOT the solver — that needs the full
  package (dual.sphysics.org, registration form) or compiling `src/`.
  GenCase accepted our real-terrain STL case (Machhu near-field, dp=4 m:
  78,078 fluid / 32,702 boundary). The native `drawbathymetry`/zpoints route
  SEGFAULTS GenCase — use `drawfilestl` with local coordinates; GenCase VTKs
  are binary, particle counts come from the `.out` text.

  **Solver executed locally (2026-09-28, full v5.4.3 package, CPU build)**:
  Machhu near-field 780x390 m, dp=6 m, 45 s simulated time — GenCase ->
  solver -> PartVTK -> depth raster all work. Pinned formats and gotchas:
  - PartVTK `-savevtk` = legacy **BINARY POLYDATA, big-endian floats** right
    after the `POINTS n float` line (our parser handles it).
  - `-onlytype` filters apply to VTK **only**; `-saveascii` files always
    contain ALL particles (columns x y z id vel.x vel.y vel.z rhop press),
    so never use them for fluid-only extraction.
  - A bare `drawfilestl` terrain is a thin shell: seal the domain floor
    (box under zmin) and thicken the crust (`advanced` + `depth depthmin`),
    or the reservoir drains through gaps and particles exit the domain
    (`NpOutPos` in RunPARTs.csv shows this immediately).
  - Reference the bed to the local **thalweg**, not the dam cell (the dam
    coordinate can sit on a valley side), and clamp the pool to the natural
    rim of the reservoir box — otherwise the pool floods the whole patch.
  - Depth-from-particle-counts (count x dp) quantises at dp: choose
    dp <= ~half the expected flow depth, i.e. GPU-scale runs for real pools.
  **TODO**: GPU run (3050/Colab T4) at dp<=2 m, dambreak benchmark
  convergence study, SPH-vs-Delft3D-vs-screening comparison.
- Delft3D FM: model builder verified against hydrolib-core 1.4.0 + meshkernel
  (24 tests). Executing needs the `dflowfm` binary — **TODO** verify the
  Colab recipe (`condacolab` + `mamba install -c deltares delft3dfm`) and the
  exact channel/package name; also verify the generated case runs (mdu +
  sidecars accepted by the kernel) on Linux/WSL and record the runtime for
  the Machhu case (~392k cells @ 60 m).
- Dambreak structure starter values (f1=f2=1, uCrit=0.5 m/s, algorithm 2
  Verheij–van der Knaap) — **TODO** calibrate against literature/test cases.

## Depth-damage curves (exposure/damage.py)

Starter piecewise curves and INR/m2 asset values assembled from background
knowledge of JRC-style functions (Huizinga et al. 2017) — shape and order of
magnitude only. **TODO**: replace knots and asset values with the actual JRC
report tables and Indian regional sources (NDMA / state disaster authorities)
before quoting any loss figure. Overrides via
`configs/datasets/damage_params.json`.

## Cross-solver comparison caveats (postprocess/comparison.py)

First real comparison (Machhu near-field, SPH dp=6 vs snapped screening,
0.30 km2 overlap): CSI 0.07, POD 0.41, FAR 0.92, SPH depth bias +12.7 m.
Known drivers, to reconcile before reading as model error: the corridor
screening spreads the breach volume over 30 km (little water near the dam)
while SPH holds its whole release in the 800 m window; SPH depth comes from
particle-count x dp (quantised, inflated at dp=6); the SPH pool is
rim-clamped (percentile-based rim) to ~72 m vs the 94.8 m requested. The
metrics themselves are unit-tested (perfect/disjoint/aligned-grid cases).

## Milestone-4 full-chain run (2026-09-29, run 20260929T151918Z, Colab T4 VM, CPU solver)

End-to-end: screening + DualSPHysics + WorldCover(GEE) exposure + loss +
cross-solver comparison. Working Colab recipe: `DUALSPHYSICS_DEVICE=cpu`, `sph_timemax_s=60`,
ee project `tpu-access-492807` (WorldCover fetched at DEM resolution).
Confirmed config from the cell output: **dp=4 m, near-field 1200x632 m,
pool 72.0 m, fluid 39,039 / boundary 151,305 particles, 60 s simulated,
total wall time 5,381.7 s (~90 min)** — i.e. the same case size that the
wedged GPU binary ground on for hours completed on the CPU binary in 90
minutes once it was the only solver on the 2-core VM (the earlier CPU
crawl coincided with the zombie GPU solver burning ~166% CPU).

- GPU verdict: v5.4 GPU binary cannot init on Colab driver 580 / CUDA 13
  (no CUDA context in /proc/<pid>/maps; either refuses at the "Charge
  calculator" shared-memory check or spins on CPU). CPU binary is the
  Colab path; GPU needs DualSPHysics >= v5.6 or an older-driver runtime.
- Exposure (corridor): tree 157 ha, shrubland 539, cropland 536, built-up
  262, bare 186, water 272, grassland 11, wetland 4.
- Indicative loss: **Rs ~776 crore** (built-up ~681, cropland ~92) —
  placeholder curves/values, see caveat above; do not quote externally.
- Comparison (SPH vs screening, 0.5 m threshold): CSI 0.05, POD 0.27,
  FAR 0.94, bias 4.2; SPH wet 0.24 km2 vs screening 0.06 km2 in-window;
  depth bias +10 m (SPH 13 m vs screening 3 m means). Dominant drivers
  are structural, not model error: (a) particle-count x dp quantisation
  makes any wet cell >= dp deep; (b) SPH raster is a max-over-time
  envelope incl. splash; (c) footprints differ — the SPH window contains
  the collapsing reservoir pool (always wet, deep) while screening in the
  same 600 m feeds only breach-flux water. Use the SPH run for
  extent/arrival narrative, not depth accuracy.
- SPH depth raster: 158x300 cells, values quantised in 4 m steps, wet
  0.224 km2, max 32 m (splash), bulk 12-16 m near the dam.

## Milestone 5 — NRT watchlist (2026-09-29)

`dam_break.nrt` implements the guide's Section 7 (UN-SPIDER Sentinel-1
practice) as an automated dam-registry sweep: rolling before/after VV
median composites (50 m focal-median despeckle), flood = (after-before <
-3 dB) AND (after < -15 dB), JRC GSW occurrence>80 excluded, GLO-30
slope>5 deg excluded (configurable — pass None for steep Himalayan
valleys), server-side area stats (one getInfo), reduceToVectors polygons
sieved at 5 ha, alert rule flood >= 25 km2, outputs watchlist.csv +
alerts.json + per-dam KML/GPKG. `satellite.gee_flood` (the manual
single-AOI South Lhonak demo) now delegates to the same core. Thresholds
are guide defaults and need per-site tuning; revisit is days, not live.
GEE-side code is NOT covered by local tests (no ee in CI) — first live
run pending in Colab.

## Milestone 5 — first live watchlist run (2026-09-30, run 20260930T054751Z)

Validated end-to-end on 3 dams after two GEE gotchas: (1) the user's
original project `tpu-access-492807` began returning USER_PROJECT_DENIED
("not found or deleted") — fixed by registering a fresh Cloud project for
Earth Engine; (2) a stacked 3-band `reduceRegion` silently returned zeros
for every band on inputs where three single-band reduces returned correct
values — `area_stats` now does three independent single-band sums in one
`ee.Dictionary` round-trip. Reminder re-learned: after `git pull`, a
Colab kernel keeps the OLD module cached — restart the session before
re-running.

Results (aoi 40x40 km, change -3 dB / water -15 dB, slope mask OFF):
- South Lhonak: water 1348 km2 (!), perm 21.5, flood 2.0 (4 polygons).
  The huge "water" is over-detection: glacier ice and smooth high-valley
  surfaces are dark in VV, and disabling the slope mask (needed to keep
  steep terrain) admits layover/shadow — documented SAR caveats, live.
- Machhu-II: water 310, perm 29.3, flood 47.0 -> ALERT (>= 25 km2),
  125 polygons. Post-monsoon Gujarat: paddy fields and full tanks read
  like water - a textbook threshold-tuning example, not an error.
- Tehri: water 227, perm 7.8, flood 6.9 (30 polygons). Reservoir +
  rivers; the small perm is real (GSW occurrence>80 only counts the
  deepest persistent part of a reservoir filled gradually since 2005).
Status: machinery validated; dB thresholds are demo defaults, tuning
per site remains future work.

## Milestone 6 — Streamlit dashboard (2026-09-30)

`src/dam_break/dashboard/` (app.py + util.py), per guide Section 10's
Streamlit recommendation: sidebar scenario editor (registry dam picker,
breach mode/case, terrain, solver selection — writes/reads the same
scenario JSON schema everything else uses), one-click pipeline run,
and tabs for Overview (Qp/tf/volume/loss metrics), Results map (folium:
transparent depth-raster overlay + depth-class polygons + dam marker),
Impact & loss (loss.csv + crore total), Comparison (JSON + overlap PNG),
NRT watchlist browser (any outputs/nrt sweep + alerts), and Exports
(download buttons for every artifact, incl. .shp zips and .kml).
Helpers (WGS84 bounds reprojection, transparent depth PNG, registry->
scenario dict, artifact listing) are unit-tested (10 tests; 59 total).
App-level smoke test: streamlit headless boot (HTTP 200) +
streamlit.testing AppTest — 0 exceptions, 6 tabs, sidebar wired. The
map/loss tabs execute only after an interactive run — first visual
check pending on the user's machine. Install: pip install ".[dashboard]";
run: streamlit run src/dam_break/dashboard/app.py. FastAPI job-runner
backend (guide 10.2/10.5) deliberately deferred — the library already
separates compute from UI.
