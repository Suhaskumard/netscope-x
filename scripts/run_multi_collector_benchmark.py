"""CLI for Phase 90's multi-collector benchmark (spec addendum Phase 90). Logic lives in
`experiments/multi_collector_benchmark.py` (importable); this is a thin wrapper.

    python -m scripts.run_multi_collector_benchmark
    python -m scripts.run_multi_collector_benchmark --levels small --seeds 42 --skip-cost

Simulates collectors from scenario traffic and reports: equivalence of the fused graph to the full capture, quality of
the pooled-evidence resolution vs alternatives, the conflicts found, the measured failure cases, and ingest cost.
"""

from __future__ import annotations

import argparse

from experiments import multi_collector_benchmark as B


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="*", default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    parser.add_argument("--skip-cost", action="store_true")
    args = parser.parse_args()
    print("EQUIVALENCE (union of collectors == full capture)\n" + B.format_equivalence(B.run_equivalence(args.levels, args.seeds)))
    for drop in (0.0, 0.3, 0.8):
        print(f"\nQUALITY / CONFLICTS (N=3, overlap 0.3, packet loss {drop})\n"
              + B.format_quality(B.run_quality(args.levels, args.seeds, drop=drop)))
    print("\nFAILURE CASES\n" + B.format_failures(B.run_failures(seeds=args.seeds)))
    if not args.skip_cost:
        print("\nCOST\n" + B.run_cost())


if __name__ == "__main__":
    main()
