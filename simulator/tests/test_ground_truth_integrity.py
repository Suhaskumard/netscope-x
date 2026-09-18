"""Phase 17 ground-truth integrity tests.

Covers the two gaps left open by Phase 16 (per docs/architecture/ground_truth.md's "Explicitly
deferred (Phase 17)" section): versioning multiple generations of the same capture_id, and a
structural safeguard preventing inference code from importing simulator.ground_truth.
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.models import Edge, Node, TopologyGraph
from experiments.artifacts import io, paths
from scripts.check_ground_truth_boundary import find_violations

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _graph(graph_id: str) -> TopologyGraph:
    n1 = Node(node_id="n1", ip_addresses=["10.0.0.1"], first_observed=NOW, last_observed=NOW)
    n2 = Node(node_id="n2", ip_addresses=["10.0.0.2"], first_observed=NOW, last_observed=NOW)
    e1 = Edge(
        edge_id="e1",
        source_node_id="n1",
        target_node_id="n2",
        confidence=1.0,
        evidence=["ground truth"],
        observation_count=1,
        first_observed=NOW,
        last_observed=NOW,
        protocols=["TCP"],
    )
    return TopologyGraph(graph_id=graph_id, generated_at=NOW, nodes=[n1, n2], edges=[e1])


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def test_first_generation_is_version_1(tmp_path: Path) -> None:
    entry = io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    assert entry.version == 1
    assert "topology.json" in entry.files


def test_second_generation_does_not_overwrite_the_first(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    entry2 = io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g2")})

    assert entry2.version == 2

    v1_dir = paths.ground_truth_generation_dir(tmp_path, "cap1", 1)
    v2_dir = paths.ground_truth_generation_dir(tmp_path, "cap1", 2)
    assert (v1_dir / "topology.json").exists()
    assert (v2_dir / "topology.json").exists()

    v1_graph = io.read_ground_truth(v1_dir / "topology.json", TopologyGraph)
    v2_graph = io.read_ground_truth(v2_dir / "topology.json", TopologyGraph)
    assert v1_graph.graph_id == "g1"
    assert v2_graph.graph_id == "g2"


def test_manifest_lists_every_generation(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g2")})

    manifest = io.read_ground_truth(paths.ground_truth_manifest_path(tmp_path, "cap1"), io.GroundTruthManifest)
    assert [g.version for g in manifest.generations] == [1, 2]
    assert manifest.capture_id == "cap1"
    assert manifest.latest_version == 2


def test_latest_resolves_to_the_most_recent_generation(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g2")})

    loaded = io.read_ground_truth_generation(tmp_path, "cap1", {"topology.json": TopologyGraph}, version="latest")
    assert loaded["topology.json"].graph_id == "g2"


def test_explicit_old_version_is_still_readable_after_a_newer_generation_exists(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g2")})

    loaded = io.read_ground_truth_generation(tmp_path, "cap1", {"topology.json": TopologyGraph}, version=1)
    assert loaded["topology.json"].graph_id == "g1"


def test_generation_tamper_detection_still_fires_per_file(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    gen_dir = paths.ground_truth_generation_dir(tmp_path, "cap1", 1)
    artifact_path = gen_dir / "topology.json"
    tampered = artifact_path.read_text(encoding="utf-8").replace('"g1"', '"g1-tampered"')
    artifact_path.write_text(tampered, encoding="utf-8")

    with pytest.raises(io.GroundTruthIntegrityError):
        io.read_ground_truth_generation(tmp_path, "cap1", {"topology.json": TopologyGraph}, version=1)


def test_manifest_artifact_hash_mismatch_is_detected(tmp_path: Path) -> None:
    """Simulates a manifest edited out of sync with its artifact: the artifact's own sidecar
    is re-signed to match the tampered content (so the per-file check alone would pass), but the
    manifest still records the original hash -- the cross-check must catch this."""
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    gen_dir = paths.ground_truth_generation_dir(tmp_path, "cap1", 1)
    artifact_path = gen_dir / "topology.json"

    tampered_graph = _graph("g1-tampered")
    io.write_ground_truth(artifact_path, tampered_graph)  # re-signs the sidecar to match

    with pytest.raises(io.GroundTruthIntegrityError):
        io.read_ground_truth_generation(tmp_path, "cap1", {"topology.json": TopologyGraph}, version=1)


def test_reading_an_unrecorded_version_raises(tmp_path: Path) -> None:
    io.write_ground_truth_generation(tmp_path, "cap1", {"topology.json": _graph("g1")})
    with pytest.raises(ValueError):
        io.read_ground_truth_generation(tmp_path, "cap1", {"topology.json": TopologyGraph}, version=99)


# ---------------------------------------------------------------------------
# Structural safeguard against inference-pipeline contamination
# ---------------------------------------------------------------------------


def test_boundary_checker_finds_no_violations_in_the_real_repository() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = find_violations(repo_root)
    assert violations == []


def test_boundary_checker_flags_a_disallowed_import(tmp_path: Path) -> None:
    """Proves the checker would actually catch a real violation, not merely that it stays
    silent because it was never exercised against one."""
    (tmp_path / "simulator").mkdir()
    (tmp_path / "simulator" / "ground_truth").mkdir()
    (tmp_path / "simulator" / "ground_truth" / "__init__.py").write_text("", encoding="utf-8")

    # A stand-in for future inference code, deliberately placed OUTSIDE the allowlist
    # (simulator/, experiments/, scripts/, tests/) -- e.g. a future nettrace/ package.
    nettrace_dir = tmp_path / "nettrace"
    nettrace_dir.mkdir()
    (nettrace_dir / "topology.py").write_text(
        textwrap.dedent(
            """
            from simulator.ground_truth import topology as gt_topology

            def infer():
                return gt_topology.SERVICE_ROLES
            """
        ),
        encoding="utf-8",
    )

    violations = find_violations(tmp_path)
    assert len(violations) == 1
    assert violations[0].file == Path("nettrace") / "topology.py"


def test_boundary_checker_allows_simulator_and_experiments_and_test_code(tmp_path: Path) -> None:
    (tmp_path / "simulator").mkdir()
    (tmp_path / "simulator" / "ground_truth").mkdir()
    (tmp_path / "simulator" / "ground_truth" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "simulator" / "ground_truth" / "cli.py").write_text(
        "from simulator.ground_truth import generate\n", encoding="utf-8"
    )

    experiments_dir = tmp_path / "experiments" / "runners"
    experiments_dir.mkdir(parents=True)
    (experiments_dir / "evaluate.py").write_text(
        "from simulator.ground_truth.models import GroundTruthRoles\n", encoding="utf-8"
    )

    backend_tests_dir = tmp_path / "backend" / "tests"
    backend_tests_dir.mkdir(parents=True)
    (backend_tests_dir / "test_something.py").write_text(
        "import simulator.ground_truth\n", encoding="utf-8"
    )

    assert find_violations(tmp_path) == []
