"""Milestone-4 tests: solver comparison and depth-damage loss."""

import numpy as np
import pytest
from rasterio.transform import Affine

from dam_break.postprocess.comparison import (
    RasterField, compare_depth, align_to_reference, comparison_map,
)
from dam_break.exposure.damage import (
    damage_fraction, loss_from_landcover, DAMAGE_CURVES,
)


def _field(values, origin=(0.0, 1000.0), cell=10.0, name=""):
    arr = np.asarray(values, dtype=float)
    transform = Affine(cell, 0, origin[0], 0, -cell, origin[1])
    return RasterField(arr, transform, "EPSG:32645", name)


def test_perfect_agreement_scores_one():
    ref = _field([[0, 1, 2], [0, 3, 0]], name="ref")
    same = _field([[0, 1.2, 2.1], [0, 2.8, 0]], name="same")
    out = compare_depth(ref, same)
    assert out["csi"] == pytest.approx(1.0)
    assert out["pod"] == pytest.approx(1.0)
    assert out["far"] == pytest.approx(0.0)
    assert out["depth_bias_m"] == pytest.approx(np.mean([0.2, 0.1, -0.2]))


def test_disjoint_masks_score_zero():
    ref = _field([[1, 1, 0], [0, 0, 0]], name="ref")
    other = _field([[0, 0, 0], [0, 2, 2]], name="other")
    out = compare_depth(ref, other)
    assert out["csi"] == pytest.approx(0.0)
    assert out["false_alarms"] == 2 and out["misses"] == 2


def test_alignment_across_grids():
    """Other raster at half the resolution, offset by one cell."""
    ref = _field(np.ones((4, 4)), origin=(0, 40), cell=10, name="ref")
    coarse = _field(np.ones((2, 2)), origin=(5, 35), cell=20, name="coarse")
    aligned = align_to_reference(ref, coarse)
    assert aligned.shape == ref.array.shape
    assert np.isfinite(aligned).all()
    out = compare_depth(ref, coarse)
    assert out["overlap_cells"] == 16
    assert out["csi"] == pytest.approx(1.0)


def test_comparison_map_written(tmp_path):
    ref = _field([[0, 1], [1, 0]], name="ref")
    other = _field([[0, 1], [0, 0]], name="other")
    out = comparison_map(ref, other, tmp_path / "cmp.png")
    assert out is not None and out.exists()


def test_damage_curve_monotonic_and_capped():
    for group, knots in DAMAGE_CURVES.items():
        depths = np.linspace(0, 10, 41)
        fracs = damage_fraction(group, depths)
        assert np.all(np.diff(fracs) >= -1e-9), group
        assert fracs.max() <= knots[-1][1] + 1e-9
        assert fracs.min() == 0.0
    assert damage_fraction("built_up", 1.0) == pytest.approx(0.25)
    assert damage_fraction("cropland", 0.5) == pytest.approx(0.50)


def test_loss_computation_and_class_merging():
    # 4x4 grid, 10 m cells (100 m2): 3 wet cropland cells (code 40),
    # 2 wet built-up cells (code 50), plus code 80 (also cropland group).
    depth = np.array([
        [0.0, 1.0, 1.0, 0.0],
        [2.0, 2.0, 0.0, 0.5],
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
    ])
    lc = np.array([
        [40, 40, 40, 40],
        [50, 50, 80, 80],
        [0, 0, 0, 0],
        [40, 40, 40, 40],
    ])
    out = loss_from_landcover(depth, lc, cell_area_m2=100.0)
    by = out["by_class"]
    # cropland: codes 40 and 80 merge; wet cells = (0,1),(0,2),(1,3)? no:
    # (0,1)=40 d1, (0,2)=40 d1, (1,3)=80 d0.5, (3,0)=40 d1 -> 4 cells
    assert by["cropland"]["hit_cells"] == 4
    assert set(by["cropland"]["worldcover_codes"]) == {40, 80}
    assert by["built_up"]["hit_cells"] == 2
    # cropland loss: fractions at [1,1,0.5,1] -> [0.70, 0.70, 0.50, 0.70]
    expected_crop = (0.70 + 0.70 + 0.50 + 0.70) * 100.0 * 150.0
    assert by["cropland"]["indicative_loss_inr"] == pytest.approx(expected_crop, rel=1e-6)
    # built-up at 2 m -> 0.38
    expected_built = 2 * 0.38 * 100.0 * 8000.0
    assert by["built_up"]["indicative_loss_inr"] == pytest.approx(expected_built, rel=1e-6)
    assert out["total_indicative_loss_inr"] == pytest.approx(expected_crop + expected_built)
    assert out["total_indicative_loss_crore_inr"] == pytest.approx(
        (expected_crop + expected_built) / 1e7)


def test_snap_to_thalweg():
    from dam_break.preparation.terrain import snap_to_thalweg
    z = np.full((40, 40), 100.0)
    z[20:23, 10:30] = 90.0          # channel east-west
    z[15, 15] = 95.0                # dam coordinate on a valley side
    transform = Affine(30.0, 0, 0, 0, -30.0, 40 * 30)
    r, c, offset = snap_to_thalweg(z, 15, 15, transform, search_radius_m=300)
    assert z[r, c] == 90.0
    assert 0 < offset <= 300 * 1.5
    # already on the thalweg -> no move
    r2, c2, off2 = snap_to_thalweg(z, 21, 20, transform)
    assert (r2, c2) == (21, 20)
    assert off2 == 0.0
