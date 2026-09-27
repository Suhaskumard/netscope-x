"""Phase 106: the reproducibility runner's parser/comparator/end-to-end behavior, on real pytest runs of a tiny generated suite."""
import json
import sys
from pathlib import Path

from scripts.run_reproducibility_check import compare, parse_pytest_summary, run_layer

GOOD = {"passed": 2, "failed": 0, "skipped": 1, "errors": 0, "exit_code": 0}


def _obs(**over):
    layer = {**GOOD, **over}
    return {"layers": {"x": layer}, "gates": {"data_contracts": {"passed": 55, "total": 55, "exit_code": 0},
                                              "ground_truth_boundary": {"clean": True, "exit_code": 0}}}


def _exp():
    return {"layers": {"x": {"passed": 2, "failed": 0, "skipped": 1, "errors": 0}}, "gates": {"data_contracts": {"passed": 55, "total": 55}}}


def test_parse_summary_variants():
    assert parse_pytest_summary("....\n3 passed, 1 skipped in 0.20s") == {"passed": 3, "failed": 0, "skipped": 1, "errors": 0}
    assert parse_pytest_summary("1 failed, 2 passed, 1 error in 1.0s")["errors"] == 1
    assert parse_pytest_summary("no tests ran in 0.01s") == {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}


def test_compare_matches_and_flags_planted_differences():
    assert compare(_obs(), _exp()) == []
    assert any("passed observed 1" in p for p in compare(_obs(passed=1), _exp()))
    assert any("failed" in p for p in compare(_obs(failed=1, exit_code=1), _exp()))
    bad_gate = _obs()
    bad_gate["gates"]["ground_truth_boundary"]["clean"] = False
    assert any("not clean" in p for p in compare(bad_gate, _exp()))


def test_run_layer_counts_a_real_pytest_run(tmp_path: Path):
    d = tmp_path / "suite"
    d.mkdir()
    (d / "test_a.py").write_text("import pytest\ndef test_ok():\n    assert True\n"
                                 "def test_bad():\n    assert False\n"
                                 "@pytest.mark.skip\ndef test_skip():\n    pass\n")
    r = run_layer(tmp_path, "suite")
    assert (r["passed"], r["failed"], r["skipped"]) == (1, 1, 1)
    assert r["exit_code"] != 0


def test_committed_manifest_is_well_formed():
    m = json.loads((Path(__file__).resolve().parents[2] / "repro" / "expected_results.json").read_text())
    assert set(m["layers"]) == {"backend/tests", "experiments/tests", "simulator/tests"}
    assert all(v["failed"] == 0 and v["errors"] == 0 for v in m["layers"].values())
    assert m["gates"]["data_contracts"]["passed"] == m["gates"]["data_contracts"]["total"]
