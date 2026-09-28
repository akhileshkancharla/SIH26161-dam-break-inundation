#!/usr/bin/env python
"""Run the dam-break pipeline from a scenario JSON.

Usage:
    python scripts/run_pipeline.py configs/scenarios/machhu2_1979.json
    python scripts/run_pipeline.py configs/scenarios/teesta_south_lhonak_2023.json \
        --out outputs --override breach.case=high
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dam_break.config import load_scenario  # noqa: E402
from dam_break.pipeline import run_pipeline  # noqa: E402


def _apply_override(cfg: dict, override: str) -> None:
    key, _, value = override.partition("=")
    path = key.split(".")
    node = cfg
    for p in path[:-1]:
        node = node.setdefault(p, {})
    try:
        node[path[-1]] = json.loads(value)
    except json.JSONDecodeError:
        node[path[-1]] = value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scenario", help="path to a scenario JSON")
    ap.add_argument("--out", default=None, help="output root (default: outputs/)")
    ap.add_argument("--override", action="append", default=[],
                    help="dotted override, e.g. breach.case=high (JSON values)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.scenario, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    for ov in args.override:
        _apply_override(cfg, ov)

    scenario = load_scenario(cfg)
    summary = run_pipeline(scenario, out_root=args.out, quiet=args.quiet)
    if not args.quiet:
        print(json.dumps({k: v for k, v in summary.items() if k != "solvers"},
                         indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
