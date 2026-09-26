"""Reproducible research artifact I/O (spec Phase 10).

Generic read/write helpers over the Phase 04 Pydantic schemas -- one
implementation per serialization shape (single JSON object, JSON Lines
collection, hashed ground truth), reused across every artifact type
rather than one bespoke serializer per type (spec §7 anti-duplication
principle).

Ground-truth artifacts get an extra content-hash sidecar file, verified
on every read (spec Phase 10). `write_ground_truth_generation`/
`read_ground_truth_generation` add a numbered-generation manifest on top,
so re-running a ground-truth generator never silently overwrites a prior
generation (spec Phase 17: "version and hash ground-truth artifacts;
prevent accidental contamination of inference").

`write_experiment_run`/`read_experiment_run` apply the same numbered-generation convention to
experiment results (spec addendum Phase 75): re-running a matrix cell either refuses or writes a
new `v<N>/` run, never overwriting an earlier run's `experiment.json`/`metrics.jsonl`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Tuple, Type, TypeVar, Union

from pydantic import BaseModel

from backend.app.models import Experiment, MetricResult
from experiments.artifacts.experiment_manifest import ExperimentManifest, ExperimentManifestEntry
from experiments.artifacts.ground_truth_manifest import GroundTruthManifest, GroundTruthManifestEntry
from experiments.artifacts.paths import (
    experiment_manifest_path,
    experiment_path,
    experiment_run_dir,
    ground_truth_generation_dir,
    ground_truth_manifest_path,
    metrics_path,
)

M = TypeVar("M", bound=BaseModel)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via temp file + fsync + os.replace, so a killed process never leaves a partial file (Phase 93)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-repl")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, model: BaseModel) -> None:
    atomic_write_text(path, model.model_dump_json(indent=2))


def read_json(path: Path, model_cls: Type[M]) -> M:
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, models: Iterable[BaseModel]) -> None:
    atomic_write_text(path, "".join(model.model_dump_json() + "\n" for model in models))


def read_jsonl(path: Path, model_cls: Type[M]) -> List[M]:
    items: List[M] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(model_cls.model_validate_json(line))
    return items


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sidecar_path(path: Path) -> Path:
    return path.parent / f"{path.name}.sha256"


class GroundTruthIntegrityError(Exception):
    """Raised when a ground-truth artifact's content does not match its recorded hash,
    or the hash sidecar is missing entirely."""


def write_ground_truth(path: Path, model: BaseModel) -> str:
    """Writes the ground-truth JSON plus a `<name>.sha256` sidecar. Returns the hash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = model.model_dump_json(indent=2)
    atomic_write_text(path, content)
    digest = _sha256_of_text(content)
    atomic_write_text(_sidecar_path(path), digest)
    return digest


def read_ground_truth(path: Path, model_cls: Type[M]) -> M:
    """Reads a ground-truth artifact and verifies its content hash before returning it.

    Raises GroundTruthIntegrityError if the sidecar is missing or the content
    hash does not match -- this is what prevents an accidentally (or
    maliciously) modified ground-truth file from silently contaminating
    inference or evaluation (spec Phase 17; spec §4 ground-truth rule).
    """
    sidecar = _sidecar_path(path)
    if not sidecar.exists():
        raise GroundTruthIntegrityError(f"missing hash sidecar for ground truth artifact: {path}")
    content = path.read_text(encoding="utf-8")
    expected = sidecar.read_text(encoding="utf-8").strip()
    actual = _sha256_of_text(content)
    if actual != expected:
        raise GroundTruthIntegrityError(
            f"ground truth artifact hash mismatch for {path}: expected {expected}, got {actual}"
        )
    return model_cls.model_validate_json(content)


def _read_manifest_if_exists(root: Path, capture_id: str) -> GroundTruthManifest:
    manifest_path = ground_truth_manifest_path(root, capture_id)
    if not manifest_path.exists():
        return GroundTruthManifest(capture_id=capture_id, generations=[])
    return read_ground_truth(manifest_path, GroundTruthManifest)


def write_ground_truth_generation(
    root: Path, capture_id: str, artifacts: Dict[str, BaseModel]
) -> GroundTruthManifestEntry:
    """Writes one new, numbered ground-truth generation without touching any prior generation
    (spec Phase 17: "version and hash ground-truth artifacts"; earlier calls' `v<N>/` directories
    are never overwritten, so regenerating ground truth for the same capture_id can never
    silently destroy an earlier generation).

    `artifacts` maps an artifact filename (e.g. "topology.json") to the Pydantic model to persist.
    Returns the manifest entry recorded for this generation.
    """
    manifest = _read_manifest_if_exists(root, capture_id)
    next_version = (manifest.latest_version + 1) if manifest.generations else 1
    gen_dir = ground_truth_generation_dir(root, capture_id, next_version)

    files: Dict[str, str] = {}
    for filename, model in artifacts.items():
        digest = write_ground_truth(gen_dir / filename, model)
        files[filename] = digest

    entry = GroundTruthManifestEntry(version=next_version, generated_at=datetime.now(timezone.utc), files=files)
    manifest.generations.append(entry)
    write_ground_truth(ground_truth_manifest_path(root, capture_id), manifest)
    return entry


