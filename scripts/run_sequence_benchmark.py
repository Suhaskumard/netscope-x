"""CLI for Phase 78's LSTM-vs-MAD anomaly-detection benchmark (spec addendum Phase 78). Logic lives in
`experiments/sequence_anomaly_benchmark.py` (importable, unit-tested); this is a thin wrapper, the same
pattern as `scripts/run_experiment_matrix.py`.

Both detectors are scored on Phase 76's labeled injected-anomaly datasets. Leave-one-topology-level-out:
the LSTM is trained on normal baseline epochs of the other five matrix topologies and tested on the
held-out one with disjoint seeds:

    python -m scripts.run_sequence_benchmark --root experiments_data
    python -m scripts.run_sequence_benchmark --root experiments_data --n-test-seeds 5 --n-train-seeds 5

Captures are written under `<root>/captures/seqbench-*`; nothing is added to `<root>/experiments`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.sequence_anomaly_benchmark import (
    TEST_SEEDS,
    TRAIN_SEEDS,
    VARIANTS,
    format_cold_start_table,
    format_method_table,
    run_sequence_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--n-test-seeds", type=int, default=len(TEST_SEEDS), help="Test seeds start at 42.")
    parser.add_argument("--n-train-seeds", type=int, default=len(TRAIN_SEEDS), help="Training seeds start at 100.")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--hidden", type=int, default=16)
    args = parser.parse_args()

    result = run_sequence_benchmark(
        args.root,
        test_seeds=list(range(42, 42 + args.n_test_seeds)),
        train_seeds=list(range(100, 100 + args.n_train_seeds)),
        hidden=args.hidden,
        epochs=args.epochs,
    )

    print(f"Test seeds {result.test_seeds}; training seeds {result.train_seeds}; history lengths {result.history_lengths}.")
    for level, info in result.fold_info.items():
        print(f"  held out {level}: {info['training_histories']:.0f} training histories, "
              f"{info['training_samples']:.0f} samples, {info['parameters']:.0f} parameters, "
              f"threshold {info['threshold']:.2f}, final loss {info['final_loss']:.3f}, "
              f"{info['training_seconds']:.1f}s")
    print(f"MAD detections on PORTS/PROTOCOLS dropped from the shared-dimension comparison: "
          f"{result.dropped_mad_novelty_detections}")
    for variant in VARIANTS:
        print(f"\n### {variant} traffic: cold-start sweep (all topologies, all completeness levels)\n")
        print(format_cold_start_table(result, variant))
        print(f"\n### {variant} traffic: per topology and completeness, 8 baseline epochs available\n")
        print(format_method_table(result, variant, max(result.history_lengths)))


if __name__ == "__main__":
    main()
