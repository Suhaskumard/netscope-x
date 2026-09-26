"""CLI for Phase 95's PCAP vs NetFlow v5 / IPFIX consistency benchmark. Logic lives in
`experiments/flow_export_benchmark.py`."""

from __future__ import annotations

import argparse

from experiments import flow_export_benchmark as B


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", nargs="*", default=list(B.LEVELS))
    parser.add_argument("--seeds", nargs="*", type=int, default=list(B.SEEDS))
    args = parser.parse_args()
    print(B.format_rows(B.run(args.levels, args.seeds)))


if __name__ == "__main__":
    main()
