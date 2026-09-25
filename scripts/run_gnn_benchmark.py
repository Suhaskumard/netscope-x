"""CLI for Phase 77's GNN-vs-heuristic edge benchmark (spec addendum Phase 77). Logic lives in
`experiments/gnn_benchmark.py` (importable, unit-tested); this is a thin wrapper, the same pattern as
`scripts/run_experiment_matrix.py`.

Leave-one-topology-level-out: for each of the six matrix topologies the GNN is trained on the other five
(training seeds) and scored on the held-out one (test seeds) by Phase 32's
`compare_topology_to_ground_truth`, next to the existing noisy-OR heuristic:

    python -m scripts.run_gnn_benchmark --root experiments_data
    python -m scripts.run_gnn_benchmark --root experiments_data --n-test-seeds 10 --n-train-seeds 5

Captures are written under `<root>/captures/gnn-*`; nothing is added to `<root>/experiments`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.gnn_benchmark import (
    TEST_SEEDS,
    TRAIN_SEEDS,
    VARIANTS,
    format_benchmark_table,
    format_edge_flow_table,
    run_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--n-test-seeds", type=int, default=len(TEST_SEEDS), help="Test seeds start at 42.")
    parser.add_argument("--n-train-seeds", type=int, default=len(TRAIN_SEEDS), help="Training seeds start at 100.")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--hidden", type=int, default=16)
    parser.add_argument("--embedding", type=int, default=8)
    args = parser.parse_args()

    result = run_benchmark(
        args.root,
        test_seeds=list(range(42, 42 + args.n_test_seeds)),
        train_seeds=list(range(100, 100 + args.n_train_seeds)),
        hidden=args.hidden,
        embedding=args.embedding,
        epochs=args.epochs,
    )

    print(f"Test seeds {result.test_seeds}; training seeds {result.train_seeds}; {result.epochs} epochs.")
    for level, size in result.fold_training_sizes.items():
        print(f"  held out {level}: {size['training_examples']} training examples, "
              f"{size['training_pairs']} node pairs, {size['parameters']} parameters, "
              f"final loss {result.final_losses[level]:.4f}")
    for variant in VARIANTS:
        for metric in ("f1", "precision", "recall"):
            print(f"\n### {variant} traffic: edge {metric}\n")
            print(format_benchmark_table(result, variant, metric))
    print("\n### GNN edge flow and calibration\n")
    print(format_edge_flow_table(result))


if __name__ == "__main__":
    main()
