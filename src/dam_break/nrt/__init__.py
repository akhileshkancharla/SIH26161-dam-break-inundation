"""Near-real-time GEE flood mapping over the dam watchlist (milestone 5)."""

from .flood_map import (
    DEFAULT_CHANGE_DB,
    DEFAULT_WATER_DB,
    aoi_box,
    detect_flood,
    s1_composite,
)
from .watchlist import (
    DEFAULT_ALERT_KM2,
    DEFAULT_AOI_KM,
    decide_alert,
    run_watchlist,
    windows,
)

__all__ = [
    "DEFAULT_ALERT_KM2", "DEFAULT_AOI_KM", "DEFAULT_CHANGE_DB",
    "DEFAULT_WATER_DB", "aoi_box", "decide_alert", "detect_flood",
    "run_watchlist", "s1_composite", "windows",
]