def read_ground_truth_generation(
    root: Path,
    capture_id: str,
    model_classes: Dict[str, Type[BaseModel]],
    version: Union[int, Literal["latest"]] = "latest",
) -> Dict[str, BaseModel]:
    """Reads one ground-truth generation, verifying integrity at two independent layers: each
    artifact's own content-hash sidecar (as `read_ground_truth` always does), and a cross-check
    against the hash the manifest recorded for that artifact at generation time -- catching a
    manifest edited out of sync with its artifacts, not just a single tampered file.

    `model_classes` maps an artifact filename to the Pydantic model class to parse it as.
    """
    manifest = read_ground_truth(ground_truth_manifest_path(root, capture_id), GroundTruthManifest)
    resolved_version = manifest.latest_version if version == "latest" else version
    entry = manifest.entry_for(resolved_version)
    gen_dir = ground_truth_generation_dir(root, capture_id, resolved_version)

    result: Dict[str, BaseModel] = {}
    for filename, model_cls in model_classes.items():
        if filename not in entry.files:
            raise GroundTruthIntegrityError(
                f"manifest for capture_id={capture_id!r} version={resolved_version} has no record of {filename!r}"
            )
        model = read_ground_truth(gen_dir / filename, model_cls)
        actual_digest = _sha256_of_text(model.model_dump_json(indent=2))
        if actual_digest != entry.files[filename]:
            raise GroundTruthIntegrityError(
                f"manifest/artifact hash mismatch for {filename!r} in capture_id={capture_id!r} "
                f"version={resolved_version}: manifest says {entry.files[filename]}, artifact is {actual_digest}"
            )
        result[filename] = model
    return result


# --- experiment runs (spec addendum Phase 75) ---

OnExisting = Literal["version", "refuse"]
EXPERIMENT_FILENAME = "experiment.json"
METRICS_FILENAME = "metrics.jsonl"


class ExperimentExistsError(Exception):
    """Raised when persisting a run for an experiment_id that already has one, under the
    `"refuse"` policy -- or when asked to write a run version that is already taken."""


class ExperimentIntegrityError(Exception):
    """Raised when a recorded experiment run's file no longer matches the manifest's hash."""


def _read_experiment_manifest_if_exists(root: Path, experiment_id: str) -> Optional[ExperimentManifest]:
    path = experiment_manifest_path(root, experiment_id)
    if not path.exists():
        return None
    return read_ground_truth(path, ExperimentManifest)


def _has_legacy_run(root: Path, experiment_id: str) -> bool:
    return experiment_path(root, experiment_id).is_file()


def next_experiment_version(root: Path, experiment_id: str, on_existing: OnExisting = "version") -> int:
    """The run number the next persisted run of `experiment_id` will get: `1` if none exists yet,
    else one past the latest (a legacy pre-Phase-75 flat run counts as version 1). Raises
    `ExperimentExistsError` under `on_existing="refuse"` if any run already exists. Read-only."""
    if on_existing not in ("version", "refuse"):
        raise ValueError(f"unknown on_existing policy {on_existing!r}; choose 'version' or 'refuse'")
    manifest = _read_experiment_manifest_if_exists(root, experiment_id)
    if manifest is not None and manifest.runs:
        existing = manifest.latest_version
    elif _has_legacy_run(root, experiment_id):
        existing = 1
    else:
        return 1
    if on_existing == "refuse":
        raise ExperimentExistsError(
            f"experiment_id={experiment_id!r} already has run v{existing}; refusing to persist another"
        )
    return existing + 1


def _write_run_files(run_dir: Path, contents: Dict[str, str]) -> Dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=False)
    files: Dict[str, str] = {}
    for filename, text in contents.items():
        atomic_write_text(run_dir / filename, text)
        files[filename] = _sha256_of_text(text)
    return files


