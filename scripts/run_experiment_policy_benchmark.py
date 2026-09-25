"""CLI for Phase 80's experiment-policy benchmark (spec addendum Phase 80). Logic lives in
`experiments/experiment_policy_benchmark.py` (importable, unit-tested); this is a thin wrapper, the same
pattern as `scripts/run_experiment_matrix.py`.

Compares Phase 67's static experiment ranking with a learned contextual-bandit policy (pre-trained on other
topologies, and cold-started), plus a random baseline, on real accuracy gained per experiment run. The reward
is the twin's real Phase 63 prediction error on each experiment. Leave-one-topology-level-out:

    python -m scripts.run_experiment_policy_benchmark --root experiments_data
    python -m scripts.run_experiment_policy_benchmark --root experiments_data --n-test-seeds 10 --budget 4

Captures are written under `<root>/captures/policy-*`; nothing is added to `<root>/experiments`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.experiment_policy_benchmark import (
    BUDGET,
    TEST_SEEDS,
    TRAIN_SEEDS,
    format_curve_table,
    format_policy_table,
    format_repair_table,
    format_topology_table,
    run_policy_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--n-test-seeds", type=int, default=len(TEST_SEEDS), help="Test seeds start at 42.")
    parser.add_argument("--n-train-seeds", type=int, default=len(TRAIN_SEEDS), help="Training seeds start at 100.")
    parser.add_argument("--budget", type=int, default=BUDGET, help="Experiments per episode.")
    args = parser.parse_args()

    result = run_policy_benchmark(
        args.root,
        test_seeds=list(range(42, 42 + args.n_test_seeds)),
        train_seeds=list(range(100, 100 + args.n_train_seeds)),
        budget=args.budget,
    )
    print(f"Budget {result.budget}; test seeds {result.test_seeds}; training seeds {result.train_seeds}; "
          f"{len(result.episodes)} episodes ({result.skipped_test_cases} twins with no node skipped).")
    for level, count in result.pretraining_episodes.items():
        print(f"  held out {level}: LinUCB pre-trained on {count} episodes")
    print("\n### Accuracy gained per experiment, pooled\n")
    print(format_policy_table(result))
    print("\n### Mean twin accuracy (all nodes) after k experiments\n")
    print(format_curve_table(result))
    print("\n### Gain per experiment (all nodes) by topology\n")
    print(format_topology_table(result))
    print("\n### Gain per experiment (held-out nodes) by topology\n")
    print(format_topology_table(result, "gain_held_per_experiment"))
    print("\n### Twin repairs\n")
    print(format_repair_table(result))


if __name__ == "__main__":
    main()
