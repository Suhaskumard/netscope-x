"""CLI for Phase 79's time-series-PC vs Phase 53 causal-candidate benchmark (spec addendum Phase 79). Logic
lives in `experiments/causal_discovery_benchmark.py` (importable, unit-tested); this is a thin wrapper, the
same pattern as `scripts/run_experiment_matrix.py`.

Both methods run on the same capture and are scored by Phase 68's `evaluate_causal_analysis`, on Phase 70's
lagged traffic and on a parent-driven control dataset with a well-defined causal structure:

    python -m scripts.run_causal_benchmark --root experiments_data
    python -m scripts.run_causal_benchmark --root experiments_data --n-seeds 10

Captures are written under `<root>/captures/causal-*`; nothing is added to `<root>/experiments`.
Discovered edges are candidates, never proven causation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.causal_discovery_benchmark import (
    DATASETS,
    TEST_SEEDS,
    format_alpha_sweep_table,
    format_benchmark_table,
    format_diagnostics_table,
    run_causal_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--n-seeds", type=int, default=len(TEST_SEEDS), help="Seeds start at 42.")
    args = parser.parse_args()

    result = run_causal_benchmark(args.root, seeds=list(range(42, 42 + args.n_seeds)))

    print(f"Seeds {result.seeds}; {len(result.scores)} scored (method, capture) pairs.")
    if result.dropped_edges:
        print(f"Cyclic declared edges dropped from the parent-driven DAG: {result.dropped_edges}")
    print("\n### Diagnostics (alpha 0.05, pooled)\n")
    print(format_diagnostics_table(result))
    for dataset in DATASETS:
        for metric in ("f1", "skeleton_f1"):
            print(f"\n### {dataset}: {metric}\n")
            print(format_benchmark_table(result, dataset, metric))
    print("\n### PC alpha sweep (completeness 1.0)\n")
    print(format_alpha_sweep_table(result))


if __name__ == "__main__":
    main()
