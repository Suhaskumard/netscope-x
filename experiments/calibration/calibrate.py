"""Automated calibration of the "provisional, pending Phase 68" constants (spec Phase 82).

Each constant group (`constants.GROUPS`) is tuned by Bayesian optimization (`bayes_opt.optimize`) on TRAIN
seeds against its stage's real matrix metric (F1 over `run_matrix_cell`), then baseline and tuned values are
re-scored on disjoint VALIDATION seeds over the full completeness range. The decision rule (`decide`) is fixed
in advance and never looks at anything but validation numbers:

  adopt a group's new values only if the validation objective improves by more than the baseline's own
  across-seed standard deviation (and by more than 0), AND no guard metric (another stage's F1) falls by
  more than its own baseline standard deviation. Otherwise the current values are kept.

Groups run in order and each is tuned on top of the values adopted so far; a final joint validation re-scores
every adopted value together against the untouched defaults. For adopted groups a one-at-a-time revert
measures each constant's marginal contribution, so "before/after" is reported per constant as well as per
group. The tool only reports: applying an adopted value to `Settings` is a deliberate manual step.

Cells are the real Phase 68 cells (`run_matrix_cell`, `evaluate_anomaly=False` -- no calibrated constant
touches the anomaly context), each run in a throwaway directory. The causal context is scored on default-volume
cells only: the Phase 74 low-volume sweep has no lag pulses, so it carries no causal signal.
"""

from __future__ import annotations

import shutil
import statistics
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.metric import MetricContext
from experiments.calibration.bayes_opt import BOResult, optimize
from experiments.calibration.constants import GROUPS, SPACE, CalibrationConstants, Group
from experiments.matrix_runner import (
    OBSERVATION_COMPLETENESS_LEVELS,
    SENSITIVITY_SWEEP,
    TOPOLOGY_LEVELS,
    run_matrix_cell,
)

TRAIN_SEEDS: List[int] = [42, 43, 44]
VALIDATION_SEEDS: List[int] = [100, 101, 102, 103]
TRAIN_COMPLETENESS: List[float] = [1.0, 0.5]
CausalOnly = (MetricContext.CAUSAL_ANALYSIS,)

Cell = Tuple[str, float, bool]  # (topology level, completeness, low-volume sweep variant)
Scores = Dict[MetricContext, List[float]]  # context -> per-seed mean F1 over cells


def cell_set(levels: Optional[Sequence[str]] = None, completeness: Sequence[float] = tuple(TRAIN_COMPLETENESS)) -> List[Cell]:
    return [(l, c, low) for l in (levels or list(TOPOLOGY_LEVELS)) for c in completeness for low in (False, True)]


class Evaluator:
    """Runs matrix cells for given constants and caches per-(constants, seed, cell) F1s."""

    def __init__(self, scratch: Path) -> None:
        self.scratch = scratch
        self._cache: Dict[tuple, Dict[MetricContext, Optional[float]]] = {}
        self.cells_run = 0

    def cell(self, constants: CalibrationConstants, seed: int, cell: Cell) -> Dict[MetricContext, Optional[float]]:
        key = (tuple(constants.as_dict().values()), seed, cell)
        if key not in self._cache:
            level, completeness, low = cell
            kwargs = (
                {"variant": SENSITIVITY_SWEEP["variant"], "packets_per_edge": SENSITIVITY_SWEEP["packets_per_edge"],
                 "pulse_cycles": SENSITIVITY_SWEEP["pulse_cycles"]} if low else {}
            )
            self.scratch.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(dir=self.scratch))
            try:
                result = run_matrix_cell(
                    work, level, completeness, seed=seed, constants=constants, evaluate_anomaly=False, **kwargs
                )
            finally:
                shutil.rmtree(work, ignore_errors=True)
            self.cells_run += 1
            self._cache[key] = {m.context: m.f1 for m in result.metrics}
        return self._cache[key]

    def scores(self, constants: CalibrationConstants, seeds: Sequence[int], cells: Sequence[Cell]) -> Scores:
        out: Scores = {ctx: [] for ctx in (
            MetricContext.TOPOLOGY_RECONSTRUCTION, MetricContext.TEMPORAL_ANALYSIS, MetricContext.CAUSAL_ANALYSIS)}
        for seed in seeds:
            values: Dict[MetricContext, List[float]] = {ctx: [] for ctx in out}
            for cell in cells:
                for ctx, f1 in self.cell(constants, seed, cell).items():
                    if ctx not in values or f1 is None or (ctx in CausalOnly and cell[2]):
                        continue
                    values[ctx].append(f1)
            for ctx, vs in values.items():
                if vs:
                    out[ctx].append(statistics.fmean(vs))
        return out


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else float("nan")


