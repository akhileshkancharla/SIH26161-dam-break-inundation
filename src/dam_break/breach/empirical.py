"""Empirical embankment-dam breach relations.

Conventions (SI units throughout):
    Vw : reservoir volume above the breach bottom [m^3]
    Hw : water depth above the breach bottom [m]
    Hb : breach (dam) height [m]
    B_avg : average breach width [m]
    tf  : failure (formation) time [s]

Relations implemented (constants as given in the SIH26161 technical guide;
dimensional checks pass but re-verify against the original papers before
publishing results):

    Froehlich (1995) peak outflow:
        Qp = 0.607 * Vw^0.295 * Hw^1.24                      [m^3/s]
    Froehlich (2008) average breach width:
        B_avg = 0.27 * Ko * Vw^0.32 * Hb^0.04                [m]
        Ko = 1.4 overtopping, 1.0 piping
    Froehlich (2008) failure time:
        tf = 63.2 * sqrt(Vw / (g * Hb^2))                    [s]

Instantaneous (concrete/masonry) failure is represented as flow over a
broad-crested weir: Q = Cw * B * H^1.5 with Cw ~ 1.7 (SI).
"""

from __future__ import annotations

from dataclasses import dataclass
import math

G = 9.81  # m/s^2

# Uncertainty brackets around the regression estimates. Froehlich (2008) is
# explicitly about the large uncertainty of these relations; these factors
# give indicative low/expected/high envelopes, not confidence intervals.
CASE_FACTORS: dict[str, dict[str, float]] = {
    "low": {"q": 0.6, "tf": 1.5, "b": 0.7},
    "expected": {"q": 1.0, "tf": 1.0, "b": 1.0},
    "high": {"q": 1.4, "tf": 0.7, "b": 1.3},
}


@dataclass
class BreachParams:
    mode: str                 # overtopping | piping | instantaneous
    case: str                 # low | expected | high
    volume_m3: float          # Vw, volume released through the breach
    water_depth_m: float      # Hw
    breach_height_m: float    # Hb
    peak_flow_m3s: float      # Qp
    breach_width_m: float     # B_avg
    failure_time_s: float     # tf
    method: str = "froehlich_2008"

    @property
    def failure_time_min(self) -> float:
        return self.failure_time_s / 60.0


def froehlich_1995_peak(volume_m3: float, water_depth_m: float) -> float:
    """Qp [m^3/s] = 0.607 * Vw^0.295 * Hw^1.24."""
    if volume_m3 <= 0 or water_depth_m <= 0:
        raise ValueError("Vw and Hw must be positive")
    return 0.607 * volume_m3**0.295 * water_depth_m**1.24


def froehlich_2008_breach_width(volume_m3: float, breach_height_m: float, mode: str) -> float:
    """B_avg [m] = 0.27 * Ko * Vw^0.32 * Hb^0.04; Ko=1.4 overtopping, 1.0 piping."""
    if volume_m3 <= 0 or breach_height_m <= 0:
        raise ValueError("Vw and Hb must be positive")
    ko = 1.4 if mode == "overtopping" else 1.0
    return 0.27 * ko * volume_m3**0.32 * breach_height_m**0.04


def froehlich_2008_failure_time(volume_m3: float, breach_height_m: float) -> float:
    """tf [s] = 63.2 * sqrt(Vw / (g * Hb^2)).

    Reported in seconds; sanity-checked against well-documented cases
    (e.g. ~3 h for Teton-scale volumes), but re-verify against the paper.
    """
    if volume_m3 <= 0 or breach_height_m <= 0:
        raise ValueError("Vw and Hb must be positive")
    return 63.2 * math.sqrt(volume_m3 / (G * breach_height_m**2))


def weir_peak(width_m: float, head_m: float, coeff: float = 1.7) -> float:
    """Broad-crested weir flow Q [m^3/s] = Cw * B * H^1.5 (SI)."""
    if width_m <= 0 or head_m <= 0:
        raise ValueError("breach width and head must be positive")
    return coeff * width_m * head_m**1.5


def breach_parameters(
    *,
    mode: str,
    case: str,
    storage_m3: float | None,
    release_fraction: float,
    dam_height_m: float | None,
    dam_length_m: float | None = None,
    failure_fraction: float = 1.0,
    method: str = "froehlich_2008",
) -> BreachParams:
    """Turn dam attributes + scenario choices into breach parameters.

    ``storage_m3`` is the (gross) reservoir storage; Vw is the volume released
    through the breach = storage * release_fraction. For instantaneous failure
    of concrete/masonry dams the peak is weir flow over the failed section.
    """
    if case not in CASE_FACTORS:
        raise ValueError(f"case must be one of {list(CASE_FACTORS)}")
    if release_fraction <= 0 or release_fraction > 1:
        raise ValueError("release_fraction must be in (0, 1]")
    if storage_m3 is None or storage_m3 <= 0:
        raise ValueError("reservoir storage (storage_mcm on the dam or override) is required")
    if dam_height_m is None or dam_height_m <= 0:
        raise ValueError("dam height (height_m on the dam or override) is required")

    factors = CASE_FACTORS[case]
    vw = storage_m3 * release_fraction
    hb = dam_height_m
    hw = dam_height_m  # worst case: full pool to breach invert

    if mode == "instantaneous":
        if not dam_length_m or dam_length_m <= 0:
            raise ValueError("instantaneous mode needs the dam length (length_m)")
        width = max(dam_length_m * failure_fraction, 1.0)
        qp = weir_peak(width, hw) * factors["q"]
        tf = 60.0 * factors["tf"]  # near-instantaneous: 1 minute envelope
        b_avg = width
    else:
        qp = froehlich_1995_peak(vw, hw) * factors["q"]
        b_avg = froehlich_2008_breach_width(vw, hb, mode) * factors["b"]
        tf = froehlich_2008_failure_time(vw, hb) * factors["tf"]

    return BreachParams(
        mode=mode,
        case=case,
        volume_m3=vw,
        water_depth_m=hw,
        breach_height_m=hb,
        peak_flow_m3s=qp,
        breach_width_m=b_avg,
        failure_time_s=max(tf, 1.0),
        method=method,
    )
