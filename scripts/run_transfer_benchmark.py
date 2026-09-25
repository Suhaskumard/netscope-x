"""CLI for Phase 81's cross-topology transfer benchmark (spec addendum Phase 81). Logic lives in
`experiments/transfer_benchmark.py` (importable, unit-tested); this is a thin wrapper, the same pattern as
`scripts/run_sequence_benchmark.py`.

Leave-one-archetype-out over the Phase 18 topology families; role (Naive Bayes) and anomaly (LSTM vs MAD)
models are scored in-distribution, zero-shot, few-shot and from scratch:

    python -m scripts.run_transfer_benchmark --root experiments_data
    python -m scripts.run_transfer_benchmark --root experiments_data --task role

Captures are written under `<root>/captures/`; nothing is added to `<root>/experiments`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.transfer_benchmark import (
    format_anomaly_table,
    format_degradation_table,
    format_role_table,
    run_transfer_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--task", choices=("role", "anomaly", "both"), default="both")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--hidden", type=int, default=16)
    args = parser.parse_args()

    tasks = ("role", "anomaly") if args.task == "both" else (args.task,)
    result = run_transfer_benchmark(args.root, epochs=args.epochs, hidden=args.hidden, tasks=tasks)

    print(f"archetypes: {', '.join(result.archetypes)}")
    print(f"seeds: train {result.train_seeds}, support {result.support_seeds}, test {result.test_seeds}\n")
    if result.role_rows:
        print("## Role model\n" + format_role_table(result) + "\n")
    if result.anomaly_rows:
        print("## Anomaly model\n" + format_anomaly_table(result) + "\n")
    if result.role_rows and result.anomaly_rows:
        print("## Degradation (in-distribution minus zero-shot)\n" + format_degradation_table(result) + "\n")
    for archetype, seconds in result.fold_seconds.items():
        print(f"{archetype}: {seconds:.1f}s")


if __name__ == "__main__":
    main()
