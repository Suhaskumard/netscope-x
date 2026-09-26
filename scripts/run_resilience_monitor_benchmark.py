"""CLI for Phase 89's resilience monitoring benchmark (spec addendum Phase 89). Logic lives in
`experiments/resilience_monitor_benchmark.py` (importable); this is a thin wrapper.

    python -m scripts.run_resilience_monitor_benchmark --root experiments_data
    python -m scripts.run_resilience_monitor_benchmark --root experiments_data --levels small --seeds 42

Removes a real node's traffic from a capture (controlled failure), pushes the snapshots through the Phase 88 sync
daemon into the resilience monitor, and checks the connectivity alert fires iff the independently computed ratio
crosses the threshold, is observable (in-memory + JSONL), and resolves on restoration. Scratch captures live under
`<root>/resilience_monitor_scratch` and are deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments import resilience_monitor_benchmark as B


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    parser.add_argument("--skip-sweep", action="store_true")
    args = parser.parse_args()
    print(B.format_matrix(B.run_matrix(args.root, args.levels, args.seeds)))
    if not args.skip_sweep:
        print("\nWhat-if sweep cost (healthy graph):\n" + B.sweep_cost(args.root))


if __name__ == "__main__":
    main()
