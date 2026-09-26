"""Phase 104: paired t-tests + bootstrap CIs over multi-seed ablation results.

    python -m scripts.run_significance_analysis --root experiments_data --n-seeds 10 [--topologies small medium]

Runs the baseline and each ablation for real, per topology and seed, and reports which ablation effects are significant
(Holm-adjusted) and which are indistinguishable from noise at the sample size actually run.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.significance import render_markdown, run_significance


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("experiments_data"))
    ap.add_argument("--n-seeds", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42, help="first seed")
    ap.add_argument("--topologies", nargs="*", default=None)
    args = ap.parse_args()
    report = run_significance(args.root, args.n_seeds, args.seed, args.topologies)
    print(render_markdown(report))
    print(f"report written to {args.root / 'significance'}")


if __name__ == "__main__":
    main()
