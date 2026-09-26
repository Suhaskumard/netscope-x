"""Phase 93 replicated store tests (pure filesystem)."""

from __future__ import annotations

import pytest

from backend.app.storage.replicated import HASHES, QuorumError, ReplicatedStore, sha256_file


@pytest.fixture()
def store(tmp_path):
    return ReplicatedStore(tmp_path / "p", [tmp_path / "r1", tmp_path / "r2"])


def _put(root, rel, data: bytes):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_commit_replicates_byte_equal(store) -> None:
    _put(store.primary, "captures/c1/raw.pcap", b"\x01" * 5000)
    _put(store.primary, "captures/c1/manifest.json", b"{}")
    assert store.commit() == 2
    for r in store.replicas:
        for rel in ("captures/c1/raw.pcap", "captures/c1/manifest.json"):
            assert (r / rel).read_bytes() == (store.primary / rel).read_bytes()
        assert not list(r.rglob("*.tmp-repl"))


def test_corrupt_primary_detected_and_repaired(store) -> None:
    _put(store.primary, "a/x.bin", b"good-content")
    store.commit()
    (store.primary / "a/x.bin").write_bytes(b"bit-rot!")
    assert store.verify(store.primary) == ["a/x.bin"]
    assert store.read_path("a/x.bin").read_bytes() == b"good-content"
    assert store.verify(store.primary) == []


def test_missing_replica_file_repaired(store) -> None:
    _put(store.primary, "a/x.bin", b"data")
    store.commit()
    (store.replicas[1] / "a/x.bin").unlink()
    report = store.repair()
    assert report.copied == 1 and (store.replicas[1] / "a/x.bin").read_bytes() == b"data"


def test_lost_primary_recovered_from_replica(store) -> None:
    _put(store.primary, "a/x.bin", b"data")
    store.commit()
    (store.primary / "a/x.bin").unlink()
    assert store.read_path("a/x.bin").read_bytes() == b"data"


def test_all_copies_corrupt_is_reported_not_hidden(store) -> None:
    _put(store.primary, "a/x.bin", b"data")
    store.commit()
    for r in (store.primary, *store.replicas):
        (r / "a/x.bin").write_bytes(b"XXXX")
    assert store.repair().unrecoverable == ["a/x.bin"]


def test_quorum_failure_raises(tmp_path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, so mkdir under it fails")
    s = ReplicatedStore(tmp_path / "p", [tmp_path / "ok", blocker / "sub"], min_replicas=2)
    _put(s.primary, "a.bin", b"1")
    with pytest.raises(QuorumError):
        s.commit()
    s.min_replicas = 1
    assert s.commit() == 1


def test_manifests_replicated_after_data(tmp_path, monkeypatch) -> None:
    order = []
    import backend.app.storage.replicated as m

    real = m._copy_atomic
    monkeypatch.setattr(m, "_copy_atomic", lambda s, d: (order.append(d.name), real(s, d))[1])
    s = ReplicatedStore(tmp_path / "p", [tmp_path / "r"])
    _put(s.primary, "e/manifest.json", b"{}")
    _put(s.primary, "e/manifest.json.sha256", b"h")
    _put(s.primary, "e/v1/metrics.jsonl", b"x")
    s.commit()
    assert order[0] == "metrics.jsonl" and set(order[1:]) == {"manifest.json", "manifest.json.sha256"}


def test_atomic_write_leaves_no_partial_file_when_interrupted(tmp_path, monkeypatch) -> None:
    import os

    from experiments.artifacts.io import atomic_write_text

    target = tmp_path / "f.json"
    atomic_write_text(target, "old")

    def boom(*a, **k):
        raise KeyboardInterrupt  # simulates death after the temp write, before the rename

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(KeyboardInterrupt):
        atomic_write_text(target, "new-content-that-is-longer")
    assert target.read_text() == "old"  # never partial


def test_hash_record_written(store) -> None:
    _put(store.primary, "a.bin", b"1")
    store.commit()
    assert (store.replicas[0] / HASHES).is_file()
    assert sha256_file(store.primary / "a.bin")
