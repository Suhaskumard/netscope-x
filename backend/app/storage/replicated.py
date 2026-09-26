"""Replicated artifact storage (spec Phase 93).

A `ReplicatedStore` keeps `primary` (the artifact root this instance writes to) mirrored into `replicas` (other
directories: separate volumes, or another instance's primary). Every copy is temp-file + fsync + atomic rename, so a
killed process never leaves a half-written file. Each root carries `_replication/hashes.json` (rel path -> sha256 of
the content at the last commit), which is how a corrupt copy is told apart from a good one.

Not a consensus system: one writer per file at a time is assumed (see docs/architecture/high_availability.md).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

META_DIR = "_replication"
HASHES = f"{META_DIR}/hashes.json"
TMP_SUFFIX = ".tmp-repl"


class QuorumError(Exception):
    """A commit reached fewer replicas than the configured minimum."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    with src.open("rb") as fin, tmp.open("wb") as fout:
        shutil.copyfileobj(fin, fout)
        fout.flush()
        os.fsync(fout.fileno())
    shutil.copystat(src, tmp)
    os.replace(tmp, dst)


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _files(root: Path, under: Optional[Path] = None) -> list[str]:
    base = under or root
    if not base.exists():
        return []
    out = []
    for p in base.rglob("*"):
        if p.is_file() and not p.name.endswith(TMP_SUFFIX):
            rel = p.relative_to(root).as_posix()
            if not rel.startswith(META_DIR + "/"):
                out.append(rel)
    return sorted(out)


def _is_commit_marker(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.endswith(".sha256") or "manifest" in name


@dataclass
class RepairReport:
    copied: int = 0
    corrupt_fixed: int = 0
    unrecoverable: list[str] = field(default_factory=list)


class ReplicatedStore:
    def __init__(self, primary: Path, replicas: list[Path], min_replicas: int = 0, commit_delay: float = 0.0) -> None:
        self.primary = primary
        self.replicas = replicas
        self.min_replicas = min_replicas or len(replicas)  # 0 = every replica must succeed
        self._commit_delay = commit_delay  # test hook: pause between files to widen the kill window

    def _hashes(self, root: Path) -> dict[str, str]:
        p = root / HASHES
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        except json.JSONDecodeError:
            return {}

    def commit(self, subtree: Optional[Path] = None) -> int:
        """Replicate new/changed files under `subtree` (default: whole primary). Data files first, then commit
        markers (manifests / .sha256), so a replica never holds a marker without the data it vouches for.
        Returns replicas reached; raises QuorumError below `min_replicas`."""
        rels = _files(self.primary, subtree)
        rels.sort(key=lambda r: (_is_commit_marker(r), r))
        hashes = self._hashes(self.primary)
        for rel in rels:
            hashes[rel] = sha256_file(self.primary / rel)
        _write_json_atomic(self.primary / HASHES, hashes)
        reached = 0
        for replica in self.replicas:
            try:
                for rel in rels:
                    src, dst = self.primary / rel, replica / rel
                    if not dst.is_file() or dst.stat().st_size != src.stat().st_size or sha256_file(dst) != hashes[rel]:
                        _copy_atomic(src, dst)
                        if self._commit_delay:
                            time.sleep(self._commit_delay)
                merged = {**self._hashes(replica), **{r: hashes[r] for r in rels}}
                _write_json_atomic(replica / HASHES, merged)
                reached += 1
            except OSError:
                continue
        if reached < self.min_replicas:
            raise QuorumError(f"replicated to {reached}/{len(self.replicas)} replicas, need {self.min_replicas}")
        return reached

    def verify(self, root: Path) -> list[str]:
        """Rel paths under `root` whose content no longer matches its recorded hash."""
        rec = self._hashes(root)
        return [r for r in _files(root) if r in rec and sha256_file(root / r) != rec[r]]

    def repair(self) -> RepairReport:
        """Make every root hold a good copy of every file: fill missing copies, overwrite corrupt ones (a copy that
        disagrees with its own root's recorded hash) from the newest good copy. Reports what cannot be recovered."""
        roots = [self.primary, *self.replicas]
        report = RepairReport()
        recs = {r: self._hashes(r) for r in roots}
        rels = sorted({rel for r in roots for rel in _files(r)})
        for rel in rels:
            good, bad = [], []
            for r in roots:
                p = r / rel
                if not p.is_file():
                    continue
                (bad if rel in recs[r] and sha256_file(p) != recs[r][rel] else good).append(r)
            if not good:
                report.unrecoverable.append(rel)
                continue
            src_root = max(good, key=lambda r: (r / rel).stat().st_mtime_ns)
            src = src_root / rel
            src_hash = sha256_file(src)
            for r in roots:
                p = r / rel
                if r in bad:
                    _copy_atomic(src, p)
                    report.corrupt_fixed += 1
                elif not p.is_file():
                    _copy_atomic(src, p)
                    report.copied += 1
                elif sha256_file(p) != src_hash and p.stat().st_mtime_ns < src.stat().st_mtime_ns:
                    _copy_atomic(src, p)  # stale good copy
                    report.copied += 1
                recs[r][rel] = src_hash
        for r in roots:
            _write_json_atomic(r / HASHES, recs[r])
        return report

    def read_path(self, rel: str) -> Path:
        """Primary path for `rel`, first repairing it from a replica if it is corrupt or missing."""
        p = self.primary / rel
        if (not p.is_file()) or rel in self.verify(self.primary):
            self.repair()
        if not p.is_file():
            raise FileNotFoundError(rel)
        return p
