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
