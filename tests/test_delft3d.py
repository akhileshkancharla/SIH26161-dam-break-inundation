"""D-Flow FM model builder tests (offline, synthetic terrain)."""

import numpy as np
import pytest
from rasterio.transform import Affine

from dam_break.breach import breach_parameters
from dam_break.ingestion.dem import DEMData

hydrolib = pytest.importorskip(
    "hydrolib.core.dflowfm", reason="hydrolib-core not installed"
)
pytest.importorskip("meshkernel", reason="meshkernel not installed")

from dam_break.solvers.delft3d.model_builder import build_dflowfm_case  # noqa: E402


CELL = 100.0
NY, NX = 100, 160  # 16 km x 10 km


def _valley_dem() -> DEMData:
    x = np.arange(NX) * CELL
    y = np.arange(NY) * CELL
    xx, yy = np.meshgrid(x, y)
    z = 100.0 - 0.004 * xx + np.abs(yy - (NY - 1) / 2 * CELL) * 0.05
    transform = Affine(CELL, 0.0, 0.0, 0.0, -CELL, NY * CELL)
    return DEMData(z=z, transform=transform, crs="EPSG:32645",
                   source="synthetic", bbox_wgs84=(0, 0, 1, 1))


def _path_xy() -> np.ndarray:
    xs = np.arange(10, NX - 20) * CELL
    ys = np.full_like(xs, (NY - 1) / 2 * CELL, dtype=float)
    return np.column_stack([xs, ys])


def _breach():
    return breach_parameters(
        mode="overtopping", case="expected", storage_m3=50e6,
        release_fraction=0.6, dam_height_m=20.0,
    )


def test_build_case_writes_all_files(tmp_path):
    dem = _valley_dem()
    case = build_dflowfm_case(
        dem=dem, dam_rowcol=(NY // 2, 10), dam_xy=(10 * CELL, (NY / 2) * CELL),
        path_xy=_path_xy(), breach=_breach(), duration_s=6 * 3600,
        out_dir=tmp_path, mesh_resolution_m=200.0, n_manning=0.05,
    )
    for key, path in case.files.items():
        if path is None:
            continue
        assert path.exists(), f"missing {key}: {path}"
    assert case.mdu_path.exists()

    info = case.info
    assert info["mesh_cells"] == pytest.approx(80 * 50, rel=0.15)
    assert info["breach_failure_time_s"] > 0
    assert info["crest_level_m"] > info["pool_level_m"]
    assert info["downstream_boundary"] == "east"
    assert info["observation_points"] >= 5
    assert info["bed_samples"] > 100


def test_mdu_reloads_with_sidecar_files(tmp_path):
    dem = _valley_dem()
    case = build_dflowfm_case(
        dem=dem, dam_rowcol=(NY // 2, 10), dam_xy=(10 * CELL, (NY / 2) * CELL),
        path_xy=_path_xy(), breach=_breach(), duration_s=6 * 3600,
        out_dir=tmp_path, mesh_resolution_m=250.0,
    )
    from hydrolib.core.dflowfm import FMModel

    # Sidecars use bare names; resolve them from the run dir (as dflowfm does).
    import os
    cwd = os.getcwd()
    os.chdir(case.run_dir)
    try:
        fm = FMModel(filepath=case.mdu_path)  # parses mdu + linked files
    finally:
        os.chdir(cwd)
    assert fm.time.tstop > 0
    assert fm.physics.uniffricttype == 1
    structures = fm.geometry.structurefile[0]
    db = structures.structure[0]
    assert db.type == "dambreak"
    assert db.timetobreachtomaximumdepth == pytest.approx(_breach().failure_time_s)
    assert len(fm.geometry.inifieldfile.initial) == 2


def test_boundary_side_selection(tmp_path):
    """Flow exiting through the north edge puts the boundary on north."""
    dem = _valley_dem()
    # Path turning north and leaving the top edge.
    xs = np.arange(10, NX - 10) * CELL
    ys = np.full(len(xs), (NY - 1) / 2 * CELL, dtype=float)
    ys[-30:] = np.linspace(ys[-31], NY * CELL + 500.0, 30)
    case = build_dflowfm_case(
        dem=dem, dam_rowcol=(NY // 2, 10), dam_xy=(10 * CELL, (NY / 2) * CELL),
        path_xy=np.column_stack([xs, ys]), breach=_breach(), duration_s=3600,
        out_dir=tmp_path, mesh_resolution_m=250.0,
    )
    assert case.info["downstream_boundary"] == "north"
