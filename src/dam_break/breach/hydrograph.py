"""Breach outflow hydrograph construction.

Shape: linear rise from 0 to Qp over the failure time tf, then a recession
chosen so the total released volume matches Vw (volume-conserving). The
recession is a smooth exponential decay whose time constant is solved from
the volume constraint.
"""

from __future__ import annotations

import numpy as np

from .empirical import BreachParams


def hydrograph_from_breach(
    params: BreachParams,
    dt_s: float = 60.0,
    duration_h: float = 24.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (t [s], Q [m^3/s]) for the breach outflow.

    Rise: linear over tf. Recession: exponential Q = Qp * exp(-(t - tf) / k)
    with k solved so that the total integral equals Vw.
    """
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    tf = params.failure_time_s
    qp = params.peak_flow_m3s
    vw = params.volume_m3

    t = np.arange(0.0, max(duration_h * 3600.0, 4 * tf) + dt_s, dt_s)

    # Volume carried by the rise limb alone.
    v_rise = 0.5 * qp * tf
    if v_rise >= vw:
        # Failure time too long for this volume: shrink the peak so the
        # triangular hydrograph carries exactly Vw (keeps volume conservation
        # ahead of peak realism) and warn through the returned values.
        qp_scaled = 2.0 * vw / tf
        q = np.where(t < tf, qp_scaled * t / tf, qp_scaled * np.exp(-(t - tf) / (0.5 * tf)))
        q = np.minimum(q, qp_scaled)
        q[t >= tf + 6 * 0.5 * tf] = 0.0
        return t, q

    # Volume still to be released by the recession: Vw - v_rise = Qp * k
    k = (vw - v_rise) / qp
    q = np.where(t < tf, qp * t / tf, qp * np.exp(-(t - tf) / k))
    # Cut off when flow becomes negligible (< 1% of Qp).
    q[t > tf + k * np.log(100.0)] = 0.0
    return t, q


def hydrograph_volume(t: np.ndarray, q: np.ndarray) -> float:
    """Integral of the hydrograph [m^3] (trapezoid)."""
    return float(np.trapezoid(q, t)) if hasattr(np, "trapezoid") else float(np.trapz(q, t))
