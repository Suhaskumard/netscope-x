"""CLI for Phase 68's full experimental matrix (FR-1.40). Logic lives in
`experiments/matrix_runner.py` (importable, unit-tested); this is a thin
wrapper, the same "script is a thin CLI over an importable module"
pattern `simulator/scenarios/cli.py` already uses.

Run the full 6 topology levels x 5 observation-completeness levels, plus
the 4 ablation studies (one per topology level at completeness=1.0):
    python -m scripts.run_experiment_matrix --root experiments_data

Results are persisted under `<root>/experiments/<experiment_id>/`
(`experiment.json` + `metrics.jsonl`), readable back via `GET /experiments`
/`GET /metrics` once wired to the same root.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.matrix_runner import run_full_matrix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-ablations", action="store_true", help="Skip the 4 ablation studies.")
    args = parser.parse_args()

    results = run_full_matrix(args.root, run_ablations=not args.no_ablations, seed=args.seed)

    print(f"Ran {len(results)} experiment cells, persisted under {args.root / 'experiments'}.")
    for cell in results:
        print(f"  {cell.experiment.experiment_id}: {len(cell.metrics)} metrics")


if __name__ == "__main__":
    main()
