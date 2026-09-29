"""Run the GEE near-real-time flood watchlist (milestone 5).

Requires ee.Authenticate() + ee.Initialize(project=...) beforehand
(Colab notebook section "Milestone 5" or earthengine authenticate CLI).

Examples:
    python scripts/run_nrt_watchlist.py                      # all registry dams
    python scripts/run_nrt_watchlist.py --dams "Machhu-II,Tehri"
    python scripts/run_nrt_watchlist.py --slope-max-deg none  # steep valleys
"""

from __future__ import annotations

import argparse
import sys

from dam_break.nrt.watchlist import run_watchlist


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dams", default=None,
                   help="comma-separated registry dam names (default: all)")
    p.add_argument("--lookback-days", type=int, default=14)
    p.add_argument("--baseline-days", type=int, default=45)
    p.add_argument("--aoi-km", type=float, default=40.0)
    p.add_argument("--alert-km2", type=float, default=25.0)
    p.add_argument("--slope-max-deg", default="5.0",
                   help="exclude slopes steeper than this; 'none' disables")
    p.add_argument("--change-db", type=float, default=-3.0)
    p.add_argument("--water-db", type=float, default=-15.0)
    p.add_argument("--out", default=None, help="output root (default outputs/nrt)")
    args = p.parse_args(argv)

    slope = None if args.slope_max_deg.lower() == "none" else float(args.slope_max_deg)
    result = run_watchlist(
        dam_ids=args.dams.split(",") if args.dams else None,
        lookback_days=args.lookback_days, baseline_days=args.baseline_days,
        aoi_km=args.aoi_km, alert_km2=args.alert_km2, slope_max_deg=slope,
        change_db=args.change_db, water_db=args.water_db, out_root=args.out)

    width = max(len(r["dam"]) for r in result["rows"])
    print(f"\n{'dam':<{width}}  flood km2   status")
    for r in result["rows"]:
        print(f"{r['dam']:<{width}}  {str(r['flood_km2']):>10}   {r['status']}")
    print(f"\nreport: {result['out_dir']}/watchlist.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