def _adopt_legacy_run(root: Path, experiment_id: str) -> ExperimentManifest:
    """Copies (never moves or edits) a legacy flat run into `v1/` and records it as version 1."""
    contents = {EXPERIMENT_FILENAME: experiment_path(root, experiment_id).read_text(encoding="utf-8")}
    if metrics_path(root, experiment_id).is_file():
        contents[METRICS_FILENAME] = metrics_path(root, experiment_id).read_text(encoding="utf-8")
    files = _write_run_files(experiment_run_dir(root, experiment_id, 1), contents)
    entry = ExperimentManifestEntry(
        version=1, recorded_at=datetime.now(timezone.utc), capture_id=experiment_id, files=files
    )
    return ExperimentManifest(experiment_id=experiment_id, runs=[entry])


def write_experiment_run(
    root: Path,
    experiment: Experiment,
    metrics: Iterable[MetricResult],
    capture_id: Optional[str] = None,
    on_existing: OnExisting = "version",
    version: Optional[int] = None,
) -> ExperimentManifestEntry:
    """Persists one run of `experiment` as a new numbered `v<N>/` directory and records it in the
    experiment's hash-protected manifest, without touching any earlier run.

    `version` is normally left `None` (resolved via `next_experiment_version` under
    `on_existing`); a caller that reserved it before running (`run_and_persist_cell`) passes it
    explicitly, and it must still be unused -- `ExperimentExistsError` otherwise.
    """
    experiment_id = experiment.experiment_id
    if version is None:
        version = next_experiment_version(root, experiment_id, on_existing)

    manifest = _read_experiment_manifest_if_exists(root, experiment_id)
    if manifest is None:
        manifest = (
            _adopt_legacy_run(root, experiment_id)
            if _has_legacy_run(root, experiment_id)
            else ExperimentManifest(experiment_id=experiment_id, runs=[])
        )
    run_dir = experiment_run_dir(root, experiment_id, version)
    if run_dir.exists() and not any(r.version == version for r in manifest.runs):
        shutil.rmtree(run_dir)  # orphan of a run interrupted before its manifest entry (the commit point)
    if any(r.version == version for r in manifest.runs) or run_dir.exists():
        raise ExperimentExistsError(f"experiment_id={experiment_id!r} run v{version} already exists")

    metrics_text = "".join(m.model_dump_json() + "\n" for m in metrics)
    files = _write_run_files(
        experiment_run_dir(root, experiment_id, version),
        {EXPERIMENT_FILENAME: experiment.model_dump_json(indent=2), METRICS_FILENAME: metrics_text},
    )
    entry = ExperimentManifestEntry(
        version=version, recorded_at=datetime.now(timezone.utc), capture_id=capture_id or experiment_id, files=files
    )
    manifest.runs.append(entry)
    write_ground_truth(experiment_manifest_path(root, experiment_id), manifest)
    return entry


def read_experiment_manifest(root: Path, experiment_id: str) -> ExperimentManifest:
    return read_ground_truth(experiment_manifest_path(root, experiment_id), ExperimentManifest)


def read_experiment_run(
    root: Path, experiment_id: str, version: Union[int, Literal["latest"]] = "latest"
) -> Tuple[Experiment, List[MetricResult]]:
    """Reads one recorded run, verifying each file against the manifest's recorded hash (the
    manifest itself is sidecar-hash-verified). With no manifest, falls back to the legacy flat
    layout, which only ever holds a single, unverified run (version 1 / "latest")."""
    manifest = _read_experiment_manifest_if_exists(root, experiment_id)
    if manifest is None:
        if not _has_legacy_run(root, experiment_id) or version not in ("latest", 1):
            raise ValueError(f"no run version={version!r} recorded for experiment_id={experiment_id!r}")
        experiment = read_json(experiment_path(root, experiment_id), Experiment)
        legacy_metrics = metrics_path(root, experiment_id)
        return experiment, (read_jsonl(legacy_metrics, MetricResult) if legacy_metrics.is_file() else [])

    resolved = manifest.latest_version if version == "latest" else version
    entry = manifest.entry_for(resolved)
    run_dir = experiment_run_dir(root, experiment_id, resolved)
    texts: Dict[str, str] = {}
    for filename, expected in entry.files.items():
        text = (run_dir / filename).read_text(encoding="utf-8")
        actual = _sha256_of_text(text)
        if actual != expected:
            raise ExperimentIntegrityError(
                f"hash mismatch for {filename!r} in experiment_id={experiment_id!r} v{resolved}: "
                f"manifest says {expected}, file is {actual}"
            )
        texts[filename] = text
    experiment = Experiment.model_validate_json(texts[EXPERIMENT_FILENAME])
    metrics = [
        MetricResult.model_validate_json(line)
        for line in texts.get(METRICS_FILENAME, "").splitlines()
        if line.strip()
    ]
    return experiment, metrics
