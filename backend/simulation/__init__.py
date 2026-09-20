"""SIMULATION: controlled failure injection, dynamic path analysis, and
failure propagation over a digital twin's topology (spec Phases 59-61,
"Failure Injection Framework, Dynamic Path Engine, Failure Propagation
Simulator").

Phase 59 (`failure_injection.py`) applies a `FailureScenario`
(`backend.app.models.failure`, Phase 04) to a `TopologyGraph`, producing
an isolated, possibly-modified copy -- no path-cost computation (Phase
60's job) and no composition with Phase 54's `propagate_failure` into a
full pipeline (Phase 61's job) happen here.

Never imports `simulator.ground_truth` (spec §4;
`scripts/check_ground_truth_boundary.py` would reject it if it did).
"""
