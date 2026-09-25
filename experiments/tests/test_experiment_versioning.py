"""Phase 75: experiment idempotency and versioning -- re-running the same
(topology_level, completeness, seed) cell must never destroy the first run's results."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.models.metric import MetricResult
from experiments.artifacts.io import (
    ExperimentExistsError,
    ExperimentIntegrityError,
    next_experiment_version,
    read_experiment_manifest,
    read_experiment_run,
    write_json,
    write_jsonl,
)
from experiments.artifacts.paths import (
    capture_dir,
    experiment_dir,
    experiment_path,
    experiment_run_dir,
    metrics_path,
    snapshots_dir,
)
from experiments.matrix_runner import persist_cell, run_and_persist_cell, run_matrix_cell


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_files_digest(root: Path, experiment_id: str, version: int) -> dict:
    run_dir = experiment_run_dir(root, experiment_id, version)
    return {f.name: _digest(f) for f in sorted(run_dir.iterdir())}


def test_rerunning_a_cell_preserves_the_first_run(tmp_path: Path) -> None:
    first = run_and_persist_cell(tmp_path, "small", 1.0, seed=4)
    exp_id = first.experiment.experiment_id
    v1_before = _run_files_digest(tmp_path, exp_id, 1)
    v1_capture_files = sorted(p.name for p in capture_dir(tmp_path, exp_id).rglob("*") if p.is_file())

    second = run_and_persist_cell(tmp_path, "small", 1.0, seed=4)

    assert second.experiment.experiment_id == exp_id
    assert _run_files_digest(tmp_path, exp_id, 1) == v1_before  # v1 bytes untouched
    assert (experiment_run_dir(tmp_path, exp_id, 2) / "experiment.json").is_file()

    manifest = read_experiment_manifest(tmp_path, exp_id)
    assert [r.version for r in manifest.runs] == [1, 2]
    assert manifest.entry_for(1).capture_id == exp_id
    assert manifest.entry_for(2).capture_id == f"{exp_id}-v2"
    assert first.experiment.configuration["run_version"] == 1
    assert second.experiment.configuration["run_version"] == 2

    # the first run's capture directory was not rewritten or appended to
    assert sorted(p.name for p in capture_dir(tmp_path, exp_id).rglob("*") if p.is_file()) == v1_capture_files
    assert len(list(snapshots_dir(tmp_path, exp_id).glob("*.json"))) == 2
    assert capture_dir(tmp_path, f"{exp_id}-v2").is_dir()


def test_read_latest_versus_specific_version(tmp_path: Path) -> None:
    run_and_persist_cell(tmp_path, "small", 1.0, seed=4)
    run_and_persist_cell(tmp_path, "small", 1.0, seed=4)
    exp_id = "matrix-small-1p0-baseline-4"

    latest, latest_metrics = read_experiment_run(tmp_path, exp_id)
    first, first_metrics = read_experiment_run(tmp_path, exp_id, version=1)
    assert latest.configuration["run_version"] == 2
    assert first.configuration["run_version"] == 1
    assert len(latest_metrics) == len(first_metrics) >= 1
    assert all(isinstance(m, MetricResult) for m in latest_metrics)
    with pytest.raises(ValueError):
        read_experiment_run(tmp_path, exp_id, version=3)


def test_refuse_policy_raises_and_writes_nothing(tmp_path: Path) -> None:
    first = run_and_persist_cell(tmp_path, "small", 1.0, seed=4, on_existing="refuse")
    exp_id = first.experiment.experiment_id
    before = _run_files_digest(tmp_path, exp_id, 1)
    captures_before = sorted(p.name for p in (tmp_path / "captures").iterdir())

    with pytest.raises(ExperimentExistsError):
        run_and_persist_cell(tmp_path, "small", 1.0, seed=4, on_existing="refuse")

    assert _run_files_digest(tmp_path, exp_id, 1) == before
    assert sorted(p.name for p in (tmp_path / "captures").iterdir()) == captures_before  # failed fast
    assert [r.version for r in read_experiment_manifest(tmp_path, exp_id).runs] == [1]


def test_unknown_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        next_experiment_version(tmp_path, "anything", "overwrite")  # type: ignore[arg-type]


def test_different_seed_is_a_different_experiment(tmp_path: Path) -> None:
    run_and_persist_cell(tmp_path, "small", 1.0, seed=4, on_existing="refuse")
    run_and_persist_cell(tmp_path, "small", 1.0, seed=5, on_existing="refuse")  # no collision


def test_explicit_taken_version_is_refused(tmp_path: Path) -> None:
    cell = run_and_persist_cell(tmp_path, "small", 1.0, seed=4)
    with pytest.raises(ExperimentExistsError):
        persist_cell(tmp_path, cell, version=1)


def test_tampered_run_file_is_detected(tmp_path: Path) -> None:
    cell = run_and_persist_cell(tmp_path, "small", 1.0, seed=4)
    exp_id = cell.experiment.experiment_id
    path = experiment_run_dir(tmp_path, exp_id, 1) / "metrics.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ExperimentIntegrityError):
        read_experiment_run(tmp_path, exp_id, version=1)


def test_legacy_flat_run_is_adopted_as_v1_without_being_modified(tmp_path: Path) -> None:
    cell = run_matrix_cell(tmp_path, "small", 1.0, seed=4)
    exp_id = cell.experiment.experiment_id
    write_json(experiment_path(tmp_path, exp_id), cell.experiment)  # pre-Phase-75 flat layout
    write_jsonl(metrics_path(tmp_path, exp_id), cell.metrics)
    legacy = (_digest(experiment_path(tmp_path, exp_id)), _digest(metrics_path(tmp_path, exp_id)))

    assert read_experiment_run(tmp_path, exp_id)[0].experiment_id == exp_id  # fallback read works
    with pytest.raises(ExperimentExistsError):
        next_experiment_version(tmp_path, exp_id, "refuse")

    run_and_persist_cell(tmp_path, "small", 1.0, seed=4)

    assert (_digest(experiment_path(tmp_path, exp_id)), _digest(metrics_path(tmp_path, exp_id))) == legacy
    assert [r.version for r in read_experiment_manifest(tmp_path, exp_id).runs] == [1, 2]
    assert read_experiment_run(tmp_path, exp_id, version=1)[0].experiment_id == exp_id
    assert experiment_dir(tmp_path, exp_id).is_dir()
