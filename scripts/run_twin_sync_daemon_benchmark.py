"""CLI for Phase 88's digital-twin sync daemon benchmark (spec addendum Phase 88). Logic lives in
`experiments/twin_sync_daemon_benchmark.py` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_twin_sync_daemon_benchmark --root experiments_data
    python -m scripts.run_twin_sync_daemon_benchmark --root experiments_data --levels small --seeds 42

Replays snapshot sequences through `TwinSyncDaemon` (block/reject, coalescing on/off, rate-limited) and checks the
final twin against a manual on-demand sync chain and a direct build; then measures the rate limit and latency.
Scratch captures live under `<root>/twin_sync_daemon_scratch` and are deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments import twin_sync_daemon_benchmark as B


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    parser.add_argument("--skip-timing", action="store_true")
    args = parser.parse_args()
    rows = B.run_equivalence(args.root, levels=args.levels, seeds=args.seeds)
    print(B.format_equivalence(rows))
    if not args.skip_timing:
        print("\n" + B.format_rate(B.run_rate(args.root)))
        print("\n" + B.latency_summary(args.root))


if __name__ == "__main__":
    main()
