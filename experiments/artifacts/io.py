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
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Type, TypeVar, Union

from pydantic import BaseModel

from experiments.artifacts.ground_truth_manifest import GroundTruthManifest, GroundTruthManifestEntry
from experiments.artifacts.paths import ground_truth_generation_dir, ground_truth_manifest_path

M = TypeVar("M", bound=BaseModel)


def write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")


def read_json(path: Path, model_cls: Type[M]) -> M:
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, models: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for model in models:
            f.write(model.model_dump_json())
            f.write("\n")


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
    path.write_text(content, encoding="utf-8")
    digest = _sha256_of_text(content)
    _sidecar_path(path).write_text(digest, encoding="utf-8")
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
