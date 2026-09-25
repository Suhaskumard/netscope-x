"""CLI for Phase 82's automated constant calibration (spec addendum Phase 82). Logic lives in
`experiments/calibration/` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_constant_calibration --root experiments_data
    python -m scripts.run_constant_calibration --root experiments_data --groups topology --n-iter 8

Reports before/after per group and per constant on held-out validation seeds; it never edits `Settings`.
Cells run in throwaway directories under `<root>/calibration_scratch`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.calibration.calibrate import calibrate, format_report
from experiments.calibration.constants import GROUPS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--groups", nargs="*", choices=[g.name for g in GROUPS], default=[g.name for g in GROUPS])
    parser.add_argument("--n-init", type=int, default=6)
    parser.add_argument("--n-iter", type=int, default=18)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    report = calibrate(
        args.root, groups=[g for g in GROUPS if g.name in args.groups],
        n_init=args.n_init, n_iter=args.n_iter, seed=args.seed,
    )
    print(format_report(report))
    print("\nadopted constants:", report.adopted.as_dict())


if __name__ == "__main__":
    main()
