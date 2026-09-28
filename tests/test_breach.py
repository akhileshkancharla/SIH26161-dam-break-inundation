import numpy as np
import pytest

from dam_break.breach import (
    breach_parameters,
    froehlich_1995_peak,
    froehlich_2008_breach_width,
    froehlich_2008_failure_time,
    hydrograph_from_breach,
    hydrograph_volume,
    weir_peak,
)


def test_froehlich_1995_peak_hand_value():
    # Vw = 1e6 m3, Hw = 10 m: Qp = 0.607 * 1e6^0.295 * 10^1.24
    expected = 0.607 * 1e6**0.295 * 10**1.24
    assert froehlich_1995_peak(1e6, 10.0) == pytest.approx(expected, rel=1e-12)


def test_froehlich_2008_width_overtopping_vs_piping():
    vw, hb = 5e6, 20.0
    over = froehlich_2008_breach_width(vw, hb, "overtopping")
    pipe = froehlich_2008_breach_width(vw, hb, "piping")
    assert over / pipe == pytest.approx(1.4)


def test_failure_time_reasonable_minutes_scale():
    # Teton-like: Vw=3e8, Hb=30 -> ~3 hours, definitely not days.
    tf = froehlich_2008_failure_time(3e8, 30.0)
    assert 1 * 3600 < tf < 6 * 3600


def test_weir_peak_positive():
    assert weir_peak(100.0, 20.0) == pytest.approx(1.7 * 100 * 20**1.5)


def test_breach_parameters_cases_bracket():
    kw = dict(
        mode="overtopping", case="expected", storage_m3=1e8,
        release_fraction=0.6, dam_height_m=25.0,
    )
    low = breach_parameters(**{**kw, "case": "low"})
    high = breach_parameters(**{**kw, "case": "high"})
    assert low.peak_flow_m3s < high.peak_flow_m3s
    assert low.failure_time_s > high.failure_time_s


def test_hydrograph_volume_conserved():
    p = breach_parameters(
        mode="overtopping", case="expected", storage_m3=1e8,
        release_fraction=0.6, dam_height_m=25.0,
    )
    t, q = hydrograph_from_breach(p, dt_s=30.0, duration_h=48.0)
    vol = hydrograph_volume(t, q)
    assert vol == pytest.approx(p.volume_m3, rel=0.02)


def test_hydrograph_peak_matches_params():
    p = breach_parameters(
        mode="piping", case="expected", storage_m3=5e7,
        release_fraction=0.8, dam_height_m=15.0,
    )
    t, q = hydrograph_from_breach(p, dt_s=60.0)
    # Peak lands on the first grid point at/after tf, so allow small undershoot.
    assert q.max() == pytest.approx(p.peak_flow_m3s, rel=0.01)
    assert q.max() <= p.peak_flow_m3s + 1e-9
    assert q[0] == 0.0


def test_instantaneous_needs_length():
    with pytest.raises(ValueError):
        breach_parameters(
            mode="instantaneous", case="expected", storage_m3=1e8,
            release_fraction=1.0, dam_height_m=30.0, dam_length_m=None,
        )
