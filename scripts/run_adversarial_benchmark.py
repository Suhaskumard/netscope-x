"""CLI for Phase 84's adversarial robustness benchmark (spec addendum Phase 84). Logic lives in
`experiments/adversarial/` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_adversarial_benchmark --root experiments_data
    python -m scripts.run_adversarial_benchmark --root experiments_data --levels medium large --seeds 42 43

Runs each crafted-traffic attack through the real pipeline (clean vs attacked, default vs hardened) and prints
degradation, whether hardening recovers it, and every attack that stays successful. Cells run in throwaway
directories under `<root>/adversarial_scratch`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.adversarial.benchmark import LEVELS, SEEDS, format_report, run_benchmark, secondary_report
from experiments.matrix_runner import TOPOLOGY_LEVELS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", choices=list(TOPOLOGY_LEVELS), default=list(LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    args = parser.parse_args()
    cells, summaries = run_benchmark(args.root, levels=args.levels, seeds=args.seeds)
    print(f"levels {args.levels}; seeds {args.seeds}; {len(cells)} scored cells\n")
    print(format_report(summaries))
    print("\n" + secondary_report(cells))


if __name__ == "__main__":
    main()
