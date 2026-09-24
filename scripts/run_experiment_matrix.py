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

Phase 72 multi-seed variance run (every cell once per seed, then
mean ± stdev [min, max] tables printed as Markdown):
    python -m scripts.run_experiment_matrix --root experiments_data --n-seeds 10
    python -m scripts.run_experiment_matrix --root experiments_data --seeds 42 43 44

Phase 73 per-target failure/counterfactual report (single-seed run only):
    python -m scripts.run_experiment_matrix --root experiments_data --targets

Phase 74: every run also includes the low-volume completeness-sensitivity sweep
(`matrix_runner.SENSITIVITY_SWEEP`) and prints its per-completeness table;
`--no-sensitivity-sweep` skips it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from experiments.matrix_runner import format_sensitivity_table, format_target_report, run_full_matrix
from experiments.multi_seed import format_markdown_table, run_multi_seed_matrix

# Headline (context, field) pairs printed for a multi-seed run -- the same
# per-context analogues `matrix_runner._to_metric_result` maps onto `MetricResult`.
_HEADLINE_COLUMNS = [
    ("topology_reconstruction", "f1"),
    ("topology_reconstruction", "graph_similarity"),
    ("role_inference", "precision"),
    ("role_inference", "calibration_error"),
    ("temporal_analysis", "f1"),
    ("causal_analysis", "f1"),
    ("pathforge", "f1"),
    ("counterfactual", "f1"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments_data"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-ablations", action="store_true", help="Skip the 4 ablation studies.")
    parser.add_argument("--targets", action="store_true", help="Phase 73: print the per-failure-target report.")
    parser.add_argument("--no-sensitivity-sweep", action="store_true", help="Phase 74: skip the low-volume sweep.")
    seeds_group = parser.add_mutually_exclusive_group()
    seeds_group.add_argument("--seeds", type=int, nargs="+", help="Phase 72: run every cell once per listed seed.")
    seeds_group.add_argument("--n-seeds", type=int, help="Phase 72: run every cell for seeds --seed .. --seed+N-1.")
    args = parser.parse_args()

    seeds = args.seeds or (list(range(args.seed, args.seed + args.n_seeds)) if args.n_seeds else None)
    if seeds is not None:
        summaries = run_multi_seed_matrix(
            args.root, seeds=seeds, run_ablations=not args.no_ablations, run_sensitivity_sweep=not args.no_sensitivity_sweep
        )
        print(f"Ran {len(summaries)} cells x {len(seeds)} seeds {seeds}, persisted under {args.root / 'experiments'}.")
        for context, field in _HEADLINE_COLUMNS:
            print(f"\n### {context} {field}\n")
            print(format_markdown_table(summaries, [(context, field)]))
        return

    results = run_full_matrix(
        args.root, run_ablations=not args.no_ablations, seed=args.seed, run_sensitivity_sweep=not args.no_sensitivity_sweep
    )

    print(f"Ran {len(results)} experiment cells, persisted under {args.root / 'experiments'}.")
    for cell in results:
        print(f"  {cell.experiment.experiment_id}: {len(cell.metrics)} metrics")
    if args.targets:
        print("\n### Phase 73 failure targets\n")
        print(format_target_report(results))
    if not args.no_sensitivity_sweep:
        print("\n### Phase 74 completeness sensitivity (low-volume sweep)\n")
        print(format_sensitivity_table(results))


if __name__ == "__main__":
    main()
