"""Phase 105: longitudinal drift study over a simulated evolving topology, with recalibration checkpoints.

    python -m scripts.run_drift_study --root experiments_data [--weeks 12] [--checkpoints 0 6 11] [--quick]

Real pipeline runs each week with the default constants; at checkpoint weeks the real Phase 82 calibrate() decides whether
recalibration would measurably help. Synthetic evolution only; see docs/architecture/longitudinal_drift.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.drift_study import CHECKPOINT_WEEKS, DRIFT_SEEDS, render_markdown, run_drift_study


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("experiments_data"))
    ap.add_argument("--weeks", type=int, default=12)
    ap.add_argument("--checkpoints", type=int, nargs="*", default=list(CHECKPOINT_WEEKS))
    ap.add_argument("--seeds", type=int, nargs="*", default=list(DRIFT_SEEDS))
    ap.add_argument("--quick", action="store_true", help="tiny BO budget (smoke run, not for conclusions)")
    args = ap.parse_args()
    kw = {"n_init": 3, "n_iter": 2} if args.quick else {}
    report = run_drift_study(args.root, args.weeks, args.seeds, args.checkpoints, **kw)
    print(render_markdown(report))
    print(f"report written to {args.root / 'drift'}")


if __name__ == "__main__":
    main()
