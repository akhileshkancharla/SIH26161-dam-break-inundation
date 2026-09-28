import pytest

from dam_break.config import load_scenario
from dam_break.ingestion.dams import lookup_dam, load_registry


def test_registry_loads_and_has_verified_columns():
    df = load_registry()
    assert {"name", "lat", "lon", "verified"} <= set(df.columns)
    assert len(df) >= 10


def test_lookup_fuzzy():
    row = lookup_dam("machhu-ii")
    assert row is not None
    assert row["name"].lower().startswith("machhu")
    row2 = lookup_dam("TEESTA III")
    assert row2 is not None


def test_scenario_from_registry(tmp_path):
    scenario = load_scenario({
        "scenario_id": "t",
        "dam": {"name": "Machhu-II", "override": {"storage_mcm": 90.0}},
    })
    assert scenario.dam.storage_mcm == 90.0
    assert scenario.dam.height_m is not None
    assert scenario.solvers == ["screening"]


def test_scenario_inline_dam():
    scenario = load_scenario({
        "scenario_id": "t",
        "dam": {"name": "custom", "lat": 10.0, "lon": 20.0,
                "height_m": 12.0, "storage_mcm": 5.0},
    })
    assert scenario.dam.lat == 10.0
    assert scenario.dam.storage_m3 == 5e6


def test_scenario_json_file_roundtrip(tmp_path):
    import json
    cfg = {
        "scenario_id": "t",
        "dam": {"name": "Machhu-II"},
        "breach": {"case": "high"},
    }
    p = tmp_path / "s.json"
    p.write_text(json.dumps(cfg))
    scenario = load_scenario(p)
    assert scenario.breach.case == "high"
    d = scenario.to_dict()
    assert d["scenario_id"] == "t"


def test_scenario_rejects_bad_solver():
    with pytest.raises(ValueError):
        load_scenario({"scenario_id": "t", "dam": {"name": "Machhu-II"},
                       "solvers": ["nan"]})


def test_scenario_missing_dam():
    with pytest.raises(ValueError):
        load_scenario({"scenario_id": "t"})
