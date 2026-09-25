"""CLI for Phase 83's end-to-end uncertainty benchmark (spec addendum Phase 83). Logic lives in
`experiments/uncertainty.py` and `experiments/uncertainty_benchmark.py` (importable, unit-tested).

    python -m scripts.run_uncertainty_benchmark --root experiments_data
    python -m scripts.run_uncertainty_benchmark --root experiments_data --levels small medium --draws 10

Bootstraps the observed packets of real Phase 68 cells through the real pipeline and reports whether the
propagated band widens as completeness falls, and how honest the propagated probabilities are. Cells run in
throwaway directories under `<root>/uncertainty_scratch`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.matrix_runner import TOPOLOGY_LEVELS
from experiments.uncertainty_benchmark import DRAWS, SEEDS, format_report, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", choices=list(TOPOLOGY_LEVELS), default=list(TOPOLOGY_LEVELS))
    parser.add_argument("--draws", type=int, default=DRAWS)
    parser.add_argument("--seeds", nargs="*", type=int, default=SEEDS)
    args = parser.parse_args()
    rows = run_benchmark(args.root, levels=args.levels, seeds=args.seeds, draws=args.draws)
    print(f"levels {args.levels}; seeds {args.seeds}; {args.draws} bootstrap draws per cell; {len(rows)} cells\n")
    print(format_report(rows))


if __name__ == "__main__":
    main()
