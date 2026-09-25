"""CLI for Phase 87's streaming dependency benchmark (spec addendum Phase 87). Logic lives in
`experiments/streaming_dependency_benchmark.py` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_streaming_dependency_benchmark --root experiments_data
    python -m scripts.run_streaming_dependency_benchmark --root experiments_data --levels small medium --seeds 42

Streams captures through `StreamingDependencyEstimator` and, after every chunk, compares dependencies and causal
candidates with a from-scratch batch run over the same prefix; then times per-chunk incremental vs batch.
Scratch batch captures live under `<root>/streaming_dependency_scratch` and are deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments import streaming_dependency_benchmark as B
from experiments.matrix_runner import TOPOLOGY_LEVELS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", choices=list(TOPOLOGY_LEVELS), default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    parser.add_argument("--skip-speed", action="store_true")
    args = parser.parse_args()
    rows = B.run_equivalence(args.root, levels=args.levels, seeds=args.seeds)
    print(f"levels {args.levels}; completeness {list(B.COMPLETENESS)}; seeds {args.seeds}; {len(rows)} streams\n")
    print(B.format_equivalence(rows))
    if not args.skip_speed:
        print("\n" + B.format_speed(B.run_speed(args.root)))


if __name__ == "__main__":
    main()
