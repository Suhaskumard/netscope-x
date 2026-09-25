"""CLI for Phase 85's incremental-topology benchmark (spec addendum Phase 85). Logic lives in
`experiments/incremental_topology_benchmark.py` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_incremental_topology_benchmark --root experiments_data
    python -m scripts.run_incremental_topology_benchmark --root experiments_data --levels small medium --seeds 42

Streams captures through `IncrementalTopology` and, after every chunk, compares flows/nodes/edges with a
from-scratch batch rebuild of the same prefix (exact model equality); then times per-chunk update vs batch rebuild.
Scratch batch captures live under `<root>/incremental_scratch` and are deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.incremental_topology_benchmark import (
    COMPLETENESS,
    LEVELS,
    SEEDS,
    format_equivalence,
    format_speed,
    run_equivalence,
    run_speed,
)
from experiments.matrix_runner import TOPOLOGY_LEVELS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", choices=list(TOPOLOGY_LEVELS), default=list(LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    parser.add_argument("--skip-speed", action="store_true")
    args = parser.parse_args()
    rows = run_equivalence(args.root, levels=args.levels, seeds=args.seeds, completeness=COMPLETENESS)
    print(f"levels {args.levels}; completeness {list(COMPLETENESS)}; seeds {args.seeds}; {len(rows)} streams\n")
    print(format_equivalence(rows))
    if not args.skip_speed:
        print("\n" + format_speed(run_speed(args.root)))


if __name__ == "__main__":
    main()
