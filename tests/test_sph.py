"""DualSPHysics adapter tests (offline + optional GenCase validation)."""

from pathlib import Path

import numpy as np
import pytest
import xml.etree.ElementTree as ET
from rasterio.transform import Affine

from dam_break.breach import breach_parameters
from dam_break.ingestion.dem import DEMData
from dam_break.preparation.geometry import dem_to_stl, dem_to_xyz
from dam_break.solvers.sph import (
    find_tools, nearfield_patch, particles_to_depth, parse_vtk_points,
    write_case_xml,
)

CELL, NY, NX = 10.0, 240, 300


def _valley_dem() -> DEMData:
    x = np.arange(NX) * CELL
    y = np.arange(NY) * CELL
    xx, yy = np.meshgrid(x, y)
    z = 100.0 - 0.004 * xx + np.abs(yy - (NY - 1) / 2 * CELL) * 0.05
    return DEMData(z=z, transform=Affine(CELL, 0, 0, 0, -CELL, NY * CELL),
                   crs="EPSG:32645", source="synthetic", bbox_wgs84=(0, 0, 1, 1))


def _breach():
    return breach_parameters(mode="overtopping", case="expected",
                             storage_m3=50e6, release_fraction=0.6,
                             dam_height_m=20.0)


def test_case_xml_schema(tmp_path):
    xml = write_case_xml(
        tmp_path, dp=2.0,
        pointmin=(-30, -30, 90), pointmax=(1230, 640, 140),
        stl_file="terrain.stl",
        water_point=(60, 30, 95), water_size=(360, 550, 25),
        timemax_s=300, timeout_s=15,
    )
    root = ET.parse(xml).getroot()
    assert root.tag == "case"
    assert root.find("./casedef/constantsdef/gravity").get("z") == "-9.81"
    definition = root.find("./casedef/geometry/definition")
    assert definition.get("dp") == "2"
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    assert mainlist.find("drawfilestl").get("file") == "terrain.stl"
    assert mainlist.find("drawbox/boxfill").text == "solid"
    params = {p.get("key"): p.get("value")
              for p in root.findall("./execution/parameters/parameter")}
    assert params["TimeMax"] == "300"
    assert params["StepAlgorithm"] == "2"
    assert params["Kernel"] == "2"


def test_nearfield_patch_bounds():
    dem = _valley_dem()
    z, transform = nearfield_patch(dem, (NY // 2, 30), length_m=1200, width_m=600)
    assert z.shape[0] * CELL == pytest.approx(610, abs=20)
    assert z.shape[1] * CELL == pytest.approx(1200, abs=20)
    assert np.isfinite(z).all()


def test_dem_to_xyz_format(tmp_path):
    dem = _valley_dem()
    out = dem_to_xyz(dem.z, dem.transform, tmp_path / "bed.xyz",
                     target_spacing_m=5.0)
    lines = out.read_text().splitlines()
    assert len(lines) == dem.z.shape[0] * dem.z.shape[1]  # step=1 (5 m < cell)
    first = lines[0].split()
    assert len(first) == 3
    float(first[0]), float(first[1]), float(first[2])


def test_dem_to_stl_writes_triangles(tmp_path):
    dem = _valley_dem()
    out = dem_to_stl(dem.z, dem.transform, tmp_path / "t.stl", coarsen=10)
    size = out.stat().st_size
    n_tri = (size - 84) // 50  # binary STL: 84-byte header + 50 bytes/triangle
    assert n_tri > 100


def test_parse_vtk_points_ascii(tmp_path):
    vtk = tmp_path / "p.vtk"
    vtk.write_text(
        "# vtk DataFile Version 3.0\nvtk output\nASCII\nDATASET POLYDATA\n"
        "POINTS 3 float\n1.0 2.0 3.0\n4.0 5.0 6.0\n7.0 8.0 9.0\n"
        "VERTICES 0 0\nPOINT_DATA 3\n"
    )
    pts = parse_vtk_points(vtk)
    assert pts.shape == (3, 3)
    assert pts[1].tolist() == [4.0, 5.0, 6.0]


def test_particles_to_depth_binning():
    pts = np.array([
        [1.0, 3.0, 10.0], [1.5, 2.5, 10.5],   # 2 particles, top-left cell
        [3.0, 3.0, 10.0],                     # 1 particle, top-right cell
        [99.0, 99.0, 10.0],                    # outside extent
    ])
    depth = particles_to_depth(pts, (0, 0, 4, 4), cell=2.0)
    assert depth.shape == (2, 2)
    assert depth[0, 0] == pytest.approx(4.0)   # 2 particles x 2 m
    assert depth[0, 1] == pytest.approx(2.0)
    assert depth[1, 1] == pytest.approx(0.0)   # outside dropped


def test_find_tools_returns_object():
    tools = find_tools()
    assert hasattr(tools, "gencase")
    if tools.gencase is not None:
        assert tools.gencase.exists()


@pytest.mark.skipif(find_tools().gencase is None,
                    reason="DualSPHysics GenCase not available")
def test_gencase_validates_our_case(tmp_path):
    """Full validation: our generated case must be accepted by GenCase."""
    from dam_break.solvers.sph import run_gencase

    dem = _valley_dem()
    z, transform = nearfield_patch(dem, (NY // 2, 30), length_m=600, width_m=300)
    cell = abs(transform.a)
    local = Affine(cell, 0, 0, 0, -cell, z.shape[0] * cell)
    dem_to_stl(z, local, tmp_path / "terrain.stl", coarsen=1)
    lx, ly = z.shape[1] * cell, z.shape[0] * cell
    write_case_xml(
        tmp_path, dp=5.0,
        pointmin=(-30, -30, float(z.min()) - 10),
        pointmax=(lx + 30, ly + 30, float(z.max()) + 30),
        stl_file="terrain.stl",
        water_point=(30, 30, float(z.min())),
        water_size=(lx * 0.3, ly - 60, 15.0),
        timemax_s=60, timeout_s=5,
    )
    (tmp_path / "CaseSph_out").mkdir()
    ok, log = run_gencase(tmp_path, "CaseSph", find_tools().gencase)
    assert ok, f"GenCase rejected the case:\n{log[-500:]}"
    assert (tmp_path / "CaseSph_out" / "CaseSph.bi4").exists()
    out_txt = (tmp_path / "CaseSph_out" / "CaseSph.out")
    assert "Total particles" in out_txt.read_text(errors="replace")
