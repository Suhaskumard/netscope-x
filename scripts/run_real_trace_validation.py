"""Phase 103: run the full pipeline on real pcaps YOU supply and print an honest proxy-metric report.

    python -m scripts.run_real_trace_validation --traces-dir path/to/pcaps [--root experiments_data] [--labels labels.json]

Real traces have no ground-truth topology, so every metric is a proxy. With no pcaps this prints NOT RUN and no numbers.
`labels.json` (optional): {"<pcap filename>": {"edges": [["10.0.0.1", "10.0.0.2"], ...]}} for a true edge precision/recall.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.real_trace_validation import DEFAULT_MAX_BYTES, render_markdown, run_validation


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traces-dir", type=Path, default=Path("experiments_data/real_traces"))
    ap.add_argument("--root", type=Path, default=Path("experiments_data"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--labels", type=Path, default=None)
    args = ap.parse_args()
    report = run_validation(args.traces_dir, args.root, args.seed, args.max_bytes, args.labels)
    print(render_markdown(report))
    print(f"report written to {args.root / 'real_trace_validation'}")


if __name__ == "__main__":
    main()
