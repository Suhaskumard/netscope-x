"""Reproducible research artifact I/O (spec Phase 10).

Generic read/write helpers over the Phase 04 Pydantic schemas -- one
implementation per serialization shape (single JSON object, JSON Lines
collection, hashed ground truth), reused across every artifact type
rather than one bespoke serializer per type (spec §7 anti-duplication
principle).

Ground-truth artifacts get an extra content-hash sidecar file, verified
on every read (spec Phase 17: "version and hash ground-truth artifacts;
prevent accidental contamination of inference").
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List, Type, TypeVar

from pydantic import BaseModel

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
