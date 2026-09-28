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
| Machhu-II | coords **TODO** 22.810 N, 70.902 E approx, ~5 km E of Morbi — snap to reservoir | height 25.6 m / length 3,571 m / storage 99.2 Mm³ quoted from memory — **TODO** vs NRLD; breach-history numbers (peak outflow, warning time) **TODO** vs CWC/account papers |
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

- DualSPHysics on Colab: clone-without-compile reported to work (forum);
  compiling from source hit `libdsphchrono.so` issues — **TODO** reproduce on
  a T4 and record the exact working recipe.
- Delft3D FM: `dflowfm` Linux binary route — **TODO** document the install
  (OSS deltares distribution or Docker) on the team laptop/WSL.
