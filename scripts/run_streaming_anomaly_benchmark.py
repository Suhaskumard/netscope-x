"""CLI for Phase 86's streaming anomaly-detection benchmark (spec addendum Phase 86). Logic lives in
`experiments/streaming_anomaly_benchmark.py` (importable, unit-tested); this is a thin wrapper.

    python -m scripts.run_streaming_anomaly_benchmark --root experiments_data
    python -m scripts.run_streaming_anomaly_benchmark --root experiments_data --levels small medium --seeds 42

Replays the Phase 76 labeled anomaly dataset through `StreamingAnomalyDetector` and the batch epoch-boundary scorer,
prints quality / equivalence, then real processing time and detection latency at increasing offered rates.
Scratch captures live under `<root>/streaming_scratch_*` and are deleted.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments import streaming_anomaly_benchmark as B
from experiments.matrix_runner import TOPOLOGY_LEVELS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--levels", nargs="*", choices=list(TOPOLOGY_LEVELS), default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    parser.add_argument("--skip-load", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    scratch = B.scratch_root(args.root)
    try:
        rows = B.run_quality(scratch, levels=args.levels, seeds=args.seeds)
        print(f"levels {args.levels}; completeness {list(B.COMPLETENESS)}; seeds {args.seeds}; {len(rows)} cells\n")
        print(B.format_quality(rows))
        if not args.skip_load:
            print("\n" + B.format_load(B.run_load_sweep(scratch)))
    finally:
        B.cleanup(scratch)


if __name__ == "__main__":
    main()