def _stdev(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


@dataclass(frozen=True)
class Decision:
    adopt: bool
    objective_gain: float
    baseline_spread: float
    guard_changes: Dict[str, float]
    reasons: List[str]


def decide(baseline: Scores, tuned: Scores, objective: MetricContext, guards: Sequence[MetricContext]) -> Decision:
    """The pre-registered adoption rule (see module docstring). Per-seed lists are paired by position."""
    if len(baseline[objective]) != len(tuned[objective]) or not baseline[objective]:
        raise ValueError("baseline and tuned scores must cover the same, non-empty seed set")
    gain = _mean(tuned[objective]) - _mean(baseline[objective])
    spread = _stdev(baseline[objective])
    reasons: List[str] = []
    ok = True
    if not gain > max(spread, 1e-9):
        ok = False
        reasons.append(f"{objective.value} gain {gain:+.4f} does not exceed baseline seed spread {spread:.4f}")
    guard_changes: Dict[str, float] = {}
    for g in guards:
        if not baseline.get(g) or len(baseline[g]) != len(tuned.get(g, [])):
            continue
        change = _mean(tuned[g]) - _mean(baseline[g])
        guard_changes[g.value] = change
        if change < -max(_stdev(baseline[g]), 1e-9):
            ok = False
            reasons.append(f"guard {g.value} regressed {change:+.4f} (beyond its baseline spread)")
    if ok:
        reasons.append(f"{objective.value} gain {gain:+.4f} exceeds baseline seed spread {spread:.4f}; no guard regressed")
    return Decision(ok, gain, spread, guard_changes, reasons)


@dataclass
class ConstantReport:
    name: str
    default: float
    tuned: float
    adopted: bool
    marginal_gain: Optional[float]  # validation objective lost when this constant alone is reverted (adopted groups)


@dataclass
class GroupReport:
    group: str
    objective: str
    bo_evaluations: int
    train_baseline: float
    train_best: float
    validation_baseline: float
    validation_tuned: float
    decision: Decision
    constants: List[ConstantReport]
    history: List[Dict] = field(default_factory=list)


@dataclass
class CalibrationReport:
    groups: List[GroupReport]
    adopted: CalibrationConstants
    joint_baseline: Scores
    joint_adopted: Scores
    train_seeds: List[int]
    validation_seeds: List[int]
    validation_cells: int
    cells_run: int
    not_calibratable: List[str]


NOT_CALIBRATABLE = [
    "path_engine._DEFAULT_LATENCY_COST_SCALE: only used for LATENCY_INJECTION scenarios; the matrix injects "
    "NODE_FAILURE only, so no matrix metric can move with it. Left at 100.0 ms, still provisional.",
]


def calibrate(
    root: Path,
    groups: Sequence[Group] = GROUPS,
    train_seeds: Optional[Sequence[int]] = None,
    validation_seeds: Optional[Sequence[int]] = None,
    train_cells: Optional[Sequence[Cell]] = None,
    validation_cells: Optional[Sequence[Cell]] = None,
    n_init: int = 6,
    n_iter: int = 18,
    seed: int = 0,
) -> CalibrationReport:
    train_seeds = list(train_seeds if train_seeds is not None else TRAIN_SEEDS)
    validation_seeds = list(validation_seeds if validation_seeds is not None else VALIDATION_SEEDS)
    if set(train_seeds) & set(validation_seeds):
        raise ValueError("train_seeds and validation_seeds must be disjoint")
    train_cells = list(train_cells if train_cells is not None else cell_set())
    validation_cells = list(
        validation_cells if validation_cells is not None else cell_set(completeness=OBSERVATION_COMPLETENESS_LEVELS)
    )
    evaluator = Evaluator(root / "calibration_scratch")
    baseline = CalibrationConstants()
    current = baseline
    reports: List[GroupReport] = []

    for group in groups:
        dims = [SPACE[name] for name in group.constants]
        start = {name: getattr(current, name) for name in group.constants}

        def objective(params: Dict[str, float]) -> float:
            scores = evaluator.scores(replace(current, **params), train_seeds, train_cells)
            return _mean(scores[group.objective])

        bo: BOResult = optimize(objective, dims, n_init=n_init, n_iter=n_iter, seed=seed, start=start)
        candidate = replace(current, **bo.best_params)

        base_val = evaluator.scores(current, validation_seeds, validation_cells)
        tuned_val = evaluator.scores(candidate, validation_seeds, validation_cells)
        decision = decide(base_val, tuned_val, group.objective, group.guards)

        constants: List[ConstantReport] = []
        for name in group.constants:
            marginal = None
            if decision.adopt:
                reverted = evaluator.scores(replace(candidate, **{name: getattr(current, name)}),
                                            validation_seeds, validation_cells)
                marginal = _mean(tuned_val[group.objective]) - _mean(reverted[group.objective])
            constants.append(ConstantReport(
                name=name, default=getattr(baseline, name),
                tuned=getattr(candidate, name), adopted=decision.adopt, marginal_gain=marginal))
        reports.append(GroupReport(
            group=group.name, objective=group.objective.value, bo_evaluations=bo.evaluations,
            train_baseline=bo.history[0]["value"], train_best=bo.best_value,
            validation_baseline=_mean(base_val[group.objective]), validation_tuned=_mean(tuned_val[group.objective]),
            decision=decision, constants=constants, history=bo.history))
        if decision.adopt:
            current = candidate

    return CalibrationReport(
        groups=reports, adopted=current,
        joint_baseline=evaluator.scores(baseline, validation_seeds, validation_cells),
        joint_adopted=evaluator.scores(current, validation_seeds, validation_cells),
        train_seeds=train_seeds, validation_seeds=validation_seeds, validation_cells=len(validation_cells),
        cells_run=evaluator.cells_run, not_calibratable=list(NOT_CALIBRATABLE),
    )


def format_report(report: CalibrationReport) -> str:
    lines = [
        f"train seeds {report.train_seeds}; validation seeds {report.validation_seeds} "
        f"({report.validation_cells} cells per seed); {report.cells_run} cells run",
        "",
        "| group | objective | validation before | validation after | gain | baseline spread | decision |",
        "|---|---|---|---|---|---|---|",
    ]
    for g in report.groups:
        lines.append(
            f"| {g.group} | {g.objective} F1 | {g.validation_baseline:.4f} | {g.validation_tuned:.4f} | "
            f"{g.decision.objective_gain:+.4f} | {g.decision.baseline_spread:.4f} | "
            f"{'ADOPT' if g.decision.adopt else 'keep'} |")
    lines += ["", "| constant | default | tuned | adopted | marginal validation gain |", "|---|---|---|---|---|"]
    for g in report.groups:
        for c in g.constants:
            marginal = "n/a" if c.marginal_gain is None else f"{c.marginal_gain:+.4f}"
            lines.append(f"| {c.name} | {c.default:g} | {c.tuned:.4g} | {'yes' if c.adopted else 'no'} | {marginal} |")
    lines += ["", "| context | joint baseline | joint adopted |", "|---|---|---|"]
    for ctx, values in report.joint_baseline.items():
        lines.append(f"| {ctx.value} | {_mean(values):.4f} | {_mean(report.joint_adopted[ctx]):.4f} |")
    lines += [""] + [f"NOT CALIBRATABLE: {n}" for n in report.not_calibratable]
    return "\n".join(lines)
